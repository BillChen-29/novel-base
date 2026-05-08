# 小说节奏分析工作流

> 从已下载的番茄小说中提取节奏数据，填充 pacing_template/ 通用层。

## 触发条件

用户说"分析节奏""解析pacing""节奏模板"等，且有已下载的小说文件（txt/epub）。

## 数据源差异

| 格式 | 对话引号 | 来源 | 适用分析 |
|------|---------|------|---------|
| TXT（TomatoNovelDownloader） | ❌ 被去除 | 番茄下载器 | 钩子率、爽点、情绪密度、字数 |
| EPUB（z-library等） | ✅ 保留 | 出版社原版 | 以上 + 对话比例 |

**关键 pitfall**：TXT 文件中 `""「」` 全部被下载器去除，对话比例分析结果为零。需要对话数据时必须用 EPUB。

## 分析维度

| 维度 | 指标 | 检测方法 |
|------|------|---------|
| **章节字数** | 章均字数、标准差、范围 | `len(content)` |
| **钩子率** | 有钩子的章节占比 | 检查章末最后3段 |
| **钩子类型** | question/ellipsis/reversal/cliffhanger/reveal/upgrade/suspense | 关键词匹配 |
| **爽点分布** | reveal/power_up/upgrade/face_slap/counterattack | 全文关键词计数 |
| **对话比例** | 对话字符/总字符（仅EPUB） | 正则 `"\u201C[^\u201D]*\u201D"` |
| **情绪密度** | 感叹号/问号/省略号 每章 | `count('！')` 等 |

## 钩子检测规则

检查章末最后一段（非空行），匹配以下模式：

```python
hooks = []
if '？' in last_line: hooks.append('question')
if '……' in last_line: hooks.append('ellipsis')
if any(w in last_line for w in ['但是','然而','却','竟然','没想到','突然','不过']): hooks.append('reversal')
if any(w in last_line for w in ['危险','危机','死亡','毁灭','完蛋']): hooks.append('cliffhanger')
if any(w in last_line for w in ['真相','秘密','原来','竟然是','发现','揭露']): hooks.append('reveal')
if any(w in last_line for w in ['突破','升级','觉醒','获得','解锁','进化','提升']): hooks.append('upgrade')
if any(w in last_line for w in ['难道','莫非','究竟','到底','怎么可能']): hooks.append('suspense')
```

## 爽点检测规则

全文章内匹配（cap 每类每章最多3次）：

```python
satisfaction_keywords = {
    'upgrade': ['突破','升级','觉醒','获得','解锁','进化','提升','加点'],
    'face_slap': ['打脸','嘲笑','瞧不起','看扁','不屑','轻视','不自量力'],
    'reveal': ['真相','秘密','原来','竟然是','发现','揭露','居然'],
    'counterattack': ['逆袭','反杀','翻盘','反击'],
    'power_up': ['力量','实力','能力','技能','天赋','血脉','境界','修为'],
}
```

## 章节分割方法

### TXT（TomatoNovelDownloader 格式）
用 `----------------------------------------` 分隔符分割：
```python
chunks = content.split('----------------------------------------')
# chunks[0] 是元数据，chunks[1:] 是章节
```

### EPUB
按文档片段分割，匹配 `第(\d+)章` 模式：
```python
for item in book.get_items():
    if item.get_type() == ebooklib.ITEM_DOCUMENT:
        text = BeautifulSoup(item.get_content(), 'html.parser').get_text(separator='\n')
        ch_match = re.match(r'第(\d+)章\s*(.*)', text)
```

## 分析策略

### 增量分析（推荐）
- 每本分析前 50 章（约半卷）
- 到没有新发现时停止（连续10章无新维度 → 停止）
- 新书分析时直接对照已有数据做横向对比

### 逐章输出格式
```
章  字数  对话%  ！  ？  …  钩子          爽点
 1  2373  13.0  18   4   3       -  power_up,upgrade
```

### 每10章汇总
```
 1-10章 | 2439字 | 对话23.1% | 钩0%   | ！18.3
```

## 输出文件

分析结果写入 `pacing_template/real-data-pacing-benchmark.md`，格式为可迭代的 living document：
- 每个榜单一个详情章节
- 跨榜对比表格
- 核心发现
- 数据更新日志（追加新数据时更新日期和内容）

## 已有数据概览（2026-05-07）

12本番茄小说，三个榜单：
- **推荐榜**（3本TXT）：钩子率34%，question主导，章均2355字
- **新书榜**（5本TXT）：钩子率33%，question主导，章均2610字
- **巅峰榜**（4本EPUB）：钩子率0-34%无标准，四种模式，章均2516字

跨榜唯一共性：reveal + power_up 是爽点双引擎（占70%+）。

详见 `pacing_template/real-data-pacing-benchmark.md`。
