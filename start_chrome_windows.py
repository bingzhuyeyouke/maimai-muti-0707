"""
Windows Chrome 启动辅助脚本

用途：在 Windows 上一键启动带远程调试端口的 Chrome

使用方法：
  python start_chrome_windows.py

启动后 Chrome 会打开，保持该窗口不要关闭。
然后在另一个终端运行主程序：
  python auto_scrape_publish.py
  或
  python custom_post_publish.py "帖子URL"
"""

import subprocess
import sys
import time
import os
import shutil
from pathlib import Path
from loguru import logger

# Windows Chrome 可能的路径
CHROME_PATHS = [
    os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
    os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
]

# 用户数据目录
CHROME_USER_DATA = os.path.join(os.environ.get("TEMP", "."), "chrome-automation-profile")

# 远程调试端口
DEBUG_PORT = 9222


def find_chrome() -> str:
    """查找 Chrome 可执行文件"""
    for path in CHROME_PATHS:
        if os.path.exists(path):
            return path
    logger.error("未找到 Chrome，请安装 Google Chrome")
    logger.info("下载地址：https://www.google.com/chrome/")
    return ""


def copy_profile_if_needed():
    """如果临时 profile 不存在，从默认 profile 复制"""
    dest = Path(CHROME_USER_DATA)
    if dest.exists():
        logger.info(f"临时 profile 已存在: {dest}")
        return

    # Windows Chrome 默认 profile 路径
    src = Path(os.path.expandvars(r"%LocalAppData%\Google\Chrome\User Data"))
    if not src.exists():
        logger.warning("未找到 Chrome 默认 profile，将使用空 profile")
        dest.mkdir(parents=True, exist_ok=True)
        return

    logger.info("首次运行，复制 Chrome profile（约需1分钟）...")
    dest.mkdir(parents=True, exist_ok=True)
    dest_default = dest / "Default"
    dest_default.mkdir(parents=True, exist_ok=True)

    src_default = src / "Default"
    items = [
        "Extensions", "Extension State", "Extension Rules",
        "Local Storage", "Session Storage", "IndexedDB",
        "Cookies", "Login Data", "Web Data",
        "Preferences", "Secure Preferences",
        "Local Extension Settings",
        "Favicons", "History", "Bookmarks",
    ]

    for item in items:
        src_item = src_default / item
        if src_item.exists():
            try:
                if src_item.is_dir():
                    shutil.copytree(str(src_item), str(dest_default / item), dirs_exist_ok=True)
                else:
                    shutil.copy2(str(src_item), str(dest_default / item))
                logger.debug(f"  ✓ {item}")
            except Exception as e:
                logger.warning(f"  ✗ {item}: {e}")

    # 复制父级配置
    for item in ["Local State", "First Run", "Last Browser"]:
        src_item = src / item
        if src_item.exists():
            try:
                shutil.copy2(str(src_item), str(dest / item))
            except Exception:
                pass

    logger.success("Profile 复制完成 ✓")


def check_port_available() -> bool:
    """检查调试端口是否已被占用"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        result = s.connect_ex(('localhost', DEBUG_PORT))
        if result == 0:
            logger.warning(f"端口 {DEBUG_PORT} 已被占用，Chrome 可能已在运行")
            return False
    return True


def start_chrome():
    """启动带调试端口的 Chrome"""
    chrome_path = find_chrome()
    if not chrome_path:
        return False

    copy_profile_if_needed()

    if not check_port_available():
        logger.info("Chrome 可能已经在运行，尝试连接...")
        return True

    logger.info("启动 Chrome...")
    cmd = [
        chrome_path,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={CHROME_USER_DATA}",
    ]

    # 在后台启动
    process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 等待启动
    logger.info("等待 Chrome 启动...")
    time.sleep(5)

    # 检查是否成功
    import urllib.request
    try:
        resp = urllib.request.urlopen(f"http://localhost:{DEBUG_PORT}/json/version", timeout=3)
        if resp.status == 200:
            logger.success(f"✓ Chrome 已启动，调试端口: {DEBUG_PORT}")
            logger.info("保持此窗口不要关闭，在另一个终端运行：")
            logger.info("  python auto_scrape_publish.py         # 自动抓取模式")
            logger.info('  python custom_post_publish.py "URL"   # 自定义帖子模式')
            return True
    except Exception:
        pass

    logger.error("Chrome 启动失败，请检查是否有其他 Chrome 实例在运行")
    logger.info("请先完全退出 Chrome（关闭所有窗口和系统托盘），然后重新运行本脚本")
    return False


if __name__ == "__main__":
    start_chrome()
