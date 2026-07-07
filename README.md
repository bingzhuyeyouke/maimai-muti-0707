# 脉脉自动化发帖助手 (maimai)

自动化运营脉脉账号的 Python 工具，支持多平台发布：**脉脉 + 微信公众号 + 今日头条**。

## 🎯 功能概览

### 🌐 多平台发布（MultiPost）

一键同时发布到 **脉脉、微信公众号、今日头条** 三个平台，带配图。

```
运营给话题+文案 → 解析文章 → Pexels搜图 → MultiPost三平台发布 → 自动清理
95% 自动，5% 复制粘贴
```

**平台操作规则：**
| 平台 | 操作 |
|---|---|
| 脉脉 | 切身份 → 加话题 → 勾发布设置 → 发动态 |
| 微信公众号 | 保存为草稿（不发表） |
| 今日头条 | 追加 `#上头条 聊热点#` → 点发布 |

**使用方式：**
```bash
# 1. 启动 Chrome
python3 start_chrome.py

# 2. 运行多平台发布脚本
python3 multi_publish_0707.py
```

**发帖间隔：** 3分钟（±30秒抖动）

---

### 📢 爆料活动（paste_post.py）

复制 DeepSeek 生成的内容 → 自动解析 → 批量发到脉脉

```
你复制粘贴 → 自动解析标题+正文 → 选话题"我来爆个料" → 上传图片 → 批量发布
5% 手动，95% 自动
```

**使用方式：**
```bash
# 1. 启动 Chrome
python3 start_chrome.py

# 2. 交互式发帖（推荐）
python3 paste_post.py
# 粘贴内容，输入 END

# 3. 从文件发帖
python3 paste_post.py --file posts.txt

# 4. 干跑预览（不实际发布）
python3 paste_post.py --file posts.txt --dry-run
```

**内容格式（DeepSeek 输出直接复制）：**
```
1. 标题：xxx
正文：xxx
2. 标题：xxx
正文：xxx
```

**图片：** 放到 `posts/images/` 目录，按序号自动配对（1.jpg→第1篇，2.jpg→第2篇）

**发帖间隔：** 2~3 分钟随机（防机器人检测）

---

### ⚡ 闪电观察者（shandian_post.py）

粘贴 DeepSeek 输出 → 按话题拆分 → 自动搜图 → 批量发到脉脉

```
运营给热点话题 → DeepSeek 创作 → 粘贴输出 → 自动拆分话题+文章 → 网络搜图 → 发布
每个话题2篇文章，自动选择对应话题名称
```

**使用方式：**
```bash
# 1. 启动 Chrome
python3 start_chrome.py

# 2. 交互式发帖
python3 shandian_post.py

# 3. 从文件发帖
python3 shandian_post.py --file shandian.txt

# 4. 干跑预览
python3 shandian_post.py --file shandian.txt --dry-run

# 5. 跳过搜图
python3 shandian_post.py --file shandian.txt --no-image
```

**内容格式（DeepSeek 输出直接复制）：**
```
## 话题名称1

**第一篇｜标题1**

正文段落1

正文段落2

**第二篇｜标题2**

正文段落1

## 话题名称2
...
```

**图片：** 自动从百度图片搜索（零配置），Pexels API 可选备用

**发帖间隔：** 1~2 分钟随机

---

## 📋 模式对比

| | 多平台发布 | 爆料活动 | 闪电观察者 |
|---|---|---|---|
| 入口 | `multi_publish_0707.py` | `paste_post.py` | `shandian_post.py` |
| 平台 | 脉脉+公众号+头条 | 脉脉 | 脉脉 |
| 话题 | 按运营给的话题名称搜索 | 固定"我来爆个料" | 按运营给的话题名称搜索 |
| 图片 | Pexels API 自动搜图 | 手动放到 `posts/images/` | 自动网络搜索（百度/Pexels） |
| 篇数/话题 | 2篇 | 1篇 | 2篇 |
| 间隔 | 3分钟 | 2~3分钟 | 1~2分钟 |

## 🛠️ 安装

```bash
git clone https://github.com/bingzhuyeyouke/maimai.git
cd maimai
pip install -r requirements.txt
```

## ⚙️ 配置

复制 `.env.example` 为 `.env`，按需填写：

```bash
cp .env.example .env
```

| 配置项 | 说明 | 默认值 |
|---|---|---|
| `MAIMAI_POST_INTERVAL` | 爆料活动发帖间隔（秒） | 150 |
| `SHANDIAN_POST_INTERVAL` | 闪电观察者发帖间隔（秒） | 90 |
| `MULTIPOST_POST_INTERVAL` | 多平台发帖间隔（秒） | 180 |
| `PEXELS_API_KEY` | Pexels API Key（多平台搜图必需） | 空 |
| `AI_API_KEY` | AI 接口密钥（合规改写用） | 空 |
| `AI_MODEL` | AI 模型 | deepseek-chat |
| `AI_BASE_URL` | AI 接口地址 | https://api.deepseek.com |
| `WECHATIONSYNC_TOKEN` | Wechatsync MCP Token | 空 |

## 🚀 快速开始

### 第一步：启动 Chrome

```bash
python3 start_chrome.py
```

保持此终端窗口不关闭。Chrome 会以调试端口 9222 启动。

### 第二步：登录平台

在打开的 Chrome 中登录：
- [maimai.cn](https://maimai.cn)（脉脉）
- [mp.weixin.qq.com](https://mp.weixin.qq.com)（微信公众号）
- [mp.toutiao.com](https://mp.toutiao.com)（今日头条）
- [multipost.app](https://multipost.app)（MultiPost 扩展）

### 第三步：发帖

打开新终端，按需选择模式：

```bash
# 多平台发布（脉脉+公众号+头条）
python3 multi_publish_0707.py

# 爆料活动（仅脉脉）
python3 paste_post.py

# 闪电观察者（仅脉脉）
python3 shandian_post.py
```

## 📁 项目结构

```
maimai/
├── multi_publish_0707.py  # 多平台发布脚本（脉脉+公众号+头条）
├── paste_post.py          # 爆料活动入口
├── shandian_post.py       # 闪电观察者入口
├── publisher/
│   ├── multipost.py       # MultiPost 多平台发布核心
│   ├── maimai.py          # 脉脉发帖核心（MaimaiPageOps mixin）
│   ├── wechatsync.py      # Wechatsync 多平台发布（知乎/掘金等）
│   └── smart_publisher.py # 智能发布路由
├── adapter/
│   ├── compliance.py      # 图片合规打码（爆料活动用）
│   └── image_search.py    # 图片搜索（百度网页+Pexels API）
├── config.py              # 配置管理
├── start_chrome.py        # Chrome 启动脚本（Mac/Windows 双平台）
├── db/
│   └── database.py        # SQLite 数据库
├── posts/
│   ├── images/            # 爆料活动图片目录
│   └── multi_0707_images/ # 多平台发布图片目录
├── requirements.txt
├── .env.example           # 配置模板
└── README.md
```

## 🔧 技术栈

- **Python** + **Playwright**（浏览器自动化）
- **Chrome DevTools Protocol**（连接已登录的浏览器）
- **MultiPost Extension**（多平台一键分发）
- **Pexels API**（自动搜配图）
- **DeepSeek**（AI 内容生成）
- **百度图片 / Pexels**（自动搜图）
- **EasyOCR + OpenCV**（图片合规打码）
- **SQLite**（去重存储）
- **Pydantic Settings**（配置管理）

## 💻 跨平台支持

支持 **macOS** 和 **Windows**：
- Chrome 启动脚本自动检测操作系统
- 路径使用 `Path` 对象，兼容不同路径分隔符
- 快捷键自动适配（Mac: Command, Windows: Control）
- 临时目录自动适配（Mac: `/tmp`, Windows: `%TEMP%`）

## ⚠️ 注意事项

- Chrome 需要以调试端口 9222 启动（`start_chrome.py`）
- 发帖前确保已登录脉脉、微信公众号、今日头条
- 发帖间隔有随机抖动防检测，建议不要手动缩短
- 闪电观察者的图片搜索依赖网络，搜不到图时会无图发布
- 话题搜索依赖脉脉话题库，新话题可能搜不到（不影响发帖）
- **话题名中的引号必须用中文引号 `""`**，不能用英文引号 `""`，否则脉脉搜索匹配不到
- **公众号只保存草稿，不发表**
- **头条正文末尾自动追加 `#上头条 聊热点#`**

## 📄 License

MIT