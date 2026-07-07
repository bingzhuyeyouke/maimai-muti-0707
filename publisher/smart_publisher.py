"""
智能多平台发布器 —— 统一调度 MaimaiPoster + MultiPostPublisher + Wechatsync

核心设计（直接发布优先）：
  - 脉脉 → MaimaiPoster（Playwright + CDP，直接发布，不带图）
  - 公众号/头条 → MultiPostPublisher（Playwright + CDP，直接发布，带图）
  - 知乎/掘金等 → WechatsyncPublisher（MCP/CLI，草稿模式）
  - MultiPostPublisher 不可用时 → WechatsyncPublisher 降级（草稿模式）

日常用法（通过 Claude MCP）：
  1. 用户提供文章内容
  2. Claude 调用 MaimaiPoster 发布到脉脉（不带图）
  3. Claude 调用 MultiPostPublisher 发布到头条+公众号（带图）
  4. Claude 调用 Wechatsync MCP 发布到知乎/掘金等（草稿模式）

脚本用法（Python）：
  from publisher.smart_publisher import SmartPublisher
  publisher = SmartPublisher()
  result = publisher.publish_to_all(title, body, platforms=["weixin", "toutiao", "maimai"])
"""

from typing import List, Optional

from loguru import logger

from config import settings


class SmartPublisher:
    """
    智能多平台发布器

    用法：
        publisher = SmartPublisher()
        result = publisher.publish_to_all(
            title="标题",
            body="正文",
            platforms=["weixin", "toutiao", "zhihu", "maimai"],
            image_paths=["img1.jpg"],
        )
    """

    # 平台分类
    MAIMAI_PLATFORMS = {"maimai"}
    # 头条和公众号 → MultiPostPublisher 直接发布（首选）
    DIRECT_PUBLISH_PLATFORMS = {"weixin", "toutiao"}
    # 其他平台 → Wechatsync 草稿模式
    WECHATSYNC_PLATFORMS = {
        "zhihu", "juejin", "csdn",
        "weibo", "bilibili", "baijiahao", "douyin",
        "xiaohongshu", "sohu", "xueqiu", "jianshu",
        "oschina", "segmentfault", "cnblogs", "douban",
        "yuque", "cto51", "eastmoney",
    }

    def __init__(self):
        self._maimai_poster = None
        self._wechatsync_publisher = None
        self._multipost_publisher = None

    def publish_to_all(
        self,
        title: str,
        body: str,
        platforms: List[str] = None,
        image_paths: List[str] = None,
        maimai_topic: str = "我来爆个料",
        maimai_title: str = "",
        maimai_content: str = "",
        dry_run: bool = False,
    ) -> dict:
        """
        发布到所有指定平台

        参数:
            title:         文章标题（公众号/头条/知乎等使用）
            body:          文章正文（Markdown 或纯文本）
            platforms:     目标平台 ID 列表，默认从配置读取
            image_paths:   本地图片路径列表
            maimai_topic:  脉脉话题（仅 maimai 平台使用）
            maimai_title:  脉脉标题（可选，与 title 不同时使用）
            maimai_content:脉脉正文（可选，与 body 不同时使用，合规改写后的版本）
            dry_run:       干跑模式

        返回:
            {
                "success_count": int,
                "fail_count": int,
                "results": {
                    "maimai": {"success": bool, ...},
                    "multipost": {"success": bool, ...},
                    "wechatsync": {"success": bool, ...},
                }
            }
        """
        if platforms is None:
            default = settings.wechatsync_default_platforms
            platforms = [p.strip() for p in default.split(",") if p.strip()]

        # 分组
        maimai_platforms = [p for p in platforms if p in self.MAIMAI_PLATFORMS]
        direct_platforms = [p for p in platforms if p in self.DIRECT_PUBLISH_PLATFORMS]
        wechatsync_platforms = [p for p in platforms if p in self.WECHATSYNC_PLATFORMS]
        unknown_platforms = [p for p in platforms if p not in self.MAIMAI_PLATFORMS and p not in self.DIRECT_PUBLISH_PLATFORMS and p not in self.WECHATSYNC_PLATFORMS]

        if unknown_platforms:
            logger.warning(f"⚠️ 未知平台，已忽略: {unknown_platforms}")

        logger.info(f"📋 智能发布: 共 {len(platforms)} 个平台")
        logger.info(f"  脉脉（直接发）: {maimai_platforms or '无'}")
        logger.info(f"  头条/公众号（直接发）: {direct_platforms or '无'}")
        logger.info(f"  知乎/掘金等（草稿）: {wechatsync_platforms or '无'}")

        results = {}
        success_count = 0
        fail_count = 0

        # ===== 1. 发布到脉脉（不带图）=====
        if maimai_platforms:
            result = self._publish_maimai(
                title=maimai_title or title,
                content=maimai_content or body,
                image_paths=None,  # 脉脉不带图
                topic=maimai_topic,
                dry_run=dry_run,
            )
            results["maimai"] = result
            if result.get("success"):
                success_count += 1
            else:
                fail_count += 1

        # ===== 2. 发布到头条+公众号（直接发布，带图）=====
        if direct_platforms:
            result = self._publish_direct(
                title=title,
                body=body,
                platforms=direct_platforms,
                image_paths=image_paths,
                dry_run=dry_run,
            )
            results["multipost"] = result
            if result.get("success"):
                success_count += len(direct_platforms)
            else:
                fail_count += len(direct_platforms)

        # ===== 3. 发布到知乎/掘金等（草稿模式）=====
        if wechatsync_platforms:
            result = self._publish_wechatsync(
                title=title,
                body=body,
                platforms=wechatsync_platforms,
                image_paths=image_paths,
                dry_run=dry_run,
            )
            results["wechatsync"] = result
            if result.get("success"):
                success_count += len(wechatsync_platforms)
            else:
                fail_count += len(wechatsync_platforms)

        # ===== 汇总 =====
        summary = {
            "success_count": success_count,
            "fail_count": fail_count,
            "results": results,
        }

        if fail_count == 0:
            logger.success(f"🎉 所有平台发布成功！({success_count} 个平台)")
        else:
            logger.warning(f"⚠️ 部分平台发布失败: 成功 {success_count}, 失败 {fail_count}")

        # ===== 发布完成后清理本地图片（从 API 下载的，发完就没用） =====
        if image_paths and not dry_run:
            from publisher.multipost import MultiPostPublisher
            MultiPostPublisher._cleanup_downloaded_images(image_paths)

        return summary

    def _publish_maimai(
        self,
        title: str,
        content: str,
        image_paths: List[str] = None,
        topic: str = "我来爆个料",
        dry_run: bool = False,
    ) -> dict:
        """发布到脉脉（不带图）"""
        logger.info("📱 发布到脉脉（不带图）...")

        try:
            from publisher.maimai import MaimaiPoster

            poster = MaimaiPoster()
            self._maimai_poster = poster

            if not poster.connect():
                return {"success": False, "error": "Chrome 连接失败"}

            result = poster.post(
                content=content,
                title=title,
                image_paths=image_paths,
                topic=topic,
                dry_run=dry_run,
            )

            poster.disconnect()
            self._maimai_poster = None

            return {"success": result}

        except Exception as e:
            logger.error(f"❌ 脉脉发布失败: {e}")
            return {"success": False, "error": str(e)}

    def _publish_direct(
        self,
        title: str,
        body: str,
        platforms: List[str],
        image_paths: List[str] = None,
        dry_run: bool = False,
    ) -> dict:
        """直接发布到头条+公众号（MultiPostPublisher，带图）"""
        from publisher.wechatsync import PLATFORM_NAMES

        # 平台 ID → 中文名
        platform_names = [PLATFORM_NAMES.get(p, p) for p in platforms]
        logger.info(f"📤 直接发布到 {platform_names}（带图）")

        try:
            from publisher.multipost import MultiPostPublisher

            publisher = MultiPostPublisher()
            self._multipost_publisher = publisher

            if not publisher.connect():
                # 连接失败，降级到 Wechatsync（草稿模式）
                logger.warning("⚠️ MultiPost 连接失败，降级到 Wechatsync（草稿模式）")
                return self._publish_wechatsync(title, body, platforms, image_paths, dry_run)

            result = publisher.publish(
                title=title,
                body=body,
                platforms=platform_names,
                image_paths=image_paths,
                dry_run=dry_run,
            )

            publisher.disconnect()
            self._multipost_publisher = None

            return {"success": result, "direct_publish": True}

        except Exception as e:
            logger.error(f"❌ MultiPost 直接发布失败: {e}")
            # 降级到 Wechatsync
            logger.info("🔄 降级到 Wechatsync（草稿模式）")
            return self._publish_wechatsync(title, body, platforms, image_paths, dry_run)

    def _publish_wechatsync(
        self,
        title: str,
        body: str,
        platforms: List[str],
        image_paths: List[str] = None,
        dry_run: bool = False,
    ) -> dict:
        """发布到 Wechatsync 平台（草稿模式）"""
        logger.info(f"📤 发布到 Wechatsync 平台（草稿模式）: {platforms}")

        try:
            from publisher.wechatsync import WechatsyncPublisher

            publisher = WechatsyncPublisher()
            self._wechatsync_publisher = publisher

            if publisher.connect():
                result = publisher.publish(
                    title=title,
                    body=body,
                    platforms=platforms,
                    image_paths=image_paths,
                    dry_run=dry_run,
                )
                publisher.disconnect()
                self._wechatsync_publisher = None
                return result

        except Exception as e:
            logger.warning(f"⚠️ Wechatsync 发布失败: {e}")

        return {"success": False, "error": "Wechatsync 不可用"}

    def check_environment(self) -> dict:
        """
        检查发布环境是否就绪

        返回:
            {
                "maimai": {"available": bool, "message": str},
                "multipost": {"available": bool, "message": str},
                "wechatsync": {"available": bool, "message": str},
            }
        """
        env_status = {}

        # 检查脉脉 & MultiPost（都需要 Chrome CDP）
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                result = s.connect_ex(('localhost', 9222))
                cdp_ok = (result == 0)
            env_status["maimai"] = {
                "available": cdp_ok,
                "message": "Chrome CDP 可用" if cdp_ok else "Chrome CDP 未启动（端口 9222）",
            }
            env_status["multipost"] = {
                "available": cdp_ok,
                "message": "MultiPost 直接发布可用" if cdp_ok else "MultiPost 不可用（需要 Chrome CDP）",
            }
        except Exception as e:
            env_status["maimai"] = {"available": False, "message": str(e)}
            env_status["multipost"] = {"available": False, "message": str(e)}

        # 检查 Wechatsync
        try:
            from publisher.wechatsync import WechatsyncPublisher
            publisher = WechatsyncPublisher()
            available = publisher.connect()
            env_status["wechatsync"] = {
                "available": available,
                "message": "Wechatsync 已就绪" if available else "Wechatsync 未就绪",
            }
            publisher.disconnect()
        except Exception as e:
            env_status["wechatsync"] = {"available": False, "message": str(e)}

        return env_status
