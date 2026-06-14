"""
Windows 上使用自媒体助手的完整指南
"""

# ============================================
# Windows 自媒体助手安装指南
# ============================================

## 第1步：安装 Python

1. 下载 Python 3.9+：https://www.python.org/downloads/
2. 安装时勾选 **"Add Python to PATH"**
3. 打开 PowerShell 验证：python --version

## 第2步：克隆项目

```powershell
git clone https://github.com/bingzhuyeyouke/media-assistant.git
cd media-assistant
```

## 第3步：安装依赖

```powershell
pip install -r requirements.txt
```

依赖包括：
- playwright（浏览器自动化）
- loguru（日志）
- pydantic-settings（配置管理）
- openai（AI API调用）
- easyocr（图片OCR识别）
- opencv-python-headless（图片处理）
- Pillow（图片处理）

## 第4步：安装 Playwright 浏览器

```powershell
playwright install chromium
```

## 第5步：配置 .env

```powershell
copy .env.example .env
notepad .env
```

填入你的 AI API 配置：
```
AI_API_KEY=你的deepseek-api-key
AI_MODEL=deepseek-chat
AI_BASE_URL=https://api.deepseek.com
```

## 第6步：启动 Chrome（调试模式）

**方法A：直接命令行启动**

先完全关闭所有 Chrome 窗口，然后在 PowerShell 运行：

```powershell
# 找到你的 Chrome 路径（通常是下面这个）
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"

# 启动带调试端口的 Chrome
& $chrome --remote-debugging-port=9222 --user-data-dir="$env:TEMP\chrome-automation-profile"
```

**方法B：使用 start_chrome_windows.py**

```powershell
python start_chrome_windows.py
```

## 第7步：登录必要网站

在刚启动的 Chrome 中手动登录：
1. **脉脉**：https://maimai.cn （登录你的账号）
2. **MultiPost**：https://multipost.app （登录并安装浏览器扩展）

## 第8步：使用

### 模式一：自动抓取（启动！）
告诉 Claude："启动！"，自动抓取小渔学姐最新帖子

### 模式二：自定义帖子（发链接）
给 Claude 发脉脉帖子链接，如：
https://maimai.cn/community/gossip-detail/37007088?egid=xxx

### 命令行直接运行
```powershell
# 自动抓取模式
python auto_scrape_publish.py

# 自定义帖子模式
python custom_post_publish.py "https://maimai.cn/community/gossip-detail/xxxxx?egid=xxx"

# 干跑模式（不真正发布）
python auto_scrape_publish.py --dry-run
python custom_post_publish.py "URL" --dry-run
```

# ============================================
# 常见问题
# ============================================

## Q: Chrome 端口被占用？
先关闭所有 Chrome 窗口（包括系统托盘），再重新启动

## Q: 连接 Chrome 失败？
确认 Chrome 是用 --remote-debugging-port=9222 启动的

## Q: EasyOCR 首次运行很慢？
首次运行会下载模型（约100MB），之后就快了

## Q: 图片打码不生效？
检查 adapter/compliance.py 中的 COMPANY_KEYWORDS 是否包含需要打码的关键词
