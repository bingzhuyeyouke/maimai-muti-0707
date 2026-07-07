"""
Chrome 启动辅助脚本（Mac/Windows 双平台）

用途：一键启动带远程调试端口的 Chrome，供 Playwright 连接

使用方法：
  python3 start_chrome.py

启动后 Chrome 会打开，保持该终端窗口不要关闭。
然后在另一个终端运行发帖程序：
  python3 paste_post.py

⚠️  如果 Chrome 已经在运行，需要先完全退出再运行本脚本
"""

import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

from loguru import logger

# ========== 跨平台配置 ==========

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    # Windows Chrome 路径（按优先级尝试）
    CHROME_PATHS = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    CHROME_USER_DATA = os.path.join(os.environ.get("TEMP", ""), "chrome-automation-profile")
    CHROME_DEFAULT_PROFILE = os.path.expandvars(
        r"%LocalAppData%\Google\Chrome\User Data"
    )
else:
    # macOS Chrome 路径
    CHROME_PATHS = [
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    CHROME_USER_DATA = "/tmp/chrome-automation-profile"
    CHROME_DEFAULT_PROFILE = str(Path.home() / "Library/Application Support/Google/Chrome")

# 远程调试端口
DEBUG_PORT = 9222


def find_chrome() -> str:
    """查找 Chrome 可执行文件"""
    for path in CHROME_PATHS:
        if Path(path).exists():
            return path
    raise FileNotFoundError(
        "未找到 Chrome，请安装 Google Chrome\n"
        "下载地址：https://www.google.com/chrome/"
    )


def copy_profile_if_needed():
    """如果临时 profile 不存在，从默认 profile 复制"""
    dest = Path(CHROME_USER_DATA)
    if dest.exists():
        logger.info(f"临时 profile 已存在: {dest}")
        return

    src = Path(CHROME_DEFAULT_PROFILE)
    if not src.exists():
        logger.warning("未找到 Chrome 默认 profile，将使用空白 profile")
        dest.mkdir(parents=True, exist_ok=True)
        return

    logger.info("首次运行，复制 Chrome profile（约需1分钟）...")
    dest.mkdir(parents=True, exist_ok=True)
    dest_default = dest / "Default"
    dest_default.mkdir(parents=True, exist_ok=True)

    src_default = src / "Default"
    # 复制关键文件
    items = [
        "Extensions", "Extension State", "Extension Rules",
        "Local Storage", "Session Storage", "IndexedDB",
        "Cookies", "Cookies-journal",
        "Login Data", "Login Data-journal",
        "Web Data", "Web Data-journal",
        "Preferences", "Secure Preferences",
        "Local Extension Settings",
        "Favicons", "Favicons-journal",
        "History", "History-journal",
        "Bookmarks",
    ]

    for item in items:
        src_item = src_default / item
        if src_item.exists():
            try:
                if IS_WINDOWS:
                    # Windows 用 shutil.copytree/copy2
                    dst_item = dest_default / item
                    if src_item.is_dir():
                        if dst_item.exists():
                            shutil.rmtree(dst_item)
                        shutil.copytree(str(src_item), str(dst_item))
                    else:
                        shutil.copy2(str(src_item), str(dst_item))
                else:
                    # macOS 用 cp -r（更快）
                    subprocess.run(["cp", "-r", str(src_item), str(dest_default / item)],
                                   capture_output=True, timeout=30)
                logger.debug(f"  ✓ {item}")
            except Exception as e:
                logger.warning(f"  ✗ {item}: {e}")

    # 复制父级配置
    for item in ["Local State", "First Run", "Last Browser"]:
        src_item = src / item
        if src_item.exists():
            try:
                if IS_WINDOWS:
                    shutil.copy2(str(src_item), str(dest / item))
                else:
                    subprocess.run(["cp", str(src_item), str(dest / item)],
                                   capture_output=True, timeout=5)
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
    copy_profile_if_needed()

    if not check_port_available():
        logger.info("Chrome 可能已经在运行，尝试连接...")
        return True

    logger.info("启动 Chrome...")
    cmd = [
        chrome_path,
        f"--remote-debugging-port={DEBUG_PORT}",
        f"--user-data-dir={CHROME_USER_DATA}",
        "--disable-popup-blocking",        # 减少弹窗提示，让扩展打开标签页更顺畅
        "--disable-background-timer-throttling",  # 后台标签页不受限
        "--disable-renderer-backgrounding",       # 后台渲染不被抑制
        "--disable-backgrounding-occluded-windows",  # 遮挡时仍正常运行
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
            logger.info(f"保持此窗口不要关闭，在另一个终端运行：python3 paste_post.py")
            return True
    except Exception:
        pass

    logger.error("Chrome 启动失败，请检查是否有其他 Chrome 实例在运行")
    if IS_WINDOWS:
        logger.info("请先完全退出 Chrome（关闭所有窗口），然后重新运行本脚本")
    else:
        logger.info("请先完全退出 Chrome（Cmd+Q），然后重新运行本脚本")
    return False


if __name__ == "__main__":
    start_chrome()
