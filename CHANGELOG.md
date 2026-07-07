# 更新日志

## 2026-07-07: 多平台发布 + Windows兼容

### 新增
- **MultiPost 三平台发布**：脉脉 + 微信公众号 + 今日头条，一键同时发布
- **Pexels API 搜图**：多平台发布时自动从 Pexels 搜配图（中文话题翻译英文关键词）
- **平台优先级排序**：脉脉→公众号→头条（用户明确要求）
- **Playwright 重连机制**：MultiPost 点发布后，Chrome 扩展新开的标签页需要重连 Playwright 才能扫描到
- **URL 匹配策略**：平台标签页扫描改为 URL 匹配为主、内容匹配为辅，解决 MultiPost 格式化内容导致匹配失败的问题
- **标签页自动清理**：每组发布完成后自动关闭所有平台标签页（`_cleanup_platform_tabs`）
- **批量发布脚本**：`multi_publish_0707.py`，从文件读取帖子内容，自动解析+发布

### 修复
- **话题名中文引号**：Write 工具会将中文引号 `""` 转成英文引号 `""`，导致脉脉搜索匹配不到话题。话题名现在从脚本硬编码的 `TOPIC_TAGS` 读取，不从文件读取
- **Windows 兼容性**：
  - `config.py`: Wechatsync 路径改用 `Path.home()` 跨平台
  - `verify_setup.py`: 所有硬编码路径改用 `PROJECT_ROOT` / `Path.home()` / `os.environ`
  - `wechatsync.py`: CLI 路径和提示信息改用跨平台路径
  - `multipost.py`: Chrome 启动提示区分 Mac/Windows

### 改进
- **内容完整性铁律**：title = 话题名（不是粗体导语），body = 粗体导语+后续段落，不能截断/改写
- **平台处理顺序**：按优先级排序（脉脉→公众号→头条）

---

## 2026-07-06: Wechatsync 集成

### 新增
- **Wechatsync MCP 多平台发布**：支持知乎、掘金等 29+ 平台，草稿模式
- **Smart Publisher 智能发布路由**：根据内容自动选择发布方式

---

## 2026-07-01: 初始版本

### 功能
- 爆料活动（paste_post.py）：复制粘贴 → 自动解析 → 批量发脉脉
- 闪电观察者（shandian_post.py）：按话题拆分 → 自动搜图 → 批量发脉脉
- Chrome 启动脚本（start_chrome.py）
- 图片合规打码（EasyOCR + OpenCV）
- Pexels API 搜图备用
