# 知乎盐选内容抓取方案

> 通过 AppleScript 控制已登录的 Chrome 浏览器，绕过知乎反爬机制

## 前提条件
- macOS
- Chrome 已登录知乎（有盐选会员）
- Chrome 菜单 → 视图 → 开发者 → 勾选「允许 Apple 事件中的 JavaScript」

## Cookie 提取

```applescript
-- 通过 AppleScript 获取 Chrome 当前页面的 cookies
osascript -e 'tell application "Google Chrome"
  execute active tab of front window javascript "document.cookie"
end tell'
```

保存为 JSON 格式供 CLI 工具使用：
```python
cookies = document.cookie.split("; ").map(c => {
  var parts = c.split("=");
  return {name: parts[0], value: parts.slice(1).join("=")};
});
JSON.stringify(cookies);
```

## 盐选故事内容提取

### URL 格式
- 列表页：`https://www.zhihu.com/market/paid_column/{column_id}/section/{section_id}`
- 文章页：`https://zhuanlan.zhihu.com/p/{article_id}`

### 内容提取 JS（关键）

盐选故事的正文存储在 `#resolved` 元素的 JSON 数据中：

```javascript
var r = document.getElementById("resolved");
var d = JSON.parse(r.textContent);
var md = d.appContext.__connectedAutoFetch.manuscript.data.manuscriptData;

// 标题
var title = md.title;

// 正文 HTML
var html = md.manuscript; // 包含 <p> 标签

// 转为纯文本（保留段落）
var tmp = document.createElement("div");
tmp.innerHTML = html;
var paragraphs = Array.from(tmp.querySelectorAll("p"))
  .map(p => p.textContent.trim())
  .filter(t => t.length > 0);
var text = paragraphs.join("\n");
```

### 其他可用字段
- `md.like_count` — 点赞数
- `md.comment_count` — 评论数
- `md.next_section` — 下一章信息
- `md.use_font` — 是否使用字体加密（true=有反爬字体）
- `md.truncate_text` — 付费墙提示文本
- `md.sku_right_type` — 权限类型（svip_free 等）

## 搜索 API

```
GET https://www.zhihu.com/api/v4/search_v3?t=general&q={关键词}&correction=1&offset=0&limit=20
```

有效的搜索词：
- "盐选 悬疑"、"盐选 惊悚"、"盐选 完结"
- "盐选 该看"、"知乎 结局 全文后续"

返回的 `item.object.url` 包含 `market/paid_column` 的即为盐选内容。

## 字体加密问题（深度分析 2026-05-09）

知乎使用**动态字体加密**（`dynamic_font_schema: 1`），是目前最复杂的反爬字体方案。

### 加密机制

1. 每次页面请求生成 **4 个自定义 TTF 字体**（base64 内嵌在 CSS `@font-face` 中）
2. 两个字体家族（normal + bold 各一）：
   - **小字体**（~5.5KB）：6 个高频字（一不了在是的）
   - **大字体**（~23KB）：80 个常用字 + 标点
3. HTML 中的 Unicode 是**加密后的**字符，字体将其渲染为**不同的视觉字形**
4. **每次请求字体不同** —— 映射表无法复用

### 字体结构

```
@font-face {
  font-family: 'zh_MA275312974a...';  // 小字体
  font-weight: normal;
  src: url(data:font/ttf;charset=utf-8;base64,...);
}
@font-face {
  font-family: 'zh_MA1193bd3e1e...';  // 大字体（80字符）
  font-weight: normal;
  src: url(data:font/ttf;charset=utf-8;base64,...);
}
```

### 大字体覆盖的 80 个字符

标点：。「」！：？
常用字：一不了在是的上了个中为于交什从代以任传低作值养再况几利力务化发各和商国在地场多学对导层当意我或把持放时有期权来然率环现相着知策算系结职能节被要说课越这通（共74字+6标点）

### 已验证失败的方案

| 方案 | 失败原因 |
|------|---------|
| textContent / DOMParser | HTML 本身就是加密 Unicode |
| Selection API | 返回加密 Unicode |
| 去掉自定义字体 | HTML 文本不变 |
| 剪贴板复制 (Cmd+C) | 知乎禁用了 copy/selectstart 事件 |
| 字形尺寸/哈希/像素对比 | 三个字体字形完全不同，无法匹配 |
| screencapture | 沙箱内无法截图 |
| Chrome Cmd+P 打印 | 可能被拦截 |

### 可行方案：Playwright + 截图 + OCR

**唯一可靠的自动化方案**：用 Playwright 控制浏览器截图渲染后的页面，再用 macOS Vision OCR 提取文字。

脚本路径：`/tmp/zhihu_playwright_scraper.py`（Claude Code 生成，649行）

```bash
# 1. 重启 Chrome 开启调试端口
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &

# 2. 在 Chrome 中登录知乎

# 3. 运行抓取脚本
~/.hermes/hermes-agent/venv/bin/python3 /tmp/zhihu_playwright_scraper.py --connect
```

**流程**：连接 Chrome CDP → 逐个打开 URL → 等待渲染 → 截图文章区域 → macOS Vision OCR → 保存 TXT

**依赖**：playwright + pyobjc-framework-Vision（均已在 hermes venv 安装）

## 已知限制
- 列表页（paid_column）不返回 "resolved" 元素，只有 section 页才有
- 章节列表需要从列表页的 DOM 链接中提取
- 每次导航需要等待 4-5 秒让页面渲染
- 部分搜索 API 返回 404，端点可能已变更
- **字体加密是动态的**，无法建立静态映射表
- 下载工具（zhihu_tools, zhihu-salt-novel-downloader）因字体加密无法直接使用
