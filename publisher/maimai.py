"""
脉脉发帖模块 —— 通过 MultiPost 发布到脉脉

完整流程：
  1. MaimaiPoster 是薄包装，委托 MultiPostPublisher 打开 MultiPost 编辑器、填入标题/正文、选中「脉脉」、点击发布
  2. MultiPost 会复用已有 maimai.cn 标签页并填入内容（不新开标签页）
  3. MultiPostPublisher._publish_maimai 在脉脉标签页上执行脉脉特有操作：
     切换身份 → (按需补填) → 添加话题 → 勾选两个发布设置开关 → 点击「发动态」

脉脉特有的 DOM 操作（添加话题、勾选开关等）封装在 MaimaiPageOps mixin 里，
供 MultiPostPublisher 继承使用。

⚠️  前置条件：
  - Chrome 带调试端口(9222)启动
  - 已登录 multipost.app 和 maimai.cn

⚠️  风险提示：
  - 发布是真实操作，会创建真实内容
  - 批量发帖需控制频率，建议每篇间隔 3 分钟
"""

import platform
import random
import time
from typing import Optional, List

# 跨平台快捷键：Mac 用 Meta(Command)，Windows/Linux 用 Control
SELECT_ALL_KEY = "Meta+A" if platform.system() == "Darwin" else "Control+A"

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from loguru import logger

from config import settings, PROJECT_ROOT


# ========== 常量 ==========

CDP_URL = "http://localhost:9222"
MAIMAI_HOME_URL = "https://maimai.cn/community/home/recommended"
DEFAULT_TOPIC = "我来爆个料"


class MaimaiPageOps:
    """
    脉脉页面 DOM 操作 mixin —— 方法只依赖 `page` 参数，不依赖连接状态。

    供 MultiPostPublisher 继承：在 MultiPost 打开并填好的脉脉标签页上执行
    脉脉特有的「添加话题 + 勾选两个发布设置开关 + 点发动态」操作。

    方法用 `_maimai_` 前缀避免与 MultiPostPublisher 已有的
    `_fill_content`/`_upload_images`/`_click_publish`（签名/语义不同）冲突。
    截图走 `self._save_screenshot`（由 MultiPostPublisher 提供）。
    """

    def _maimai_switch_identity(self, page: Page):
        """确保身份为'职场领域创作者'（幂等；只点元素不刷页）"""
        logger.info("检查发帖身份...")

        # 检查当前身份文本是否包含"职场领域创作者"
        current = page.evaluate('''() => {
            const all = document.querySelectorAll('span, div');
            for (const el of all) {
                const t = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if (t.includes('职场领域创作者') && t.length < 30
                    && rect.width > 50 && rect.width < 300
                    && rect.y > 80 && rect.y < 200) {
                    return t.substring(0, 30);
                }
            }
            return '';
        }''')

        if '职场领域创作者' in current:
            logger.info("  ✓ 身份已是职场领域创作者")
            return

        logger.info("  切换身份为职场领域创作者...")

        clicked_switch = page.evaluate('''() => {
            const all = document.querySelectorAll('span, a, div');
            for (const el of all) {
                const t = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if (t === '切换' && rect.y > 80 && rect.y < 200
                    && rect.width > 10 && rect.width < 80) {
                    el.click();
                    return true;
                }
            }
            return false;
        }''')

        if not clicked_switch:
            logger.warning("  ⚠️ 未找到切换按钮")
            return

        time.sleep(2)

        selected = page.evaluate('''() => {
            const all = document.querySelectorAll('span, div, li, p');
            for (const el of all) {
                const t = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if (t === '职场领域创作者' && el.children.length === 0
                    && rect.width > 50 && rect.width < 300) {
                    el.click();
                    return true;
                }
            }
            return false;
        }''')

        if selected:
            logger.success("  ✓ 已切换为职场领域创作者")
        else:
            logger.warning("  ⚠️ 未找到职场领域创作者选项")
        time.sleep(1)

    def _maimai_fill_title(self, page: Page, title: str):
        """填入标题，标题为空则跳过"""
        if not title or not title.strip():
            logger.info("  标题为空，跳过填入")
            return
        logger.info(f"填入标题: {title[:20]}...")
        title = title[:20]

        title_input = page.locator('input[placeholder*="标题"]')
        if title_input.count() > 0:
            title_input.first.click()
            title_input.first.fill("")
            title_input.first.fill(title)
            logger.success(f"  ✓ 标题已填入: {title}")
        else:
            filled = page.evaluate('''(title) => {
                const inputs = document.querySelectorAll('input');
                for (const input of inputs) {
                    const ph = (input.placeholder || '') + (input.getAttribute('aria-label') || '');
                    if (ph.includes('标题')) {
                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
                            window.HTMLInputElement.prototype, 'value'
                        ).set;
                        nativeInputValueSetter.call(input, title);
                        input.dispatchEvent(new Event('input', { bubbles: true }));
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                        return true;
                    }
                }
                return false;
            }''', title)
            if filled:
                logger.success(f"  ✓ 标题已填入: {title}")
            else:
                logger.warning("  ⚠️ 未找到标题输入框（标题为选填，继续）")

        time.sleep(0.5)

    def _maimai_clear_form(self, page: Page):
        """清空发帖表单"""
        logger.debug("清空表单残留内容...")

        title_input = page.locator('input[placeholder*="标题"]')
        if title_input.count() > 0:
            title_input.first.fill("")

        editor = page.locator('[contenteditable="true"]')
        if editor.count() > 0:
            editor.first.click()
            page.keyboard.press(SELECT_ALL_KEY)
            page.keyboard.press("Backspace")
            time.sleep(0.3)

        page.evaluate('''() => {
            const closeButtons = document.querySelectorAll('svg, button, div');
            for (const btn of closeButtons) {
                const rect = btn.getBoundingClientRect();
                if (rect.width > 0 && rect.width < 25 && rect.height > 0 && rect.height < 25
                    && rect.y > 250 && rect.y < 320) {
                    const svg = btn.querySelector('svg');
                    if (svg && (btn.getAttribute('aria-label')?.includes('关闭')
                        || btn.getAttribute('aria-label')?.includes('close')
                        || (btn.textContent || '').trim() === '×')) {
                        btn.click();
                    }
                }
            }
        }''')

        time.sleep(0.3)

    def _maimai_fill_content(self, page: Page, content: str):
        """填入正文"""
        logger.info(f"填入正文: {len(content)} 字")
        content = content[:1000]

        # 策略1：textarea
        textarea = page.locator('textarea[placeholder*="想法"], textarea[placeholder*="分享"]')
        if textarea.count() > 0:
            textarea.first.click()
            page.keyboard.press(SELECT_ALL_KEY)
            page.keyboard.press("Backspace")
            time.sleep(0.2)
            textarea.first.fill(content)
            logger.success(f"  ✓ 正文已填入 (textarea)")
            time.sleep(0.5)
            return

        # 策略2：contenteditable
        editor = page.locator('[contenteditable="true"]')
        if editor.count() > 0:
            editor.first.click()
            page.keyboard.press(SELECT_ALL_KEY)
            page.keyboard.press("Backspace")
            time.sleep(0.2)
            page.keyboard.type(content, delay=10)
            logger.success(f"  ✓ 正文已填入 (contenteditable)")
            time.sleep(0.5)
            return

        raise RuntimeError("未找到正文输入框")

    def _maimai_add_topic(self, page: Page, topic: str) -> bool:
        """
        添加话题 —— 带重试机制：
          1. 点击「添加话题」按钮
          2. 等待弹出面板（等待最多10秒）
          3. 在搜索框输入话题名称
          4. 点击搜索结果
        搜不到返回 False 让调用方刷新页面重试。
        """
        logger.info(f"添加话题: {topic}")

        # 1. 点击「添加话题」按钮
        clicked = page.evaluate('''() => {
            const all = document.querySelectorAll('div, span, label');
            let best = null;
            let bestArea = Infinity;

            for (const el of all) {
                const t = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                const cls = (el.className || '').toString();
                const area = rect.width * rect.height;

                if (t.includes('添加话题') && rect.y > 250 && rect.width > 0
                    && cls.includes('cursor-pointer')) {
                    if (area < bestArea) {
                        bestArea = area;
                        best = el;
                    }
                }
            }

            if (best) {
                best.click();
                return best.textContent.trim();
            }

            for (const el of all) {
                const t = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if ((t === '添加话题' || t === '# 添加话题') && rect.y > 250 && rect.width < 150) {
                    el.click();
                    return t;
                }
            }

            return false;
        }''')

        if not clicked:
            logger.warning("  ⚠️ 未找到'添加话题'按钮")
            return False

        logger.info(f"  已点击添加话题按钮: {clicked}")
        time.sleep(3)

        # 2. 在弹出面板的搜索框中输入话题名称（等待最多10秒）
        popup_search = None
        for _ in range(10):
            for inp in page.locator('input[type="search"]').all():
                try:
                    box = inp.bounding_box()
                    if box and box['y'] > 100 and box['width'] > 50:
                        popup_search = inp
                        break
                except Exception:
                    continue
            if not popup_search:
                for inp in page.locator('input[type="text"]').all():
                    try:
                        box = inp.bounding_box()
                        if box and box['y'] > 250 and box['width'] > 50:
                            popup_search = inp
                            break
                    except Exception:
                        continue
            if popup_search:
                break
            time.sleep(1)

        if not popup_search:
            logger.warning("  ⚠️ 搜索框未出现")
            return False

        popup_search.click()
        time.sleep(0.5)
        popup_search.fill(topic)
        logger.info(f"  已在弹出搜索框输入: {topic}")
        time.sleep(2)

        # 3. 点击搜索结果（精确匹配优先 → 前缀匹配 → 兜底点第一个结果）
        selected = page.evaluate('''(topic) => {
            const all = document.querySelectorAll('div');
            let exactRow = null;
            let exactLen = Infinity;
            let prefixRow = null;
            let prefixLen = Infinity;
            let firstRow = null;  // 兜底：第一个结果

            for (const el of all) {
                const t = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                const cls = (el.className || '').toString();

                if (!cls.includes('cursor-pointer') || rect.y < 300 || rect.height < 30 || rect.height > 60) continue;

                // 记录第一个结果（兜底用）
                if (!firstRow) firstRow = el;

                if (!t.includes(topic)) continue;

                const afterTopic = t.substring(topic.length);
                const isExactTopic = t.startsWith(topic) && (afterTopic.length === 0 || /^\\d/.test(afterTopic));

                if (isExactTopic) {
                    if (t.length < exactLen) { exactLen = t.length; exactRow = el; }
                } else {
                    if (t.length < prefixLen) { prefixLen = t.length; prefixRow = el; }
                }
            }

            const target = exactRow || prefixRow || firstRow;
            if (target) {
                const matchType = exactRow ? 'exact' : (prefixRow ? 'prefix' : 'first');
                target.click();
                return { match: matchType, text: target.textContent.trim().substring(0, 30) };
            }
            return null;
        }''', topic)

        if selected:
            match_type = selected.get('match', 'unknown')
            if match_type == 'first':
                logger.info(f"  ⚠️ 未找到精确匹配，使用第一个搜索结果: {selected.get('text', topic)}")
            logger.success(f"  ✓ 话题已点击: {selected.get('text', topic)}")
            time.sleep(2)
            page.keyboard.press("Escape")
            time.sleep(1)
            return True
        else:
            logger.warning("  ⚠️ 搜索结果为空，无法选择话题")
            return False

    def _maimai_upload_images(self, page: Page, image_paths: List[str]):
        """上传图片 —— 直接通过 #picture file input"""
        logger.info(f"上传图片: {len(image_paths)} 张")

        try:
            picture_input = page.locator('#picture')
            if picture_input.count() > 0:
                picture_input.set_input_files(image_paths)
                logger.info(f"  ✓ 上传 {len(image_paths)} 张图片成功 (#picture)")
                time.sleep(3)
            else:
                image_input = page.locator('input[type="file"][accept*="image"]')
                if image_input.count() > 0:
                    image_input.first.set_input_files(image_paths)
                    logger.info(f"  ✓ 上传 {len(image_paths)} 张图片成功 (file input)")
                    time.sleep(3)
                else:
                    logger.warning("  ⚠️ 未找到图片上传 file input")
        except Exception as e:
            logger.warning(f"  ⚠️ 图片上传异常: {e}")

        logger.success("✓ 图片上传完成")

    def _maimai_enable_publish_settings(self, page: Page):
        """确保发布设置面板中的两个开关已开启：
        1. 发布后同步到我的主页展示
        2. 使用昵称作为水印

        开关在页面刷新后状态会丢失，每次发帖前需检查。
        """
        logger.info("检查发布设置开关...")

        try:
            # 第1步：确保设置面板已展开
            panel_open = page.evaluate('''() => {
                const h3s = document.querySelectorAll('h3');
                for (const h3 of h3s) {
                    if ((h3.textContent || '').trim() === '发布设置'
                        && h3.getBoundingClientRect().width > 0) {
                        return true;
                    }
                }
                return false;
            }''')

            if not panel_open:
                clicked = page.evaluate('''() => {
                    // 策略1：找到"添加话题"文字，然后往左找最近的button
                    const allDivs = document.querySelectorAll('div');
                    let topicEl = null;
                    for (const div of allDivs) {
                        const t = (div.textContent || '').trim();
                        const rect = div.getBoundingClientRect();
                        if (t === '添加话题' && rect.width > 50 && rect.width < 150
                            && rect.height > 15 && rect.height < 30) {
                            topicEl = div;
                            break;
                        }
                    }

                    if (topicEl) {
                        const topicRect = topicEl.getBoundingClientRect();
                        const buttons = document.querySelectorAll('button');
                        let bestBtn = null;
                        let bestDist = Infinity;
                        for (const btn of buttons) {
                            const rect = btn.getBoundingClientRect();
                            const t = (btn.textContent || '').trim();
                            if (Math.abs(rect.y - topicRect.y) < 15
                                && rect.x < topicRect.x
                                && t !== '发动态' && t !== '发布'
                                && rect.width > 15 && rect.width < 40) {
                                const dist = topicRect.x - rect.x;
                                if (dist < bestDist) {
                                    bestDist = dist;
                                    bestBtn = btn;
                                }
                            }
                        }
                        if (bestBtn) {
                            bestBtn.click();
                            return { strategy: 'left_of_topic', x: Math.round(bestBtn.getBoundingClientRect().x) };
                        }
                    }

                    // 策略2：工具栏中所有24x24的无文字button，逐个点击直到面板出现
                    const buttons2 = document.querySelectorAll('button');
                    const candidates = [];
                    for (const btn of buttons2) {
                        const rect = btn.getBoundingClientRect();
                        const t = (btn.textContent || '').trim();
                        if (rect.width >= 20 && rect.width <= 30
                            && rect.height >= 20 && rect.height <= 30
                            && t === '' && rect.y > 300) {
                            candidates.push(btn);
                        }
                    }
                    candidates.sort((a, b) => a.getBoundingClientRect().x - b.getBoundingClientRect().x);
                    for (const btn of candidates) {
                        btn.click();
                        const h3s = document.querySelectorAll('h3');
                        for (const h3 of h3s) {
                            if ((h3.textContent || '').trim() === '发布设置'
                                && h3.getBoundingClientRect().width > 0) {
                                return { strategy: 'try_each_button', x: Math.round(btn.getBoundingClientRect().x) };
                            }
                        }
                    }

                    return null;
                }''')

                if clicked:
                    logger.info(f"  ⚙️ 点击设置按钮展开面板 (x≈{clicked.get('x')})")
                    time.sleep(1.5)
                else:
                    logger.info("  ⚙️ 未找到设置按钮，尝试直接检查开关...")

            # 第2步：检查并启用两个开关
            toggles_result = page.evaluate('''() => {
                const result = { sync_home: null, nickname_watermark: null, enabled: 0 };

                const switches = document.querySelectorAll('button[role="switch"]');
                for (const sw of switches) {
                    const ariaChecked = sw.getAttribute('aria-checked');
                    const swRect = sw.getBoundingClientRect();

                    const labels = document.querySelectorAll('label');
                    for (const label of labels) {
                        const labelText = (label.textContent || '').trim();
                        const labelRect = label.getBoundingClientRect();

                        if (Math.abs(labelRect.y - swRect.y) < 20 && labelRect.x < swRect.x) {
                            if (labelText.includes('发布后同步到我的主页展示')) {
                                result.sync_home = { ariaChecked };
                                if (ariaChecked !== 'true') {
                                    sw.click();
                                    result.enabled++;
                                }
                            } else if (labelText.includes('使用昵称作为水印')) {
                                result.nickname_watermark = { ariaChecked };
                                if (ariaChecked !== 'true') {
                                    sw.click();
                                    result.enabled++;
                                }
                            }
                        }
                    }
                }

                return result;
            }''')

            if toggles_result:
                sync = toggles_result.get('sync_home')
                watermark = toggles_result.get('nickname_watermark')

                if sync:
                    status = '✓ 已开启' if sync.get('ariaChecked') == 'true' else '✅ 未开启，已点击开启'
                    logger.info(f"  {status} \"发布后同步到我的主页展示\"")
                else:
                    logger.info("  ⚠️ 未找到\"发布后同步到我的主页展示\"开关")

                if watermark:
                    status = '✓ 已开启' if watermark.get('ariaChecked') == 'true' else '✅ 未开启，已点击开启'
                    logger.info(f"  {status} \"使用昵称作为水印\"")
                else:
                    logger.info("  ⚠️ 未找到\"使用昵称作为水印\"开关")

                if toggles_result.get('enabled', 0) > 0:
                    logger.info(f"  ✓ 发布设置检查完成，已启用 {toggles_result['enabled']} 个开关")
                    time.sleep(0.5)
                elif sync and watermark:
                    logger.info("  ✓ 发布设置检查完成，开关均已开启")
                else:
                    logger.info("  ⚠️ 发布设置检查完成，但部分开关未找到")
            else:
                logger.info("  ⚠️ 未找到发布设置开关（面板可能未展开）")

            # 第3步：关闭设置面板
            page.keyboard.press("Escape")
            time.sleep(0.5)

        except Exception as e:
            logger.warning(f"  ⚠️ 发布设置检查异常: {e}，跳过（不影响发帖）")

    def _maimai_click_publish(self, page: Page) -> bool:
        """点击'发动态'按钮。未找到按钮时返回 False（不 raise，避免中断其他平台）。"""
        logger.info("⚠️  点击'发动态'按钮...")

        page.keyboard.press("Escape")
        time.sleep(1)

        clicked = page.evaluate('''() => {
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                const t = (btn.textContent || '').trim();
                const rect = btn.getBoundingClientRect();
                if ((t === '发动态' || t === '发布') && rect.width > 0 && !btn.disabled) {
                    btn.click();
                    return { tag: 'button', text: t };
                }
            }
            const all = document.querySelectorAll('div, span');
            for (const el of all) {
                const t = (el.textContent || '').trim();
                const rect = el.getBoundingClientRect();
                if ((t === '发动态' || t === '发布') && rect.width > 50 && rect.y > 200) {
                    el.click();
                    return { tag: el.tagName, text: t };
                }
            }
            return null;
        }''')

        if not clicked:
            logger.warning("  ⚠️ 未找到'发动态'按钮")
            return False

        logger.info(f"  ✓ 已点击: {clicked.get('tag')}.{clicked.get('text')}")

        time.sleep(5)

        self._save_screenshot(page, f"maimai_after_post_{int(time.time())}")
        logger.success("✓ 发帖完成")
        return True


class MaimaiPoster:
    """
    脉脉发帖器（薄包装）—— 通过 MultiPost 发布到脉脉。

    内部委托 MultiPostPublisher：MultiPost 打开编辑器、填标题/正文、选中「脉脉」、
    点击发布；然后在脉脉标签页上执行 MaimaiPageOps 的特有操作（加话题/勾开关/发动态）。

    用法（签名与旧版完全一致，调用方零改动）：
        poster = MaimaiPoster()
        poster.connect()
        poster.batch_post(posts=[...], interval=180)
        poster.disconnect()
    """

    def __init__(self):
        self._multipost = None

    def connect(self) -> bool:
        """连接 Chrome（委托 MultiPostPublisher，共用一条 CDP 连接）"""
        from publisher.multipost import MultiPostPublisher  # lazy import 避免循环依赖
        self._multipost = MultiPostPublisher()
        return self._multipost.connect()

    def disconnect(self):
        """断开连接"""
        if self._multipost:
            self._multipost.disconnect()
            self._multipost = None
        logger.info("已断开 Chrome 连接")

    def post(
        self,
        content: str,
        title: str = "",
        image_paths: List[str] = None,
        topic: str = DEFAULT_TOPIC,
        dry_run: bool = False,
    ) -> bool:
        """单篇发帖（委托 MultiPostPublisher，platforms=['脉脉']）"""
        if not self._multipost:
            if not self.connect():
                return False
        # maimai 调用方传 "content"；MultiPostPublisher 用 "body"
        return self._multipost.publish(
            title=title,
            body=content,
            platforms=["脉脉"],
            image_paths=image_paths,
            maimai_topic=topic,
            dry_run=dry_run,
        )

    def batch_post(
        self,
        posts: List[dict],
        interval: int = 180,
        dry_run: bool = False,
    ) -> dict:
        """
        批量发帖 —— 委托 MultiPostPublisher.batch_post，篇间等待 interval 秒（±30秒抖动）。

        参数:
            posts:    帖子列表，每项 {"content": str, "title": str, "image_paths": list, "topic": str}
            interval: 发帖间隔秒数（调用方传 settings.maimai_post_interval / shandian_post_interval）
            dry_run:  干跑模式
        """
        if not self._multipost:
            if not self.connect():
                return {"success": 0, "failed": len(posts), "results": []}

        # 规范化：content -> body
        normalized = [{
            "title": p.get("title", ""),
            "body": p.get("content", ""),
            "image_paths": p.get("image_paths"),
            "topic": p.get("topic", DEFAULT_TOPIC),
        } for p in posts]

        return self._multipost.batch_post(
            posts=normalized,
            platforms=["脉脉"],
            interval=interval,
            dry_run=dry_run,
        )
