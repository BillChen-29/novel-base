# 番茄小说数据抓取

## 反爬机制

番茄小说使用 **自定义字体反爬**：
- 页面上视觉文字正常显示
- DOM 中文字是乱码（字体映射不同 Unicode 码位）
- 浏览器 snapshot 和 OCR 均受影响

## 已测试的 API

| 端点 | 状态 | 说明 |
|------|------|------|
| `/api/author/book/category_list/v0/` | ✅ 可用 | 返回所有分类（女频悬疑、科幻末世、古风世情等） |
| `/api/author/library/book_list/v0/` | ❌ 需要认证 | 返回"参数有误" |
| `/api/author/book/rank_list/v0/` | ❌ 404 | 排行榜 API 不存在 |
| `novel.snssdk.com/api/...` | ❌ 404 | 旧域名已失效 |

## 可行方案

### 方案 1：用户截图 + macOS Vision OCR（推荐）

用户在 App/网页截图，Hermes 用 pyobjc + Vision 框架识别。

**关键 pitfall：** `vision_analyze` 工具对本地临时文件路径（screencapture 生成的）不可靠，必须用 Python 脚本直接调用 macOS Vision 框架。

**OCR 脚本模板：**
```python
import objc
from Foundation import NSURL
from Quartz import CIImage
import Vision

def ocr_image(path):
    url = NSURL.fileURLWithPath_(path)
    ci_image = CIImage.imageWithContentsOfURL_(url)
    request = Vision.VNRecognizeTextRequest.alloc().init()
    request.setRecognitionLanguages_(["zh-Hans", "zh-Hant", "en"])
    request.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    handler = Vision.VNImageRequestHandler.alloc().initWithCIImage_options_(ci_image, None)
    handler.performRequests_error_([request], None)
    results = []
    for obs in request.results():
        text = obs.topCandidates_(1)[0].string()
        conf = obs.topCandidates_(1)[0].confidence()
        results.append({"text": text, "confidence": round(conf, 2)})
    return results

# 用法：先 cp 截图到 /tmp，再调用 ocr_image("/tmp/screenshot.png")
```

**运行环境：** `~/.hermes/hermes-agent/venv/bin/python3`（已安装 pyobjc-framework-Vision）

### 方案 2：第三方数据平台

橙瓜数据、塔读文学数据等有网文热度排行，不反爬。

### 方案 3：TomatoNovelDownloader（Rust TUI，推荐批量下载）

**仓库/下载：** GitHub Releases → `TomatoNovelDownloader-macOS_arm64-v2.4.9`
**用法：** TUI 交互模式（默认）或 `--server` 启动 Web UI
**macOS：** 首次需 `chmod +x` + 系统偏好设置→安全性→仍要打开

**输出格式（分析脚本必须适配）：**
- 章节分隔符：`----------------------------------------`（40个连字符），**不是** `第X章` pattern
- 文件头：元数据行（书名/作者/book_id/评分/字数/章节/分类/标签/在读）→ 空行 → 第1章正文
- **对话引号被剥离**：输出无 `""「」`，对话检测需用 EPUB 格式或语气词推断
- 标点：全角 `！` `？` `……` `，` `。`
- 每本生成 `.txt` + 同名目录（元数据），EPUB 格式也可选
- **EPUB 对话保留**：epub 格式保留智能引号 `\u201C\u201D`，可用于对话比例分析
- 分章代码模板见 `references/novel-pacing-analysis.md`

### 方案 4：GitHub 爬虫工具

`fanqie-novel-download` 等，主要下小说内容，排行榜支持不确定。

## 已获取的数据

### 书荒热词榜（读者想看但供给不足的题材）

**男频脑洞向：** 游戏、单女主、末世、搞笑、异能、同人、直播、诡异、无限、扮演
**男频传统向：** 修仙、无敌、年代、谍战、科技、进化、武侠、**悬疑**（#8）、种田、西游

### 男频总榜头部（2026-05 数据）

| 排名 | 书名 | 作者 | 核心元素 |
|------|------|------|----------|
| 1 | 我不是戏神 | 三九音域 | 科幻+悬疑 |
| 2 | 精神病院学斩神 | 三九音域 | 都市+诡异+悬疑 |
| 3 | 天眼风水师 | 道之光 | 风水+道医 |
| 9 | 十日终焉 | 杀虫队队员 | 末世+悬疑+规则 |
| 11 | 诸神愚戏 | 一月九十秋 | 悬疑+骗局 |

### 分类列表（API 获取）

女频悬疑、西方奇幻、东方仙侠、古风世情、科幻末世、男频衍生、女频衍生、民国言情等。
