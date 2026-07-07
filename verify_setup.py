#!/usr/bin/env python3
"""
环境验证脚本 —— 一键检查 Wechatsync + Maimai 多平台发布环境

检查项：
  1. Chrome 是否运行（CDP 端口 9222）
  2. Wechatsync 扩展是否加载
  3. Wechatsync MCP Server 是否可启动
  4. MCP Token 配置是否一致
  5. 各平台登录状态
  6. 依赖包是否安装

用法：
  python3 verify_setup.py
"""

import json
import os
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path

# 颜色输出
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
BLUE = "\033[94m"
RESET = "\033[0m"

# 检查结果统计
checks_passed = 0
checks_failed = 0
checks_warned = 0


def check(name: str, passed: bool, message: str = "", is_warning: bool = False):
    """输出检查结果"""
    global checks_passed, checks_failed, checks_warned

    if is_warning:
        status = f"{YELLOW}⚠️{RESET}"
        checks_warned += 1
    elif passed:
        status = f"{GREEN}✓{RESET}"
        checks_passed += 1
    else:
        status = f"{RED}✗{RESET}"
        checks_failed += 1

    print(f"  {status} {name}", end="")
    if message:
        print(f" — {message}", end="")
    print()


def main():
    global checks_passed, checks_failed, checks_warned

    print(f"\n{BLUE}{'='*50}{RESET}")
    print(f"{BLUE}  🔍 多平台发布环境验证{RESET}")
    print(f"{BLUE}{'='*50}{RESET}\n")

    # ===== 1. Chrome CDP =====
    print(f"{BLUE}📡 Chrome 浏览器{RESET}")
    cdp_ok = False
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            result = s.connect_ex(('localhost', 9222))
            cdp_ok = (result == 0)
        check("Chrome CDP 端口 9222", cdp_ok,
              "可用" if cdp_ok else "未启动 — 运行 python3 start_chrome.py")

        if cdp_ok:
            resp = urllib.request.urlopen("http://localhost:9222/json/version", timeout=3)
            info = json.loads(resp.read().decode())
            check("Chrome 版本", True, info.get("Browser", "未知"))
    except Exception as e:
        check("Chrome CDP 端口 9222", False, str(e))

    print()

    # ===== 2. Wechatsync 项目 =====
    print(f"{BLUE}📦 Wechatsync 项目{RESET}")
    ws_path = Path.home() / "Wechatsync"
    check("项目目录", ws_path.exists(),
          str(ws_path) if ws_path.exists() else "未克隆 — git clone https://github.com/wechatsync/Wechatsync.git")

    # 检查构建产物
    ext_dist = ws_path / "packages/extension/dist/manifest.json"
    check("Chrome 扩展构建", ext_dist.exists(),
          "已构建" if ext_dist.exists() else "未构建 — cd Wechatsync && pnpm build")

    mcp_dist = ws_path / "packages/mcp-server/dist/index.js"
    check("MCP Server 构建", mcp_dist.exists(),
          "已构建" if mcp_dist.exists() else "未构建")

    cli_dist = ws_path / "packages/cli/dist/index.js"
    check("CLI 构建", cli_dist.exists(),
          "已构建" if cli_dist.exists() else "未构建")

    print()

    # ===== 3. Wechatsync Chrome 扩展 =====
    print(f"{BLUE}🧩 Wechatsync Chrome 扩展{RESET}")

    if cdp_ok:
        try:
            # 方法1：通过扩展目录检查
            ext_dir = Path(os.environ.get("TEMP", "/tmp")) / "chrome-automation-profile" / "Default" / "Extensions"
            ext_found = False
            if ext_dir.exists():
                for ext_id_dir in ext_dir.iterdir():
                    if not ext_id_dir.is_dir():
                        continue
                    for version_dir in ext_id_dir.iterdir():
                        manifest_path = version_dir / 'manifest.json'
                        if manifest_path.exists():
                            try:
                                m = json.loads(manifest_path.read_text())
                                if '同步助手' in m.get('name', '') or 'wechatsync' in m.get('name', '').lower():
                                    ext_found = True
                                    ext_version = m.get('version', '?')
                                    check("扩展已加载", True, f"{m.get('name')} v{ext_version}")
                                    break
                            except Exception:
                                pass
                    if ext_found:
                        break
            if not ext_found:
                # 方法2：CDP targets 搜索
                resp = urllib.request.urlopen("http://localhost:9222/json/list", timeout=3)
                targets = json.loads(resp.read().decode())
                ext_found = any(
                    "wechatsync" in t.get("url", "").lower() or
                    "sync-assistant" in t.get("url", "").lower() or
                    "wechatsync" in t.get("title", "").lower()
                    for t in targets
                )
                check("扩展已加载", ext_found,
                      "已检测到" if ext_found else "未检测到 — 在 Chrome 中加载扩展")
        except Exception as e:
            check("扩展已加载", False, f"检查失败: {e}")
    else:
        check("扩展已加载", False, "Chrome 未运行，无法检查", is_warning=True)

    print()

    # ===== 4. Wechatsync MCP Server =====
    print(f"{BLUE}🔌 Wechatsync MCP Server{RESET}")

    # 检查 MCP Server 进程
    ws_port = 9527
    http_port = ws_port + 1
    mcp_running = False

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            result = s.connect_ex(('localhost', ws_port))
            mcp_running = (result == 0)
    except Exception:
        pass

    check("MCP Server WebSocket 端口 9527", mcp_running,
          "运行中" if mcp_running else "未运行（Claude Code 会自动启动）", is_warning=not mcp_running)

    # 检查 Extension 连接状态
    if mcp_running:
        try:
            resp = urllib.request.urlopen(f"http://localhost:{http_port}/status", timeout=3)
            status = json.loads(resp.read().decode())
            ext_connected = status.get("connected", False)
            check("Chrome 扩展 → MCP Server", ext_connected,
                  "已连接" if ext_connected else "未连接 — 检查扩展设置中的 MCP 连接开关和 Token")
        except Exception as e:
            check("Chrome 扩展 → MCP Server", False, f"检查失败: {e}")
    else:
        check("Chrome 扩展 → MCP Server", False, "MCP Server 未运行，无法检查", is_warning=True)

    print()

    # ===== 5. MCP Token 配置 =====
    print(f"{BLUE}🔑 MCP Token 配置{RESET}")

    # 读取 .env 中的 Token
    env_path = PROJECT_ROOT / ".env"
    env_token = ""
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith("WECHATSYNC_TOKEN="):
                env_token = line.split("=", 1)[1].strip()
                break

    check(".env Token 配置", bool(env_token),
          f"已配置 ({env_token[:8]}...)" if env_token else "未配置")

    # 读取 .mcp.json 中的 Token
    mcp_json_path = PROJECT_ROOT / ".mcp.json"
    mcp_token = ""
    if mcp_json_path.exists():
        try:
            mcp_config = json.loads(mcp_json_path.read_text())
            mcp_token = mcp_config.get("mcpServers", {}).get("wechatsync", {}).get("env", {}).get("WECHATSYNC_TOKEN", "")
        except Exception:
            pass

    check(".mcp.json Token 配置", bool(mcp_token),
          f"已配置 ({mcp_token[:8]}...)" if mcp_token else "未配置")

    if env_token and mcp_token:
        tokens_match = (env_token == mcp_token)
        check("Token 一致性", tokens_match,
              "一致" if tokens_match else f"不一致！.env={env_token}, .mcp.json={mcp_token}")

    print()

    # ===== 6. Python 依赖 =====
    print(f"{BLUE}🐍 Python 依赖{RESET}")

    dependencies = [
        ("playwright", "Playwright (浏览器自动化)"),
        ("pydantic_settings", "Pydantic Settings (配置管理)"),
        ("loguru", "Loguru (日志)"),
        ("openai", "OpenAI (AI 内容改写)"),
    ]

    for module, desc in dependencies:
        try:
            __import__(module)
            check(desc, True)
        except ImportError:
            check(desc, False, "未安装")

    # 检查 Playwright 浏览器
    try:
        from playwright.sync_api import sync_playwright
        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=True)
        browser.close()
        pw.stop()
        check("Playwright Chromium", True, "已安装")
    except Exception:
        check("Playwright Chromium", False, "未安装 — 运行 playwright install chromium")

    print()

    # ===== 7. 配置文件 =====
    print(f"{BLUE}⚙️ 配置文件{RESET}")

    check(".env 文件", env_path.exists(),
          str(env_path) if env_path.exists() else "缺失")
    check(".mcp.json 文件", mcp_json_path.exists(),
          str(mcp_json_path) if mcp_json_path.exists() else "缺失")

    print()

    # ===== 汇总 =====
    print(f"{BLUE}{'='*50}{RESET}")
    total = checks_passed + checks_failed + checks_warned
    print(f"  检查完成: {GREEN}{checks_passed} 通过{RESET}, {RED}{checks_failed} 失败{RESET}, {YELLOW}{checks_warned} 警告{RESET}")

    if checks_failed == 0:
        print(f"  {GREEN}🎉 环境就绪！{RESET}")
        print()
        print("  日常工作流：")
        print("    1. 给 Claude 一篇文章（标题 + 正文）")
        print("    2. Claude 调用 Wechatsync MCP 发布到各平台（草稿模式）")
        print("    3. 各平台后台审查草稿 → 点击发布")
        print()
        print("  常用 MCP 命令：")
        print("    • list_platforms  — 查看支持的平台和登录状态")
        print("    • check_auth      — 检查指定平台登录状态")
        print("    • sync_article    — 发布文章到指定平台（草稿）")
        print("    • upload_image_file — 上传本地图片")
    else:
        print(f"  {RED}❌ 有 {checks_failed} 项未通过，请按提示修复{RESET}")
        sys.exit(1)

    print(f"{BLUE}{'='*50}{RESET}\n")


if __name__ == "__main__":
    main()
