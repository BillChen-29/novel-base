# 知乎盐选下载工具 (2026-05-09 调研)

> 所有工具均需盐选会员账号 + cookie，不能绕过付费墙

## 推荐工具

### xfengyin/zhihu-salt-novel-downloader (3★，最新最全)
- 异步下载 (asyncio + aiohttp)
- 输出格式: TXT / MD / EPUB
- 断点续传、速率控制（令牌桶）、UA 轮换
- Docker 支持
- 安装: `cd /tmp && git clone https://github.com/xfengyin/zhihu-salt-novel-downloader.git && cd zhihu-salt-novel-downloader && pip3 install -r requirements.txt`
- 用法: `python3 cli.py --url https://www.zhihu.com/market/xxx --cookie-file=cookies.json --format=epub`

### onewhitethreee/zhihu_tools (181★，最成熟)
- Python，功能最全
- 需要盐选会员 cookie

### wangbuliuxing714/zhihu_download (9★，GUI 版)
- 基于 zhihu_tools 的图形界面

## Cookie 获取方法
1. Chrome 登录知乎
2. F12 → Application → Cookies → zhihu.com → 复制 `z_c0` 值
3. 或用 EditAnyCookie 插件导出 JSON:
```json
[{"name": "z_c0", "value": "xxx"}, {"name": "q_c1", "value": "..."}]
```

## 知乎 vs 番茄关键差异

| 维度 | 番茄 | 知乎盐选 |
|------|------|---------|
| 章均字数 | 2200-2600 | 800-2000 |
| 人称 | 第三人称为主 | 第一人称为主 (60-70%) |
| 钩子率 | 33% | 50-70% |
| 结局 | 可连载/开放 | 必须完整结局 |
| 试读窗口 | 前30章免费 | 首章前500字 |
| 变现 | 按章广告分成 | 按篇付费 (盐选会员) |
| 叙事密度 | 允许铺垫 | 全程高密度 |

## 采集优先级
P0: 5-10 本热门盐选作品 (悬疑/恐怖/现实/情感/职场各 1-2 本)
P1: 平台规则文档 + 创作者经验帖
P2: 同题材知乎 vs 番茄对比数据

## 实际可用方案：Playwright + OCR（2026-05-09 验证）

由于知乎使用**动态字体加密**（每次请求生成新字体），所有基于文本提取的工具（包括 zhihu_tools、zhihu-salt-novel-downloader）都无法直接获取正确文字。

**唯一可靠方案**：截图渲染后的页面 → OCR 提取文字。

```bash
# 依赖（已安装在 hermes venv）
~/.hermes/hermes-agent/venv/bin/python3 -m pip install playwright
~/.hermes/hermes-agent/venv/bin/python3 -m playwright install chromium

# 使用
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome --remote-debugging-port=9222 &
~/.hermes/hermes-agent/venv/bin/python3 /tmp/zhihu_playwright_scraper.py --connect
```

脚本功能：连接 Chrome CDP → 逐个打开 URL → 截图 → macOS Vision OCR → 保存 TXT

## 注意事项
- 知乎盐选作品有版权保护，仅限个人研究使用
- Hermes 内置浏览器 (Browserbase) 无登录态，不能自主访问知乎
- 需要用户手动提供 cookie 或在浏览器中手动登录
- **字体加密是动态的**，zhihu_tools 的 fontPreview 模块无法复用映射表
