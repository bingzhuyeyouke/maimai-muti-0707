"""
MultiPost 发布模块 —— 自动操作 MultiPost 网页端发布内容到多平台

完整流程：
  1. 连接到用户已打开的 Chrome（带远程调试端口 9222）
  2. 打开 MultiPost 编辑器（multipost.app）
  3. 上传图片
  4. 填入标题和正文
  5. 点击「下一步」（蓝色箭头按钮）
  6. 取消全选，勾选目标平台（头条/公众号）
  7. 点击发布按钮
  8. 等待平台标签页打开，按优先级处理（脉脉→公众号→头条）
  9. 发布完成后自动清理标签页

⚠️  前置条件：
  - 用户需要先启动 Chrome 并打开远程调试端口：
    macOS:
      /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome \\
        --remote-debugging-port=9222 \\
        --user-data-dir=/tmp/chrome-automation-profile
    Windows:
      chrome.exe --remote-debugging-port=9222 --user-data-dir=%TEMP%\\chrome-automation-profile
  - 或直接运行: python3 start_chrome.py
  - 用户需要已登录 MultiPost（multipost.app）
  - 用户需要已登录各目标平台（头条/公众号/脉脉）

⚠️  风险提示：
  - 发布是真实操作，会在平台上创建真实内容
  - 建议先用测试内容验证流程，确认无误后再用正式内容
  - 不要短时间内大量发布，可能触发平台风控
"""

import json
import platform
import time
import urllib.request
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from loguru import logger

from config import settings, PROJECT_ROOT


# ========== 常量 ==========

# Chrome 远程调试地址
CDP_URL = "http://localhost:9222"

# MultiPost 编辑器地址
MULTIPOST_URL = "https://multipost.app/"

# 脉脉社区首页（发帖入口）
MAIMAI_HOME_URL = "https://maimai.cn/community/home/recommended"

# 脉脉默认话题
DEFAULT_TOPIC = "我来爆个料"

# 默认要发布的平台（优先级顺序：脉脉 → 公众号 → 头条）
DEFAULT_PLATFORMS = ["脉脉", "微信公众号", "今日头条"]

# MultiPost 扩展 ID
MULTIPOST_EXT_ID = "dhohkaclnjgcikfoaacfgijgjgceofih"


class MultiPostPublisher:
    """
    MultiPost 发布器

    用法：
        publisher = MultiPostPublisher()
        publisher.connect()
        publisher.publish(title="标题", body="正文", platforms=["今日头条", "微信公众号"])
        publisher.disconnect()
    """

    def __init__(self):
        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None

    def connect(self) -> bool:
        """
        连接到用户已启动的 Chrome 浏览器

        返回:
            True 连接成功，False 连接失败
        """
        logger.info(f"连接到 Chrome（{CDP_URL}）...")

        try:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.chromium.connect_over_cdp(CDP_URL)
            self._context = self._browser.contexts[0] if self._browser.contexts else None

            if not self._context:
                logger.error("❌ 未找到浏览器上下文")
                return False

            logger.success("✓ 已连接到 Chrome")
            return True

        except Exception as e:
            logger.error(f"❌ 连接 Chrome 失败: {e}")
            logger.info("请先启动 Chrome（带调试端口）：")
            if platform.system() == "Windows":
                logger.info(
                    "  chrome.exe --remote-debugging-port=9222 "
                    "--user-data-dir=%TEMP%\\chrome-automation-profile"
                )
            else:
                logger.info(
                    "  /Applications/Google\\ Chrome.app/Contents/MacOS/Google\\ Chrome "
                    "--remote-debugging-port=9222 "
                    "--user-data-dir=/tmp/chrome-automation-profile"
            )
            return False

    def disconnect(self):
        """断开连接（不关闭用户的 Chrome）"""
        # 不关闭 browser，因为是用户的 Chrome
        if self._playwright:
            self._playwright.stop()
        logger.info("已断开 Chrome 连接")

    def _reconnect(self):
        """
        重连 Playwright 以刷新页面列表

        当 Chrome 扩展（如 MultiPost）打开新标签页时，
        Playwright 的 CDP 连接不会自动追踪这些新页面。
        断开并重新连接可以获取最新的页面列表。
        """
        try:
            self._playwright.stop()
        except Exception:
            pass

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.connect_over_cdp(CDP_URL)
        self._context = self._browser.contexts[0] if self._browser.contexts else None

        if self._context:
            page_count = len(self._context.pages)
            logger.info(f"  ✓ 已重连，当前 {page_count} 个标签页")
        else:
            logger.warning("  ⚠️ 重连后未找到浏览器上下文")

    def publish(
        self,
        title: str,
        body: str,
        platforms: list[str] = None,
        image_paths: list[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """
        发布内容到 MultiPost

        参数:
            title:       文章标题
            body:        文章正文
            platforms:   目标平台列表，默认 ["微信公众号", "今日头条"]
            image_paths: 要上传的本地图片路径列表
            dry_run:     干跑模式——只填内容选平台，不点最终发布按钮

        返回:
            True 发布成功，False 失败
        """
        if platforms is None:
            platforms = DEFAULT_PLATFORMS

        try:
            # 第1步：打开 MultiPost 编辑器
            page = self._open_editor()

            # 第2步：上传图片（在填文字之前，因为上传后光标位置更可控）
            if image_paths:
                self._upload_images(page, image_paths)

            # 第3步：填入标题和正文
            self._fill_content(page, title, body)

            # 第4步：点击「下一步」
            self._click_next(page)

            # 第5步：先取消所有已勾选平台，再勾选目标平台
            self._deselect_all_platforms(page)
            self._select_platforms(page, platforms)

            if dry_run:
                logger.info("🔍 干跑模式：内容已填入，平台已选择，但不点击发布")
                page.screenshot(path="debug_screenshots/dry_run_preview.png", full_page=True)
                return True

            # 第6步：点击发布 + 处理平台标签页（按优先级：脉脉 → 公众号 → 头条）
            result = self._click_publish(page, title, body, platforms)

            return result

        except Exception as e:
            logger.error(f"❌ 发布失败: {e}")
            return False

    def _open_editor(self) -> Page:
        """第1步：打开或切换到 MultiPost 编辑器（确保在编辑状态，不是平台选择页）"""
        logger.info("打开 MultiPost 编辑器...")

        # 先看看是否已经打开了 multipost 页面
        found_page = None
        for pg in self._context.pages:
            if "multipost.app" in pg.url and "signin" not in pg.url:
                found_page = pg
                break

        if found_page:
            # 已有页面，刷新回到编辑器初始状态
            logger.info("  刷新页面回到编辑器...")
            found_page.goto(MULTIPOST_URL, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)
            self._page = found_page
        else:
            # 没有就新建
            page = self._context.new_page()
            page.goto(MULTIPOST_URL, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)
            self._page = page
            found_page = page

        # 检查是否被重定向到登录页
        if "signin" in found_page.url:
            raise RuntimeError("未登录 MultiPost，请先在 Chrome 中登录")

        # 验证编辑器是否就绪（检查是否有正文输入框）
        textarea = found_page.locator('textarea[placeholder*="内容"]')
        if textarea.count() == 0:
            logger.warning("  编辑器未就绪，再次刷新...")
            found_page.reload(wait_until="domcontentloaded", timeout=10000)
            time.sleep(3)

        logger.success("✓ 编辑器已打开")
        return found_page

    def _fill_content(self, page: Page, title: str, body: str):
        """第2步：填入标题和正文"""
        logger.info("填入内容...")

        # 填标题
        title_input = page.locator('input[placeholder*="标题"]')
        if title_input.count() > 0:
            title_input.click()
            title_input.fill(title)
            logger.info(f"  标题: {title}")
        else:
            logger.warning("  未找到标题输入框")

        time.sleep(0.5)

        # 填正文
        textarea = page.locator('textarea[placeholder*="内容"]')
        if textarea.count() > 0:
            textarea.click()
            textarea.fill(body)
            logger.info(f"  正文: {body[:50]}...")
        else:
            raise RuntimeError("未找到正文输入框")

        time.sleep(1)
        logger.success("✓ 内容已填入")

    def _click_next(self, page: Page):
        """第3步：点击蓝色「下一步」按钮"""
        logger.info("点击「下一步」...")

        # 找蓝色按钮（background-color: rgb(0, 111, 238)）
        clicked = page.evaluate('''() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                const style = getComputedStyle(btn);
                if (style.backgroundColor.includes('0, 111, 238')) {
                    const rect = btn.getBoundingClientRect();
                    if (rect.width > 100) {  // 确保是主按钮，不是小图标
                        btn.click();
                        return true;
                    }
                }
            }
            return false;
        }''')

        if not clicked:
            raise RuntimeError("未找到「下一步」按钮")

        time.sleep(3)  # 等待平台选择页加载
        logger.success("✓ 已进入平台选择页")

    def _select_platforms(self, page: Page, platforms: list[str]):
        """第5步：选择目标平台（先取消全选再勾选目标）"""
        logger.info(f"选择平台: {platforms}")

        # 先取消所有已勾选的平台
        self._deselect_all_platforms(page)

        for platform_name in platforms:
            result = self._select_single_platform(page, platform_name)
            if result:
                logger.info(f"  ✓ 已选择: {platform_name}")
            else:
                logger.warning(f"  ⚠️ 未找到或已选择: {platform_name}")
            time.sleep(0.5)

        logger.success(f"✓ 平台选择完成")

    def _deselect_all_platforms(self, page: Page):
        """取消所有已勾选的平台"""
        logger.info("取消所有已勾选的平台...")

        # 取消热门列表中已勾选的
        page.evaluate('''() => {
            const checkboxes = document.querySelectorAll('input[type="checkbox"]');
            let unchecked = 0;
            for (const cb of checkboxes) {
                if (cb.checked) {
                    cb.click();
                    unchecked++;
                }
            }
            return unchecked;
        }''')

        # 也检查「其他」分类下是否有已勾选的
        page.evaluate('''() => {
            const all = document.querySelectorAll('button, span, a, div');
            for (const el of all) {
                if (el.textContent.trim() === '其他') {
                    el.click();
                    return true;
                }
            }
            return false;
        }''')
        time.sleep(1)

        page.evaluate('''() => {
            const checkboxes = document.querySelectorAll('input[type="checkbox"]');
            for (const cb of checkboxes) {
                if (cb.checked) {
                    cb.click();
                }
            }
        }''')

        logger.info("  ✓ 已取消所有平台勾选")

    def _upload_images(self, page: Page, image_paths: list[str]):
        """上传图片到 MultiPost 编辑器

        交互流程：
          1. 点击编辑器下方的「上传图片」卡片按钮
          2. 按钮点击后会激活隐藏的 <input type="file" accept="image/*">
          3. 通过该 input 上传本地图片文件
        """
        logger.info(f"上传图片: {len(image_paths)} 张")

        # 先点击「上传图片」按钮，激活 file input
        logger.info("  点击「上传图片」按钮...")
        clicked = page.evaluate('''() => {
            // 找包含「上传图片」文字的卡片/按钮
            const all = document.querySelectorAll('div, button, span');
            for (const el of all) {
                const text = (el.textContent || '').trim();
                // 精确匹配「上传图片」文字的卡片
                if (text === '上传图片' || text.startsWith('上传图片')) {
                    el.click();
                    return true;
                }
            }
            return false;
        }''')

        if not clicked:
            logger.warning("  ⚠️ 未找到「上传图片」按钮")
        else:
            logger.info("  ✓ 已点击「上传图片」按钮")

        time.sleep(1)

        # 通过激活的 file input 上传图片
        image_input = page.locator('input[type="file"][accept*="image"]')

        if image_input.count() > 0:
            # 一次性上传所有图片（input 支持 multiple）
            image_input.set_input_files(image_paths)
            logger.info(f"  ✓ 已上传 {len(image_paths)} 张图片")
            time.sleep(3)  # 等待上传完成
        else:
            logger.warning("  ⚠️ 未找到图片 file input，尝试逐张上传...")
            for i, img_path in enumerate(image_paths, 1):
                # 再次点击上传按钮
                page.evaluate('''() => {
                    const all = document.querySelectorAll('div, button, span');
                    for (const el of all) {
                        if ((el.textContent || '').trim().startsWith('上传图片')) {
                            el.click();
                            return true;
                        }
                    }
                    return false;
                }''')
                time.sleep(1)

                image_input = page.locator('input[type="file"][accept*="image"]')
                if image_input.count() > 0:
                    image_input.set_input_files(img_path)
                    logger.info(f"    ✓ 图片 {i}/{len(image_paths)} 上传成功")
                    time.sleep(2)
                else:
                    logger.warning(f"    ⚠️ 图片 {i} 上传失败：未找到 file input")

        logger.success(f"✓ 图片上传完成")

    def _select_single_platform(self, page: Page, platform_name: str) -> bool:
        """
        选择单个平台

        策略：
          1. 先在热门列表里找
          2. 找不到就点「其他」展开，再找
          3. 找到后勾选 checkbox
        """
        result = page.evaluate('''(platformName) => {
            // 找到包含目标平台名的行
            const rows = document.querySelectorAll('div.flex.items-center.rounded-lg.p-2');
            for (const row of rows) {
                const text = (row.textContent || '').trim();
                if (text.includes(platformName) && text.length < 30) {
                    const checkbox = row.querySelector('input[type="checkbox"]');
                    if (checkbox && !checkbox.checked) {
                        checkbox.click();
                        return { found: true, clicked: true };
                    } else if (checkbox && checkbox.checked) {
                        return { found: true, clicked: false, reason: 'already checked' };
                    }
                }
            }
            return { found: false };
        }''', platform_name)

        if result.get('found'):
            return True

        # 热门列表里没找到，尝试展开「其他」
        logger.info(f"  {platform_name} 不在热门列表，尝试展开「其他」...")
        page.evaluate('''() => {
            const all = document.querySelectorAll('button, span, a, div');
            for (const el of all) {
                if (el.textContent.trim() === '其他') {
                    el.click();
                    return true;
                }
            }
            return false;
        }''')
        time.sleep(2)

        # 再试一次
        result = page.evaluate('''(platformName) => {
            const rows = document.querySelectorAll('div.flex.items-center.rounded-lg.p-2');
            for (const row of rows) {
                const text = (row.textContent || '').trim();
                if (text.includes(platformName) && text.length < 30) {
                    const checkbox = row.querySelector('input[type="checkbox"]');
                    if (checkbox && !checkbox.checked) {
                        checkbox.click();
                        return { found: true, clicked: true };
                    } else if (checkbox && checkbox.checked) {
                        return { found: true, clicked: false, reason: 'already checked' };
                    }
                }
            }
            return { found: false };
        }''', platform_name)

        return result.get('found', False)

    def _click_publish(self, page: Page, title: str, body: str, platforms: list[str] = None) -> bool:
        """
        第6步：点击 MultiPost 发布按钮，等待各平台标签页打开，按优先级处理

        流程：
          1. 点击发布按钮
          2. 等待10秒让 MultiPost 弹出各平台编辑器标签页
          3. 重连 Playwright（因为扩展打开的新标签页不会出现在旧连接中）
          4. 扫描所有标签页，匹配平台编辑器页面
          5. 按优先级处理：脉脉 → 公众号 → 头条
        """
        logger.info("⚠️  即将点击发布按钮，这是真实发布操作！")

        # 将中文平台名映射为内部标识
        platform_map = {
            '脉脉': 'maimai',
            '微信公众号': 'wechat',
            '微信': 'wechat',
            '公众号': 'wechat',
            '今日头条': 'toutiao',
            '头条': 'toutiao',
        }
        expected = []
        if platforms:
            for p in platforms:
                key = platform_map.get(p, p)
                if key not in expected:
                    expected.append(key)

        if not expected:
            expected = ['maimai', 'wechat', 'toutiao']

        # 点击蓝色发布按钮
        clicked = page.evaluate('''() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                const style = getComputedStyle(btn);
                if (style.backgroundColor.includes('0, 111, 238')) {
                    const rect = btn.getBoundingClientRect();
                    if (rect.width > 100) {
                        btn.click();
                        return true;
                    }
                }
            }
            return false;
        }''')

        if not clicked:
            raise RuntimeError("未找到发布按钮")

        logger.info("  ✓ MultiPost 发布按钮已点击，等待20秒让所有平台标签页打开...")
        time.sleep(20)

        # 重连 Playwright 以获取扩展打开的新标签页
        self._reconnect()

        # 扫描所有标签页，匹配平台编辑器页面
        platform_tabs = self._scan_all_platform_tabs(expected)

        if not platform_tabs:
            # 没有找到任何平台标签页，可能 MultiPost 已自动处理完毕
            logger.warning("⚠️  未检测到平台标签页，MultiPost 可能已自动处理")
            return True

        # 按优先级处理平台标签页：脉脉 → 公众号 → 头条
        # 先切回 MultiPost 页面，减少平台操作时弹窗到前台的干扰
        self._focus_multipost_page()

        results = {}
        for platform in self.PLATFORM_PRIORITY:
            if platform not in platform_tabs:
                # 该平台标签页未找到，可能已被 MultiPost 自动处理
                platform_names = {'maimai': '脉脉', 'wechat': '公众号', 'toutiao': '头条'}
                logger.warning(
                    f"  ⚠️ [{platform_names.get(platform, platform)}] 标签页未找到，"
                    f"可能已被 MultiPost 自动处理或尚未打开"
                )
                continue

            tab = platform_tabs[platform]
            logger.info(f"  处理平台: {platform}（优先级）")

            try:
                if platform == 'maimai':
                    results['maimai'] = self._publish_maimai(tab, title, body)
                elif platform == 'toutiao':
                    results['toutiao'] = self._publish_toutiao(tab, title, body)
                elif platform == 'wechat':
                    results['wechat'] = self._publish_wechat(tab, title, body)
                else:
                    logger.warning(f"  未知平台，跳过: {tab.url}")
            except Exception as e:
                logger.error(f"  ❌ {platform} 发布异常: {e}")
                results[platform] = False

        # 汇总结果
        for platform, success in results.items():
            status = "✅ 成功" if success else "❌ 失败"
            logger.info(f"  {platform}: {status}")

        # 清理已处理的平台标签页，为下一组发布做准备
        self._cleanup_platform_tabs(platform_tabs)

        # 找到的平台都成功就算成功（未找到的跳过）
        if not results:
            logger.warning("  ⚠️ 未找到任何平台标签页进行操作")
            return True  # MultiPost 可能已经处理了

        all_success = all(results.values())
        if all_success:
            logger.success("🎉 所有已找到的平台发布成功！")
        return all_success

    def _cleanup_platform_tabs(self, platform_tabs: dict):
        """关闭已处理的平台标签页，为下一组发布做准备"""
        if not platform_tabs:
            return
        logger.info("清理平台标签页...")
        for platform_name, pg in platform_tabs.items():
            try:
                if not pg.is_closed():
                    pg.close()
                    logger.info(f"  ✓ 已关闭 [{platform_name}] 标签页")
            except Exception:
                pass

    def _focus_multipost_page(self):
        """切回 MultiPost 页面，减少平台操作时弹窗到前台的干扰"""
        if not self._context:
            return
        for pg in self._context.pages:
            if 'multipost.app' in pg.url and not pg.is_closed():
                try:
                    pg.bring_to_front()
                except Exception:
                    pass
                break

    # ========== 平台标签页检测与交互 ==========

    # 平台编辑器 URL 特征（MultiPost 弹出的编辑器页面包含这些关键词）
    PLATFORM_EDITOR_RULES = {
        'maimai':   ['maimai.cn/community/home'],           # 脉脉社区首页自带发帖框
        'wechat':   ['appmsg_edit', 'appmsg_edit_v2'],      # 公众号图文编辑器
        'toutiao':  ['weitoutiao/publish', 'graphic/publish'],  # 头条微头条/图文发布页
    }

    # 平台处理优先级：脉脉 → 公众号 → 头条（头条放最后因为上传图片耗时更长）
    PLATFORM_PRIORITY = ['maimai', 'wechat', 'toutiao']

    def _scan_all_platform_tabs(self, expected_platforms: list[str]) -> dict:
        """
        扫描当前所有浏览器标签页，匹配平台编辑器页面

        前提：调用前已重连 Playwright，context.pages 包含最新标签页列表

        参数:
            expected_platforms: 期望的平台列表，如 ['maimai', 'wechat', 'toutiao']

        返回:
            dict: { platform_name: Page } 匹配到的平台标签页
        """
        logger.info(f"扫描平台编辑器标签页: {expected_platforms}...")
        found: dict[str, Page] = {}

        all_pages = self._context.pages
        logger.info(f"  当前共 {len(all_pages)} 个标签页")

        for pg in all_pages:
            if pg.is_closed():
                continue
            url = pg.url
            for platform_name in expected_platforms:
                if platform_name in found:
                    continue
                editor_rules = self.PLATFORM_EDITOR_RULES.get(platform_name, [])
                if any(rule in url for rule in editor_rules):
                    found[platform_name] = pg
                    logger.info(f"  ✓ [{platform_name}] 编辑器已就绪: {url[:100]}")

        if not found:
            # 打印所有标签页帮助调试
            logger.warning("  ⚠️ 未找到任何平台编辑器页面，当前标签页:")
            for pg in all_pages:
                if not pg.is_closed():
                    logger.warning(f"    {pg.url[:120]}")
        else:
            missing = [p for p in expected_platforms if p not in found]
            if missing:
                logger.warning(f"  未找到: {missing}")
            else:
                logger.success(f"  ✓ 所有 {len(expected_platforms)} 个平台编辑器已就绪")

        return found

    def _identify_platform(self, page: Page) -> str:
        """
        根据 URL 识别平台

        返回:
            'maimai' / 'toutiao' / 'wechat' / 'unknown'
        """
        url = page.url
        logger.debug(f"  标签页 URL: {url}")

        for platform_name, rules in self.PLATFORM_URL_RULES.items():
            if any(rule in url for rule in rules):
                return platform_name

        # 等待页面跳转完成后再次检查
        time.sleep(3)
        url = page.url
        logger.debug(f"  标签页 URL (等待后): {url}")

        for platform_name, rules in self.PLATFORM_URL_RULES.items():
            if any(rule in url for rule in rules):
                return platform_name

        # 未知平台，保存截图用于调试
        self._save_screenshot(page, "unknown_platform_tab")
        logger.warning(f"  未知平台: {url}")
        return 'unknown'

    def _publish_maimai(self, page: Page, title: str, content: str) -> bool:
        """
        在脉脉社区发布页面填写内容并发布

        脉脉的特殊之处：MultiPost 复用已有标签页（不打开新标签页），
        所以这个页面可能是用户之前打开的脉脉页面。

        操作流程：
          1. 确保编辑器存在（导航到社区首页）
          2. 切换身份为"职场领域创作者"
          3. 填入标题和正文
          4. 添加话题（带重试）
          5. 勾选两个发布设置开关（同步主页 + 昵称水印）
          6. 点击「发动态」
        """
        logger.info("📝 脉脉：填写内容并发布")

        # 确保在脉脉发帖页面
        if "maimai.cn" not in page.url:
            logger.warning("  当前页面不是脉脉，尝试导航...")
            page.goto(MAIMAI_HOME_URL, wait_until="domcontentloaded", timeout=15000)
            time.sleep(3)

        # 等待页面加载
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            logger.warning("  脉脉页面加载超时")
        time.sleep(2)

        self._save_screenshot(page, "maimai_before_fill")

        # 1. 切换身份
        self._switch_maimai_identity(page)

        # 2. 填标题（脉脉标题为选填，最多20字）
        if title:
            self._fill_maimai_title(page, title[:20])

        # 3. 填正文
        content_ok = self._fill_maimai_content(page, content)
        if not content_ok:
            logger.error("  ❌ 脉脉：正文填写失败")
            self._save_screenshot(page, "maimai_content_fail")
            return False

        time.sleep(0.5)

        # 4. 添加话题（带重试）
        self._add_maimai_topic(page, DEFAULT_TOPIC, retries=2)

        # 5. 勾选两个发布设置开关
        self._check_maimai_publish_settings(page)

        self._save_screenshot(page, "maimai_before_publish")

        # 6. 点击「发动态」
        publish_clicked = page.evaluate('''() => {
            // 优先 button
            const buttons = document.querySelectorAll('button');
            for (const btn of buttons) {
                const t = (btn.textContent || '').trim();
                const rect = btn.getBoundingClientRect();
                if ((t === '发动态' || t === '发布') && rect.width > 0 && !btn.disabled) {
                    btn.click();
                    return { tag: 'button', text: t };
                }
            }
            // 备用
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

        if not publish_clicked:
            logger.warning("  ⚠️ 脉脉：未找到「发动态」按钮")
            self._save_screenshot(page, "maimai_publish_btn_fail")
            return False

        logger.info(f"  ✓ 脉脉「发动态」已点击: {publish_clicked}")
        time.sleep(3)

        self._save_screenshot(page, "maimai_after_publish")
        logger.success("✓ 脉脉发布完成")
        return True

    # ========== 脉脉辅助方法 ==========

    def _switch_maimai_identity(self, page: Page):
        """确保脉脉身份为'职场领域创作者'"""
        logger.info("  检查脉脉发帖身份...")

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
            logger.info("    ✓ 身份已是职场领域创作者")
            return

        logger.info("    切换身份为职场领域创作者...")

        # 点击"切换"
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
            logger.warning("    ⚠️ 未找到切换按钮")
            return

        time.sleep(2)

        # 选择"职场领域创作者"
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
            logger.success("    ✓ 已切换为职场领域创作者")
        else:
            logger.warning("    ⚠️ 未找到职场领域创作者选项")
        time.sleep(1)

    def _fill_maimai_title(self, page: Page, title: str):
        """填入脉脉标题"""
        logger.info(f"  填入标题: {title[:20]}...")

        # 策略1：Playwright locator
        title_input = page.locator('input[placeholder*="标题"]')
        if title_input.count() > 0:
            title_input.first.click()
            title_input.first.fill("")
            title_input.first.fill(title)
            logger.success(f"    ✓ 标题已填入: {title}")
            time.sleep(0.5)
            return

        # 策略2：JS evaluate
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
            logger.success(f"    ✓ 标题已填入: {title}")
        else:
            logger.warning("    ⚠️ 未找到标题输入框（标题为选填，继续）")
        time.sleep(0.5)

    def _fill_maimai_content(self, page: Page, content: str) -> bool:
        """填入脉脉正文"""
        logger.info(f"  填入正文: {len(content)} 字")
        content = content[:1000]

        SELECT_ALL_KEY = "Meta+A" if platform.system() == "Darwin" else "Control+A"

        # 策略1：textarea
        textarea = page.locator('textarea[placeholder*="想法"], textarea[placeholder*="分享"]')
        if textarea.count() > 0:
            textarea.first.click()
            page.keyboard.press(SELECT_ALL_KEY)
            page.keyboard.press("Backspace")
            time.sleep(0.2)
            textarea.first.fill(content)
            logger.success(f"    ✓ 正文已填入 (textarea)")
            time.sleep(0.5)
            return True

        # 策略2：contenteditable
        editor = page.locator('[contenteditable="true"]')
        if editor.count() > 0:
            editor.first.click()
            page.keyboard.press(SELECT_ALL_KEY)
            page.keyboard.press("Backspace")
            time.sleep(0.2)
            page.keyboard.type(content, delay=10)
            logger.success(f"    ✓ 正文已填入 (contenteditable)")
            time.sleep(0.5)
            return True

        return False

    def _add_maimai_topic(self, page: Page, topic: str, retries: int = 2):
        """添加脉脉话题（带重试）"""
        for attempt in range(retries + 1):
            logger.info(f"  添加话题: {topic}" + (f"（第 {attempt+1} 次尝试）" if attempt > 0 else ""))

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
                        if (area < bestArea) { bestArea = area; best = el; }
                    }
                }
                if (best) { best.click(); return best.textContent.trim(); }
                for (const el of all) {
                    const t = (el.textContent || '').trim();
                    const rect = el.getBoundingClientRect();
                    if ((t === '添加话题' || t === '# 添加话题') && rect.y > 250 && rect.width < 150) {
                        el.click(); return t;
                    }
                }
                return false;
            }''')

            if not clicked:
                logger.warning("    ⚠️ 未找到「添加话题」按钮")
                if attempt < retries:
                    time.sleep(2)
                    continue
                return

            time.sleep(2)

            # 2. 在弹出面板的搜索框中输入话题
            popup_search = None
            for inp in page.locator('input[type="search"], input[type="text"]').all():
                try:
                    box = inp.bounding_box()
                    if box and box['y'] > 250 and box['width'] > 50:
                        popup_search = inp
                        break
                except Exception:
                    continue

            if popup_search:
                popup_search.click()
                time.sleep(0.3)
                popup_search.fill(topic)
                logger.info(f"    已在搜索框输入: {topic}")
            else:
                logger.warning("    ⚠️ 未找到搜索框")
                if attempt < retries:
                    page.keyboard.press("Escape")
                    time.sleep(2)
                    continue
                return

            time.sleep(2)

            # 3. 点击搜索结果
            selected = page.evaluate('''(topic) => {
                const all = document.querySelectorAll('div');
                let exactRow = null, exactLen = Infinity;
                let prefixRow = null, prefixLen = Infinity;
                for (const el of all) {
                    const t = (el.textContent || '').trim();
                    const rect = el.getBoundingClientRect();
                    const cls = (el.className || '').toString();
                    if (!cls.includes('cursor-pointer') || rect.y < 300 || rect.height < 30 || rect.height > 60) continue;
                    if (!t.includes(topic)) continue;
                    if (t.startsWith(topic)) {
                        if (t.length < exactLen) { exactLen = t.length; exactRow = el; }
                    } else {
                        if (t.length < prefixLen) { prefixLen = t.length; prefixRow = el; }
                    }
                }
                const target = exactRow || prefixRow;
                if (target) {
                    target.click();
                    return { match: exactRow ? 'exact' : 'prefix', text: target.textContent.trim().substring(0, 30) };
                }
                return null;
            }''', topic)

            if selected:
                logger.success(f"    ✓ 话题已点击: {selected.get('text', topic)}")
            else:
                logger.warning(f"    ⚠️ 未找到话题搜索结果: {topic}")
                if attempt < retries:
                    page.keyboard.press("Escape")
                    time.sleep(2)
                    continue

            # 关闭弹窗
            time.sleep(1)
            page.keyboard.press("Escape")
            time.sleep(0.5)
            return

    def _check_maimai_publish_settings(self, page: Page):
        """勾选脉脉的两个发布设置开关：同步主页 + 昵称水印"""
        logger.info("  检查发布设置开关...")

        checked = page.evaluate('''() => {
            let toggled = 0;
            // 查找开关：通常是 checkbox 或 toggle 样式的元素
            // 脉脉的开关是自定义组件，需要通过文字找到对应的开关
            const labels = ['同步主页', '昵称水印'];
            for (const label of labels) {
                const all = document.querySelectorAll('span, div, label');
                for (const el of all) {
                    const t = (el.textContent || '').trim();
                    const rect = el.getBoundingClientRect();
                    // 找到标签文字附近的开关/checkbox
                    if (t.includes(label) && rect.y > 300) {
                        // 查找同级的 checkbox 或 toggle
                        const parent = el.closest('div[class]') || el.parentElement;
                        if (parent) {
                            const checkbox = parent.querySelector('input[type="checkbox"]');
                            if (checkbox && !checkbox.checked) {
                                checkbox.click();
                                toggled++;
                                continue;
                            }
                            // 自定义 toggle：查找圆点指示器
                            const toggle = parent.querySelector('[class*="toggle"], [class*="switch"], [role="switch"]');
                            if (toggle) {
                                const isOff = toggle.getAttribute('aria-checked') === 'false'
                                    || !toggle.classList.contains('active')
                                    || toggle.classList.contains('off');
                                if (isOff) {
                                    toggle.click();
                                    toggled++;
                                }
                            }
                        }
                    }
                }
            }
            return toggled;
        }''')

        if checked > 0:
            logger.info(f"    ✓ 已勾选 {checked} 个开关")
        else:
            logger.info("    开关已是正确状态或未找到")
        time.sleep(0.5)

    def _publish_toutiao(self, page: Page, title: str, content: str) -> bool:
        """
        在今日头条发布页面：追加话题标签 + 点击发布

        MultiPost 已经填好了标题和正文，我们只需要：
          1. 在正文末尾追加 `#上头条 聊热点#` 话题标签
          2. 点击红色「发布」按钮
        """
        logger.info("📝 今日头条：追加话题标签并发布")

        # 等待页面加载
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            logger.warning("  今日头条页面加载超时")
        time.sleep(2)

        self._save_screenshot(page, "toutiao_before_action")

        # 在已有正文末尾追加话题标签
        appended = page.evaluate("""() => {
            // 找到 contenteditable 编辑器
            const editors = document.querySelectorAll(
                'div[contenteditable="true"], [role="textbox"], textarea'
            );
            for (const editor of editors) {
                const rect = editor.getBoundingClientRect();
                if (rect.width > 200 && rect.height > 100) {
                    editor.focus();
                    // 将光标移到末尾
                    const range = document.createRange();
                    const sel = window.getSelection();
                    range.selectNodeContents(editor);
                    range.collapse(false);
                    sel.removeAllRanges();
                    sel.addRange(range);
                    // 追加话题标签
                    document.execCommand('insertText', false, '\\n\\n#上头条 聊热点#');
                    return true;
                }
            }
            return false;
        }""")

        if appended:
            logger.info("  ✓ 已追加话题标签 #上头条 聊热点#")
        else:
            logger.warning("  ⚠️ 未找到编辑器追加话题标签，尝试键盘输入...")
            # 备用方案：点击编辑器后用键盘输入
            editor = page.locator('div[contenteditable="true"], [role="textbox"]').first
            if editor.count() > 0:
                editor.click()
                page.keyboard.press("End")
                page.keyboard.type("\n\n#上头条 聊热点#", delay=10)
                logger.info("  ✓ 已追加话题标签 (键盘输入)")
            else:
                logger.warning("  ⚠️ 未找到编辑器，跳过话题标签追加")

        time.sleep(1)
        self._save_screenshot(page, "toutiao_before_publish")

        # 点击红色「发布」按钮
        publish_clicked = page.evaluate("""() => {
            const btns = document.querySelectorAll('button');
            for (const btn of btns) {
                const text = (btn.textContent || '').trim();
                const style = getComputedStyle(btn);
                const rect = btn.getBoundingClientRect();
                if ((text === '发布' || text === '发表') && rect.width > 0 && rect.height > 0) {
                    btn.click();
                    return text;
                }
            }
            // 备用：找红色按钮
            for (const btn of btns) {
                const style = getComputedStyle(btn);
                const rect = btn.getBoundingClientRect();
                if (style.backgroundColor.includes('255') && rect.width > 40 && rect.width < 200) {
                    const t = (btn.textContent || '').trim();
                    if (t.includes('发布') || t.includes('发表') || t === '') {
                        btn.click();
                        return t || '红色按钮';
                    }
                }
            }
            return false;
        }""")

        if not publish_clicked:
            logger.warning("  ⚠️ 今日头条：未找到发布按钮")
            self._save_screenshot(page, "toutiao_publish_btn_fail")
            return False

        logger.info(f"  ✓ 今日头条发布按钮已点击: {publish_clicked}")
        time.sleep(3)

        self._save_screenshot(page, "toutiao_after_publish")
        logger.success("✓ 今日头条发布完成")
        return True

    def _publish_wechat(self, page: Page, title: str, content: str) -> bool:
        """
        在微信公众号编辑页面：点击「保存为草稿」

        MultiPost 已经填好了标题和正文，我们只需要：
          点击「保存为草稿」（⚠️ 不点「群发」或「发表」）
        """
        logger.info("📝 微信公众号：保存为草稿")

        # 等待页面加载
        try:
            page.wait_for_load_state("domcontentloaded", timeout=10000)
        except Exception:
            logger.warning("  微信公众号页面加载超时")
        time.sleep(2)

        self._save_screenshot(page, "wechat_before_action")

        # ⚠️ 只点击「保存为草稿」，绝对不点「群发」或「发表」！
        publish_clicked = page.evaluate("""() => {
            const btns = document.querySelectorAll('button, a, span');
            for (const btn of btns) {
                const text = (btn.textContent || '').trim();
                if (text === '保存为草稿' || text === '存为草稿' || text === '保存草稿') {
                    btn.click();
                    return text;
                }
            }
            return false;
        }""")

        if not publish_clicked:
            logger.warning("  ⚠️ 微信公众号：未找到「保存为草稿」按钮")
            self._save_screenshot(page, "wechat_save_draft_btn_fail")
            return False

        logger.info(f"  ✓ 微信公众号「保存为草稿」已点击: {publish_clicked}")
        time.sleep(2)

        # 处理确认弹窗
        confirm_clicked = page.evaluate("""() => {
            const btns = document.querySelectorAll('button, a, span');
            for (const btn of btns) {
                const text = (btn.textContent || '').trim();
                if (text === '确定' || text === '确认' || text === '确认保存') {
                    btn.click();
                    return text;
                }
            }
            return false;
        }""")

        if confirm_clicked:
            logger.info(f"  ✓ 确认弹窗已点击: {confirm_clicked}")
            time.sleep(2)

        self._save_screenshot(page, "wechat_after_save_draft")
        logger.success("✓ 微信公众号已保存为草稿")
        return True

    # ========== 平台通用填写方法 ==========

    def _fill_platform_title(self, page: Page, title: str, platform: str) -> bool:
        """在平台发布页面填写标题"""
        # 策略1：通过 placeholder 定位标题输入框
        title_input = page.locator('input[placeholder*="标题"], input[placeholder*="请输入"]')
        if title_input.count() > 0:
            title_input.first.click()
            title_input.first.fill(title)
            logger.info(f"  标题已填写: {title[:30]}...")
            return True

        # 策略2：通过 id 或常见选择器
        title_input = page.locator('#title, input[name="title"], input[type="text"]')
        if title_input.count() > 0:
            title_input.first.click()
            title_input.first.fill(title)
            logger.info(f"  标题已填写: {title[:30]}...")
            return True

        # 策略3：JS evaluate 兜底
        filled = page.evaluate('''(title) => {
            const inputs = document.querySelectorAll('input[type="text"]');
            for (const input of inputs) {
                const ph = (input.placeholder || '') + (input.getAttribute('aria-label') || '');
                if (ph.includes('标题') || ph.includes('请输入') || ph === '') {
                    input.focus();
                    input.value = title;
                    input.dispatchEvent(new Event('input', { bubbles: true }));
                    input.dispatchEvent(new Event('change', { bubbles: true }));
                    return true;
                }
            }
            return false;
        }''', title)

        if filled:
            logger.info(f"  标题已填写 (JS): {title[:30]}...")
        return filled

    def _fill_platform_content(self, page: Page, content: str, platform: str) -> bool:
        """在平台发布页面填写正文（通用方法，非微信）"""
        # 策略1：contenteditable div（今日头条常用）
        content_editor = page.locator('div[contenteditable="true"]')
        if content_editor.count() > 0:
            content_editor.first.click()
            page.keyboard.type(content, delay=5)
            logger.info(f"  正文已填写 (contenteditable): {len(content)} 字")
            return True

        # 策略2：textarea
        textarea = page.locator('textarea[placeholder*="正文"], textarea[placeholder*="内容"], textarea')
        if textarea.count() > 0:
            textarea.first.click()
            textarea.first.fill(content)
            logger.info(f"  正文已填写 (textarea): {len(content)} 字")
            return True

        # 策略3：role="textbox"
        textbox = page.locator('[role="textbox"]')
        if textbox.count() > 0:
            textbox.first.click()
            page.keyboard.type(content, delay=5)
            logger.info(f"  正文已填写 (textbox): {len(content)} 字")
            return True

        # 策略4：JS evaluate 兜底
        filled = page.evaluate('''(content) => {
            const editors = document.querySelectorAll(
                'div[contenteditable="true"], textarea, [role="textbox"]'
            );
            for (const editor of editors) {
                if (editor.tagName === 'TEXTAREA') {
                    editor.value = content;
                } else {
                    editor.innerHTML = content;
                }
                editor.dispatchEvent(new Event('input', { bubbles: true }));
                return true;
            }
            return false;
        }''', content)

        if filled:
            logger.info(f"  正文已填写 (JS): {len(content)} 字")
        return filled

    def _fill_wechat_content(self, page: Page, content: str) -> bool:
        """在微信公众号发布页面填写正文（处理 iframe 编辑器）"""
        # 策略1：iframe 编辑器（微信公众号常用）
        editor_frame = page.locator('iframe[id*="edui"], iframe[class*="editor"], iframe[src*="editor"]')
        if editor_frame.count() > 0:
            try:
                frame = editor_frame.first.content_frame()
                body = frame.locator('body[contenteditable="true"]')
                if body.count() > 0:
                    body.click()
                    page.keyboard.type(content, delay=5)
                    logger.info(f"  正文已填写 (iframe编辑器): {len(content)} 字")
                    return True
            except Exception as e:
                logger.warning(f"  iframe 编辑器填写失败: {e}")

        # 策略2：直接 contenteditable
        content_editor = page.locator('div[contenteditable="true"], [role="textbox"]')
        if content_editor.count() > 0:
            content_editor.first.click()
            page.keyboard.type(content, delay=5)
            logger.info(f"  正文已填写 (contenteditable): {len(content)} 字")
            return True

        # 策略3：JS evaluate 尝试访问 iframe
        filled = page.evaluate('''(content) => {
            // 尝试 iframe
            const iframes = document.querySelectorAll('iframe');
            for (const iframe of iframes) {
                try {
                    const body = iframe.contentDocument && iframe.contentDocument.body;
                    if (body && body.contentEditable === 'true') {
                        body.innerHTML = content;
                        return true;
                    }
                } catch (e) { /* 跨域 iframe */ }
            }
            // 尝试 contenteditable
            const editors = document.querySelectorAll('div[contenteditable="true"], [role="textbox"]');
            for (const editor of editors) {
                editor.focus();
                editor.innerHTML = content;
                editor.dispatchEvent(new Event('input', { bubbles: true }));
                return true;
            }
            return false;
        }''', content)

        if filled:
            logger.info(f"  正文已填写 (JS): {len(content)} 字")
        return filled

    # ========== 截图工具 ==========

    def _save_screenshot(self, page: Page, name: str):
        """保存调试截图"""
        try:
            debug_dir = PROJECT_ROOT / "debug_screenshots"
            debug_dir.mkdir(exist_ok=True)
            page.screenshot(path=str(debug_dir / f"{name}.png"), full_page=True)
            logger.debug(f"  截图已保存: {name}.png")
        except Exception:
            pass
