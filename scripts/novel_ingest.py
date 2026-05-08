#!/usr/bin/env python3
"""
小说数据库 Ingest 管线 v2
用法:
  python3 novel_ingest.py <file> --type <类型>
  
类型:
  web_novel   网文 → pacing分析 + 基础风格指标
  motif       母题/神话文本 → motif提取
  character   角色原型文本 → character提取
  technique   写作技巧文本 → technique提取
  style       风格参考 → 风格提取
  
选项:
  --type      文本类型（必须）
  --chapters  分析前N章（默认50，仅web_novel/style）
  --mid       同时分析100-150章（仅web_novel）
  --json      输出JSON
  --write     自动写入数据库
  --sync-qmd  写入后自动更新 QMD 索引
  --force     忽略去重，强制重新处理
"""

import re
import os
import sys
import json
import argparse
import statistics
from collections import Counter
from datetime import datetime

# 复用 style_fingerprint 的核心风格提取逻辑
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
from style_fingerprint import collect_metrics

# ============ 配置 ============

ASSETS_DIR = os.path.expanduser("~/.hermes/skills/novel-creator-skill/assets")

TARGETS = {
    'pacing_template': os.path.join(ASSETS_DIR, 'pacing_template'),
    'style_library': os.path.join(ASSETS_DIR, 'style_library'),
    'motif_library': os.path.join(ASSETS_DIR, 'motif_library'),
    'character_archetypes': os.path.join(ASSETS_DIR, 'character_archetypes'),
    'technique_library': os.path.join(ASSETS_DIR, 'technique_library'),
}

MANIFEST_PATH = os.path.join(ASSETS_DIR, 'ingest_manifest.json')

# ingest type → QMD collection 映射
TYPE_TO_COLLECTIONS = {
    'motif': ['motif-library'],
    'character': ['character-archetypes'],
    'technique': ['technique-library'],
    'style': ['style-library'],
    'web_novel': ['pacing-template', 'style-library'],
}

# ============ 文件读取 ============

def read_txt(fp):
    for enc in ['utf-8', 'gbk', 'gb18030', 'latin-1']:
        try:
            with open(fp, 'r', encoding=enc) as f:
                return f.read()
        except:
            continue
    return ""

def read_epub(fp):
    try:
        import ebooklib
        from ebooklib import epub
        from bs4 import BeautifulSoup
    except ImportError:
        print("错误: pip install ebooklib beautifulsoup4", file=sys.stderr)
        sys.exit(1)
    
    book = epub.read_epub(fp)
    meta = {
        'title': book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else '?',
        'author': book.get_metadata('DC', 'creator')[0][0] if book.get_metadata('DC', 'creator') else '?',
        'description': book.get_metadata('DC', 'description')[0][0] if book.get_metadata('DC', 'description') else '',
    }
    
    chapters = []
    for item in book.get_items():
        if item.get_type() == ebooklib.ITEM_DOCUMENT:
            soup = BeautifulSoup(item.get_content(), 'html.parser')
            text = soup.get_text(separator='\n').strip()
            if len(text) < 100:
                continue
            ch_match = re.match(r'第(\d+)章\s*(.*)', text)
            if ch_match:
                num = int(ch_match.group(1))
                title_line = text.split('\n')[0].strip()
                content = '\n'.join(text.split('\n')[1:]).strip()
                chapters.append({
                    'number': num, 'title': title_line,
                    'content': content, 'wc': len(content),
                })
    
    return chapters, meta

def read_txt_chapters(fp):
    content = read_txt(fp)
    if not content:
        return [], {}
    
    meta = {}
    for key, pat in [('title', r'书名[：:](.+)'), ('author', r'作者[：:](.+)'),
                     ('rating', r'评分[：:](\d+\.?\d*)'), ('word_count', r'字数[：:](\d+)'),
                     ('chapter_count', r'章节[：:](\d+)'), ('category', r'分类[：:](.+)'),
                     ('tags', r'标签[：:](.+)'), ('readers', r'在读[：:](.+)')]:
        match = re.search(pat, content)
        if match:
            val = match.group(1).strip()
            if key == 'rating': meta[key] = float(val)
            elif key in ('word_count', 'chapter_count'): meta[key] = int(val)
            elif key == 'tags': meta[key] = [t.strip() for t in val.split('|')]
            else: meta[key] = val
    
    chunks = content.split('----------------------------------------')
    chapters = []
    for i, chunk in enumerate(chunks[1:], 1):
        lines = [l.strip() for l in chunk.split('\n') if l.strip()]
        if not lines:
            continue
        ch_match = re.match(r'第(\d+)章\s*(.*)', lines[0])
        if ch_match:
            num = int(ch_match.group(1))
            ch_title = ch_match.group(2).strip()
            body = '\n'.join(lines[1:])
        else:
            num = i
            ch_title = lines[0][:30]
            body = '\n'.join(lines)
        chapters.append({
            'number': num, 'title': ch_title,
            'content': body, 'wc': len(body),
        })
    
    return chapters, meta

def read_full_text(fp):
    """读取全文（不分章）"""
    ext = os.path.splitext(fp)[1].lower()
    if ext == '.epub':
        try:
            import ebooklib
            from ebooklib import epub
            from bs4 import BeautifulSoup
            book = epub.read_epub(fp)
            meta = {
                'title': book.get_metadata('DC', 'title')[0][0] if book.get_metadata('DC', 'title') else '?',
                'author': book.get_metadata('DC', 'creator')[0][0] if book.get_metadata('DC', 'creator') else '?',
            }
            texts = []
            for item in book.get_items():
                if item.get_type() == ebooklib.ITEM_DOCUMENT:
                    soup = BeautifulSoup(item.get_content(), 'html.parser')
                    t = soup.get_text(separator='\n').strip()
                    if len(t) > 50:
                        texts.append(t)
            return '\n\n'.join(texts), meta
        except:
            return '', {}
    else:
        return read_txt(fp), {}

# ============ 网文分析 ============

WEB_NOVEL_KW = ['系统', '升级', '觉醒', '穿越', '重生', '金手指', '面板', '属性',
                '修为', '境界', '突破', '丹田', '灵石', '功法', '副本', '任务',
                '打脸', '装逼', '逆袭', '废柴', '赘婿', '战神', '龙王']

def analyze_pacing(chapters, max_ch=50):
    batch = [c for c in chapters if 1 <= c['number'] <= max_ch]
    batch.sort(key=lambda x: x['number'])
    
    results = []
    for ch in batch:
        content = ch['content']
        wc = ch['wc']
        paras = [p.strip() for p in content.split('\n') if p.strip()]
        last = paras[-1] if paras else ""
        
        dialogue_segments = re.findall(r'\u201C[^\u201D]*\u201D', content)
        dialogue_chars = sum(len(s) for s in dialogue_segments)
        dr = dialogue_chars / wc * 100 if wc > 0 else 0
        
        hooks = []
        if '？' in last: hooks.append('question')
        if '……' in last: hooks.append('ellipsis')
        if any(w in last for w in ['但是','然而','却','竟然','没想到','突然','不过']): hooks.append('reversal')
        if any(w in last for w in ['危险','危机','死亡','毁灭','完蛋']): hooks.append('cliffhanger')
        if any(w in last for w in ['真相','秘密','原来','竟然是','发现','揭露']): hooks.append('reveal')
        if any(w in last for w in ['突破','升级','觉醒','获得','解锁','进化','提升']): hooks.append('upgrade')
        if any(w in last for w in ['难道','莫非','究竟','到底','怎么可能']): hooks.append('suspense')
        
        satis = []
        for t, kw in [('upgrade',['突破','升级','觉醒','获得','解锁','进化','提升','加点']),
                       ('face_slap',['打脸','嘲笑','瞧不起','看扁','不屑','轻视']),
                       ('reveal',['真相','秘密','原来','竟然是','发现','揭露','居然']),
                       ('counterattack',['逆袭','反杀','翻盘','反击']),
                       ('power_up',['力量','实力','能力','技能','天赋','血脉','境界','修为'])]:
            count = sum(content.count(k) for k in kw)
            if count > 0: satis.extend([t] * min(count, 3))
        
        results.append({
            'wc': wc, 'dr': round(dr, 1), 'hooks': hooks,
            'excl': content.count('！'), 'ques': content.count('？'),
            'ellip': content.count('……'), 'satis': satis,
        })
    
    if not results:
        return None
    
    hook_count = sum(1 for r in results if r['hooks'])
    all_hooks = []
    for r in results: all_hooks.extend(r['hooks'])
    all_satis = []
    for r in results: all_satis.extend(r['satis'])
    
    hr = hook_count / len(results) * 100
    avg_dr = statistics.mean([r['dr'] for r in results])
    avg_ques = statistics.mean([r['ques'] for r in results])
    
    if hr <= 2: mode = 'C'
    elif avg_dr < 10: mode = 'D'
    elif hr >= 20 and avg_ques >= 10: mode = 'B'
    elif hr < 20: mode = 'A'
    else: mode = 'B'
    
    return {
        'count': len(results),
        'avg_wc': round(statistics.mean([r['wc'] for r in results])),
        'std_wc': round(statistics.stdev([r['wc'] for r in results])) if len(results) > 1 else 0,
        'avg_dr': round(avg_dr, 1),
        'hook_rate': round(hook_count / len(results), 3),
        'hook_types': dict(Counter(all_hooks).most_common()),
        'satis_types': dict(Counter(all_satis).most_common()),
        'avg_excl': round(statistics.mean([r['excl'] for r in results]), 1),
        'avg_ques': round(avg_ques, 1),
        'avg_ellip': round(statistics.mean([r['ellip'] for r in results]), 1),
        'mode': mode,
    }

def analyze_style(chapters, max_ch=20):
    """分析章节风格，复用 style_fingerprint.collect_metrics() 提取核心指标。"""
    batch = [c for c in chapters if 1 <= c['number'] <= max_ch]
    batch.sort(key=lambda x: x['number'])
    if not batch:
        return None

    all_text = '\n'.join([ch['content'] for ch in batch])
    total_wc = sum(ch['wc'] for ch in batch)

    # 调用 style_fingerprint 的完整风格提取
    m = collect_metrics(all_text, top_n=12)

    # 将 style_fingerprint 的输出映射为本函数的原有字段格式
    total_cjk = m['total_cjk_chars']

    # 情绪风格（基于感叹号密度，per-1000中文字符）
    excl_per_1k = round(m['punctuation_density'].get('！', 0) * m['sentence_count'] / total_cjk * 1000, 1) if total_cjk > 0 else 0
    ques_per_1k = round(m['punctuation_density'].get('？', 0) * m['sentence_count'] / total_cjk * 1000, 1) if total_cjk > 0 else 0
    ellip_count = all_text.count('……')
    ellip_per_1k = round(ellip_count / total_cjk * 1000, 1) if total_cjk > 0 else 0

    if excl_per_1k > 15:
        emotion_style = '高情绪'
    elif excl_per_1k > 8:
        emotion_style = '中情绪'
    else:
        emotion_style = '低情绪/克制型'

    return {
        'sample_chapters': len(batch), 'total_wc': total_wc,
        'avg_sentence_len': m['avg_sentence_chars'],
        'avg_para_len': m['avg_paragraph_chars'],
        'dialogue_ratio': round(m['dialogue_ratio'] * 100, 1),
        'pov': m['perspective_label'].rstrip('倾向').rstrip('/不显著')
               if '第一' in m['perspective_label'] or '第三' in m['perspective_label']
               else m['perspective_label'],
        'emotion_style': emotion_style,
        'excl_rate': excl_per_1k, 'ques_rate': ques_per_1k,
        'ellip_rate': ellip_per_1k,
    }

# ============ 母题/角色/技巧 提取（输出待LLM处理的文本） ============

def extract_sections_for_llm(fp, section_size=3000):
    """将全文按段落切分为适合LLM处理的块"""
    text, meta = read_full_text(fp)
    if not text:
        return [], meta
    
    # 按双换行分段
    paragraphs = re.split(r'\n\s*\n', text)
    paragraphs = [p.strip() for p in paragraphs if len(p.strip()) > 20]
    
    # 合并为指定大小的块
    sections = []
    current = []
    current_len = 0
    
    for para in paragraphs:
        if current_len + len(para) > section_size and current:
            sections.append('\n\n'.join(current))
            current = [para]
            current_len = len(para)
        else:
            current.append(para)
            current_len += len(para)
    
    if current:
        sections.append('\n\n'.join(current))
    
    return sections, meta

# ============ Manifest（去重+跟踪） ============

def load_manifest():
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {'ingested': []}

def save_manifest(manifest):
    os.makedirs(os.path.dirname(MANIFEST_PATH), exist_ok=True)
    with open(MANIFEST_PATH, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

def is_ingested(fp, text_type):
    """检查是否已入库"""
    manifest = load_manifest()
    basename = os.path.basename(fp)
    for entry in manifest['ingested']:
        if entry['file'] == basename and entry['type'] == text_type:
            return True
    return False

def record_ingest(fp, text_type, results_summary):
    """记录入库"""
    manifest = load_manifest()
    manifest['ingested'].append({
        'file': os.path.basename(fp),
        'type': text_type,
        'time': datetime.now().isoformat(),
        'summary': results_summary,
    })
    save_manifest(manifest)

def sync_qmd(text_type):
    """调用 qmd update + qmd embed 更新指定 collection 的索引。"""
    import subprocess
    collections = TYPE_TO_COLLECTIONS.get(text_type, [])
    if not collections:
        return
    for col in collections:
        try:
            subprocess.run(['qmd', 'update'], capture_output=True, timeout=30)
            subprocess.run(['qmd', 'embed', '-c', col], capture_output=True, timeout=60)
            print(f"  QMD sync: {col} ✓")
        except Exception as e:
            print(f"  QMD sync: {col} ✗ ({e})", file=sys.stderr)

# ============ 报告输出 ============

MODE_NAMES = {
    'A': '低钩子反转/揭秘型',
    'B': '高钩子问号型',
    'C': '零钩子内容驱动型',
    'D': '低对话描写型',
}

def report_web_novel(chapters, meta, fp, max_ch, do_mid):
    title = meta.get('title', os.path.basename(fp))
    author = meta.get('author', '?')
    
    pacing = analyze_pacing(chapters, max_ch)
    style = analyze_style(chapters, min(max_ch, 20))
    
    print(f"\n{'='*60}")
    print(f"📚 网文: {title}")
    print(f"   作者: {author} | 总章数: {len(chapters)}")
    print(f"{'='*60}")
    
    if pacing:
        print(f"\n📊 节奏分析 (前{max_ch}章)")
        print(f"  模式: {pacing['mode']} - {MODE_NAMES.get(pacing['mode'], '?')}")
        print(f"  章均字数: {pacing['avg_wc']} ± {pacing['std_wc']}")
        print(f"  对话比例: {pacing['avg_dr']}%")
        print(f"  钩子率: {pacing['hook_rate']*100:.1f}%")
        print(f"  钩子类型: {pacing['hook_types']}")
        print(f"  爽点分布: {pacing['satis_types']}")
        print(f"  情绪: ！{pacing['avg_excl']}  ？{pacing['avg_ques']}  …{pacing['avg_ellip']}")
    
    if style:
        print(f"\n🎨 风格指标 (前20章)")
        print(f"  叙述视角: {style['pov']}")
        print(f"  情绪风格: {style['emotion_style']}")
        print(f"  句均长度: {style['avg_sentence_len']}字")
        print(f"  段均长度: {style['avg_para_len']}字")
        print(f"  对话比例: {style['dialogue_ratio']}%")
        print(f"  情绪密度: ！{style['excl_rate']}/千字  ？{style['ques_rate']}/千字  …{style['ellip_rate']}/千字")
    
    if do_mid:
        mid_pacing = analyze_pacing(chapters, 150)
        # 只取100-150章
        mid_batch = [c for c in chapters if 100 <= c['number'] <= 150]
        if mid_batch and pacing:
            mid_results = []
            for ch in sorted(mid_batch, key=lambda x: x['number']):
                content = ch['content']
                wc = ch['wc']
                paras = [p.strip() for p in content.split('\n') if p.strip()]
                last = paras[-1] if paras else ""
                hooks = []
                if '？' in last: hooks.append('question')
                if '……' in last: hooks.append('ellipsis')
                if any(w in last for w in ['但是','然而','却','竟然','没想到','突然','不过']): hooks.append('reversal')
                mid_results.append({'wc': wc, 'hooks': hooks})
            
            mid_wc = round(statistics.mean([r['wc'] for r in mid_results]))
            mid_hr = sum(1 for r in mid_results if r['hooks']) / len(mid_results) * 100
            
            print(f"\n📈 中后期对比 (100-150章)")
            print(f"  章均字数: {pacing['avg_wc']} → {mid_wc}")
            print(f"  钩子率: {pacing['hook_rate']*100:.1f}% → {mid_hr:.1f}%")
    
    return {'pacing': pacing, 'style': style}

def report_motif(fp):
    """母题文本：输出章节供LLM提取"""
    sections, meta = extract_sections_for_llm(fp)
    title = meta.get('title', os.path.basename(fp))
    
    print(f"\n{'='*60}")
    print(f"📖 母题文本: {title}")
    print(f"   分为 {len(sections)} 个段落块")
    print(f"{'='*60}")
    print(f"\n需LLM处理。段落块预览:")
    for i, s in enumerate(sections[:3]):
        print(f"\n--- 块 {i+1} (前200字) ---")
        print(s[:200])
    
    return {'sections_count': len(sections), 'title': title}

def report_character(fp):
    """角色文本：输出章节供LLM提取"""
    sections, meta = extract_sections_for_llm(fp)
    title = meta.get('title', os.path.basename(fp))
    
    print(f"\n{'='*60}")
    print(f"👤 角色原型文本: {title}")
    print(f"   分为 {len(sections)} 个段落块")
    print(f"{'='*60}")
    print(f"\n需LLM处理。段落块预览:")
    for i, s in enumerate(sections[:3]):
        print(f"\n--- 块 {i+1} (前200字) ---")
        print(s[:200])
    
    return {'sections_count': len(sections), 'title': title}

def report_technique(fp):
    """技巧文本：输出章节供LLM提取"""
    sections, meta = extract_sections_for_llm(fp)
    title = meta.get('title', os.path.basename(fp))
    
    print(f"\n{'='*60}")
    print(f"✍️ 技巧文本: {title}")
    print(f"   分为 {len(sections)} 个段落块")
    print(f"{'='*60}")
    print(f"\n需LLM处理。段落块预览:")
    for i, s in enumerate(sections[:3]):
        print(f"\n--- 块 {i+1} (前200字) ---")
        print(s[:200])
    
    return {'sections_count': len(sections), 'title': title}

def report_style(chapters, meta, fp, max_ch):
    """风格参考：节奏+风格分析"""
    title = meta.get('title', os.path.basename(fp))
    
    pacing = analyze_pacing(chapters, max_ch)
    style = analyze_style(chapters, max_ch)
    
    print(f"\n{'='*60}")
    print(f"🎨 风格参考: {title}")
    print(f"   总章数: {len(chapters)}")
    print(f"{'='*60}")
    
    if pacing:
        print(f"\n📊 节奏 (前{max_ch}章)")
        print(f"  模式: {pacing['mode']} - {MODE_NAMES.get(pacing['mode'], '?')}")
        print(f"  章均字数: {pacing['avg_wc']} ± {pacing['std_wc']}")
        print(f"  对话比例: {pacing['avg_dr']}%")
        print(f"  钩子率: {pacing['hook_rate']*100:.1f}%")
        print(f"  爽点: {pacing['satis_types']}")
    
    if style:
        print(f"\n🎨 风格 (前{max_ch}章)")
        print(f"  视角: {style['pov']}")
        print(f"  情绪: {style['emotion_style']}")
        print(f"  句均: {style['avg_sentence_len']}字")
        print(f"  对话: {style['dialogue_ratio']}%")
        print(f"  密度: ！{style['excl_rate']}  ？{style['ques_rate']}  …{style['ellip_rate']}")
    
    return {'pacing': pacing, 'style': style}

# ============ 主函数 ============

def main():
    parser = argparse.ArgumentParser(description='小说数据库 Ingest 管线 v2')
    parser.add_argument('file', help='epub或txt文件')
    parser.add_argument('--type', required=True,
                        choices=['web_novel', 'motif', 'character', 'technique', 'style'],
                        help='文本类型')
    parser.add_argument('--chapters', type=int, default=50, help='分析前N章')
    parser.add_argument('--mid', action='store_true', help='同时分析100-150章')
    parser.add_argument('--json', action='store_true', help='输出JSON')
    parser.add_argument('--write', action='store_true', help='自动写入数据库')
    parser.add_argument('--sync-qmd', action='store_true', help='写入后自动更新 QMD 索引')
    parser.add_argument('--force', action='store_true', help='忽略去重，强制重新处理')
    
    args = parser.parse_args()
    
    fp = args.file
    if not os.path.exists(fp):
        print(f"错误: 文件不存在: {fp}", file=sys.stderr)
        sys.exit(1)
    
    # 去重检查
    if not args.force and is_ingested(fp, args.type):
        print(f"跳过: {os.path.basename(fp)} ({args.type}) 已入库。用 --force 强制重新处理。")
        sys.exit(0)
    
    # 读取
    ext = os.path.splitext(fp)[1].lower()
    if args.type in ['web_novel', 'style']:
        if ext == '.epub':
            chapters, meta = read_epub(fp)
        else:
            chapters, meta = read_txt_chapters(fp)
        
        if not chapters:
            print(f"错误: 无章节内容", file=sys.stderr)
            sys.exit(1)
        
        if args.type == 'web_novel':
            results = report_web_novel(chapters, meta, fp, args.chapters, args.mid)
        else:
            results = report_style(chapters, meta, fp, args.chapters)
    else:
        if args.type == 'motif':
            results = report_motif(fp)
        elif args.type == 'character':
            results = report_character(fp)
        elif args.type == 'technique':
            results = report_technique(fp)
    
    # JSON输出
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    
    # 记录
    title = meta.get('title', os.path.basename(fp)) if 'meta' in dir() else os.path.basename(fp)
    record_ingest(fp, args.type, {'title': title})
    
    if args.sync_qmd:
        sync_qmd(args.type)
    
    print(f"\n✅ 已记录到 manifest")

if __name__ == '__main__':
    main()
