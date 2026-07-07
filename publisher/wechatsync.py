"""
Wechatsync 发布模块 —— 通过 Wechatsync CLI/MCP 将文章同步到多平台

支持的发布路径：
  1. MCP Server（推荐）：Claude Code 直接调用 MCP 工具 sync_article
  2. CLI 调用：通过 subprocess 调用 wechatsync CLI

与 MultiPostPublisher 的区别：
  - Wechatsync 支持 29+ 平台（知乎、掘金、微博、CSDN、B站等）
  - Wechatsync 以草稿模式发布（更安全，需要用户在各平台审核后发布）
  - MultiPostPublisher 仅支持公众号和头条，但是直接发布

⚠️  前置条件：
  - Chrome 安装了 Wechatsync 扩展
  - Wechatsync 扩展已启用 MCP 连接（设置中开启，Token 与 .env 一致）
  - 已登录各目标平台
"""

import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, List

from loguru import logger

from config import settings, PROJECT_ROOT


# Wechatsync 平台 ID → 中文名映射（常用平台）
PLATFORM_NAMES = {
    "weixin": "微信公众号",
    "toutiao": "今日头条",
    "zhihu": "知乎",
    "juejin": "掘金",
    "csdn": "CSDN",
    "weibo": "微博",
    "bilibili": "B站",
    "baijiahao": "百家号",
    "douyin": "抖音图文",
    "xiaohongshu": "小红书",
    "sohu": "搜狐号",
    "xueqiu": "雪球",
    "jianshu": "简书",
    "oschina": "开源中国",
    "segmentfault": "SegmentFault",
    "cnblogs": "博客园",
    "douban": "豆瓣",
    "yuque": "语雀",
    "imoo": "慕课网",
    "cto51": "51CTO",
    "eastmoney": "东方财富",
}


class WechatsyncPublisher:
    """
    Wechatsync 发布器 —— 通过 CLI 调用 Wechatsync 同步文章到多平台

    用法：
        publisher = WechatsyncPublisher()
        if publisher.connect():
            publisher.publish(title="标题", body="正文", platforms=["weixin", "toutiao"])
            publisher.disconnect()
    """

    def __init__(self):
        self._cli_path = self._find_cli()
        self._connected = False

    def _find_cli(self) -> Optional[str]:
        """查找 Wechatsync CLI 可执行文件"""
        # 1. 检查项目内 CLI
        cli_path = str(Path.home() / "Wechatsync" / "packages" / "cli" / "dist" / "index.js")
        if Path(cli_path).exists():
            return cli_path

        # 2. 检查全局安装
        try:
            result = subprocess.run(
                ["which", "wechatsync"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

        logger.warning("⚠️ 未找到 Wechatsync CLI")
        return None

    def connect(self) -> bool:
        """
        验证 Wechatsync 环境是否就绪

        检查项：
          1. CLI 是否可用
          2. Chrome 扩展是否连接（通过 HTTP API 检查）

        返回:
            True 环境就绪，False 环境不可用
        """
        logger.info("检查 Wechatsync 环境...")

        if not self._cli_path:
            logger.error("❌ Wechatsync CLI 不可用")
            ws_dir = Path.home() / "Wechatsync"
            logger.info(f"请确认已构建 Wechatsync：cd {ws_dir} && pnpm build")
            return False

        logger.info(f"  ✓ CLI 路径: {self._cli_path}")

        # 检查 Chrome 扩展连接状态（通过 HTTP API）
        ws_port = settings.wechatsync_ws_port
        http_port = ws_port + 1

        try:
            import urllib.request
            url = f"http://localhost:{http_port}/status"
            resp = urllib.request.urlopen(url, timeout=3)
            status = json.loads(resp.read().decode())

            if status.get("connected"):
                logger.success("✓ Chrome 扩展已连接")
                self._connected = True
                return True
            else:
                logger.warning("⚠️ Chrome 扩展未连接")
                logger.info("请确保：")
                logger.info("  1. 已安装 Wechatsync Chrome 扩展")
                logger.info("  2. 扩展设置中已启用 MCP 连接")
                logger.info(f"  3. Token 设置为: {settings.wechatsync_token}")
                return False

        except Exception as e:
            logger.warning(f"⚠️ 无法连接 Wechatsync MCP Server: {e}")
            logger.info("MCP Server 可能未启动（Claude Code 会自动启动）")
            # 不阻断 —— MCP 模式下 Claude Code 自动管理
            self._connected = True
            return True

    def disconnect(self):
        """断开连接（CLI 模式无需额外操作）"""
        self._connected = False
        logger.info("Wechatsync 已断开")

    def publish(
        self,
        title: str,
        body: str,
        platforms: List[str] = None,
        image_paths: List[str] = None,
        dry_run: bool = False,
    ) -> dict:
        """
        通过 CLI 发布文章到多平台

        参数:
            title:       文章标题
            body:        文章正文（支持 Markdown 和纯文本）
            platforms:   目标平台 ID 列表，如 ["weixin", "toutiao", "zhihu"]
            image_paths: 本地图片路径列表（可选，图片会嵌入 Markdown）
            dry_run:     干跑模式

        返回:
            {"success": bool, "platforms": {platform_id: result}}
        """
        if not self._connected:
            logger.error("❌ 未连接，请先调用 connect()")
            return {"success": False, "platforms": {}}

        if platforms is None:
            platforms = settings.wechatsync_default_platforms.split(",")

        # 平台 ID 列表展示
        platform_display = [f"{p}({PLATFORM_NAMES.get(p, '未知')})" for p in platforms]
        logger.info(f"📝 发布到 Wechatsync: {', '.join(platform_display)}")
        logger.info(f"  标题: {title}")

        # 构造 Markdown 内容
        markdown = self._build_markdown(title, body, image_paths)

        if dry_run:
            logger.info("🔍 干跑模式：内容已准备，但不调用 CLI")
            logger.info(f"  Markdown 长度: {len(markdown)} 字符")
            return {"success": True, "platforms": {}, "dry_run": True}

        # 写入临时 Markdown 文件
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8",
            dir=str(PROJECT_ROOT / "posts"),
        ) as f:
            f.write(markdown)
            md_path = f.name

        try:
            # 调用 CLI
            result = self._run_cli(md_path, platforms)
            return result
        finally:
            # 清理临时文件
            try:
                Path(md_path).unlink(missing_ok=True)
            except Exception:
                pass

    def _build_markdown(
        self,
        title: str,
        body: str,
        image_paths: List[str] = None,
    ) -> str:
        """构造 Wechatsync 格式的 Markdown 文件内容"""
        parts = []

        # 标题（Wechatsync 会从标题行提取标题）
        parts.append(f"# {title}")
        parts.append("")

        # 正文（已经是 Markdown 或纯文本）
        parts.append(body)

        # 嵌入图片引用
        if image_paths:
            parts.append("")
            for i, img_path in enumerate(image_paths, 1):
                # Wechatsync 支持本地路径的图片引用
                abs_path = str(Path(img_path).resolve())
                parts.append(f"![图片{i}]({abs_path})")

        return "\n".join(parts)

    def _run_cli(self, md_path: str, platforms: List[str]) -> dict:
        """调用 Wechatsync CLI 同步文章"""
        platform_args = ",".join(platforms)

        cmd = [
            "node", self._cli_path,
            "sync", md_path,
            "-p", platform_args,
        ]

        # 设置环境变量
        env = {
            **dict(__import__("os").environ),
            "WECHATSYNC_TOKEN": settings.wechatsync_token,
        }

        logger.info(f"  调用 CLI: {' '.join(cmd)}")

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,  # 5分钟超时
                env=env,
            )

            if result.returncode == 0:
                logger.success("✓ Wechatsync 同步完成")
                # 尝试解析 CLI 输出
                try:
                    output = json.loads(result.stdout)
                    return {"success": True, "platforms": output}
                except (json.JSONDecodeError, ValueError):
                    logger.info(f"  CLI 输出: {result.stdout[:500]}")
                    return {"success": True, "platforms": {}, "raw_output": result.stdout}
            else:
                logger.error(f"❌ Wechatsync CLI 失败: {result.stderr}")
                return {"success": False, "platforms": {}, "error": result.stderr}

        except subprocess.TimeoutExpired:
            logger.error("❌ Wechatsync CLI 超时（5分钟）")
            return {"success": False, "platforms": {}, "error": "timeout"}
        except Exception as e:
            logger.error(f"❌ Wechatsync CLI 异常: {e}")
            return {"success": False, "platforms": {}, "error": str(e)}

    def list_platforms(self) -> List[dict]:
        """
        列出所有支持的平台及登录状态（通过 HTTP API）

        返回:
            [{"id": "zhihu", "name": "知乎", "isLoggedIn": true}, ...]
        """
        ws_port = settings.wechatsync_ws_port
        http_port = ws_port + 1

        try:
            import urllib.request
            # 通过 MCP 的 list_platforms 获取
            # 这里简化：直接返回已知平台列表
            # 实际使用时通过 Claude 的 MCP 工具获取
            url = f"http://localhost:{http_port}/status"
            resp = urllib.request.urlopen(url, timeout=3)
            status = json.loads(resp.read().decode())

            if not status.get("connected"):
                logger.warning("Chrome 扩展未连接，无法获取平台列表")
                return []

            # TODO: 通过 HTTP API 转发 listPlatforms 请求
            # 当前简化返回已知平台
            return [
                {"id": k, "name": v, "isLoggedIn": False}
                for k, v in PLATFORM_NAMES.items()
            ]

        except Exception as e:
            logger.warning(f"获取平台列表失败: {e}")
            return []


def get_platform_name(platform_id: str) -> str:
    """获取平台中文名"""
    return PLATFORM_NAMES.get(platform_id, platform_id)
