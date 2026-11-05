"""Portable HTML view of executed narrative recommendation results."""

from __future__ import annotations

import html
import json
from typing import Any


def _escape(value: Any) -> str:
    return html.escape(str(value), quote=True)


def _json(value: Any) -> str:
    return _escape(json.dumps(value, ensure_ascii=False, indent=2))


def _list(values: list) -> str:
    return '<ul>' + ''.join('<li>' + _escape(v) + '</li>' for v in values) + '</ul>'


def _sources(refs: list) -> str:
    parts = []
    for ref in refs:
        if not isinstance(ref, dict):
            parts.append('<p class="path">' + _escape(ref) + '</p>')
            continue
        parts.append(
            '<div class="source"><strong>' + _escape(ref.get('title', '来源'))
            + '</strong><div class="path">' + _escape(ref.get('path', ''))
            + '</div><blockquote>' + _escape(ref.get('excerpt', ''))
            + '</blockquote><span class="hash">SHA-256 '
            + _escape(ref.get('sha256', '')) + '</span></div>'
        )
    return ''.join(parts)


def _count(summary: dict, key: str) -> str:
    value = summary.get(key, 0)
    if isinstance(value, dict):
        value = value.get('count', value.get('files', 0))
    return _escape(value)


def _plan(plan: dict, number: int) -> str:
    evidence = ', '.join(str(x) for x in plan.get('evidence_fact_ids', [])) or '暂无'
    return (
        '<article class="plan"><div class="plan-top"><span class="eyebrow">建议 '
        + str(number).zfill(2) + '</span><span class="score">规则优先级 '
        + _escape(plan.get('score', 0)) + '</span></div><h3>'
        + _escape(plan.get('title', '候选计划')) + '</h3><p class="effect">'
        + _escape(plan.get('expected_effect', '')) + '</p><h4>为什么现在适合</h4>'
        + _list(plan.get('reasons', [])) + '<h4>下一场戏可以这样安排</h4><ol class="beats">'
        + ''.join('<li>' + _escape(v) + '</li>' for v in plan.get('beats', []))
        + '</ol><p class="note">以上为待作者确认的计划，尚未成为故事事实。</p>'
        + '<details><summary>查看事实锚点与评分依据</summary><p class="path">'
        + _escape(evidence) + '</p><pre>' + _json(plan.get('score_breakdown', {}))
        + '</pre></details><details><summary>查看实际读取的技巧与节奏资料</summary>'
        + _sources(plan.get('source_refs', [])) + '</details></article>'
    )


def _rhythm(state: dict) -> str:
    scenes = state.get('recent_scenes', [])
    bars = []
    for scene in scenes:
        if not isinstance(scene, dict):
            continue
        value = scene.get('tension', 0)
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            value = 0
        level = max(0, min(5, value))
        bars.append(
            '<div class="bar-unit"><span class="bar-value">' + _escape(value)
            + '</span><div class="bar-track"><div class="bar" style="height:'
            + str(int(level * 20)) + '%"></div></div><span class="bar-label">'
            + _escape(scene.get('id', '')) + '</span><small>'
            + _escape(scene.get('function', '')) + '</small></div>'
        )
    return '<div class="rhythm">' + ''.join(bars) + '</div>'


def _panel(report: dict, index: int, selected: bool) -> str:
    state = report.get('story_state', {})
    goal = state.get('goal', {})
    if not isinstance(goal, dict):
        goal = {'description': goal}
    summary = report.get('catalog_summary', {})
    recommendations = report.get('recommendations', [])
    rejected = report.get('rejected', [])
    retrieval = report.get('retrieval', {})
    known = state.get('known_fact_ids', [])
    unknown = state.get('unknown_fact_ids', [])
    plans = ''.join(_plan(p, i + 1) for i, p in enumerate(recommendations))
    if not plans:
        plans = '<div class="empty">当前没有满足前提的计划。请先补充视角人物已知的事实及来源。</div>'
    blocked = ''.join(
        '<div class="blocked"><strong>' + _escape(r.get('title', r.get('id', '')))
        + '</strong>' + _list(r.get('reasons', [])) + '</div>' for r in rejected
    ) or '<p class="note">本次没有因前提不足被挡住的策略。</p>'
    materials = retrieval.get('knowledge', [])
    material_html = _sources(materials) if materials else '<p class="note">本次没有词面匹配的创作素材。</p>'
    facts = retrieval.get('story', [])
    fact_html = ''.join(
        '<div class="fact"><span class="path">'
        + _escape(f.get('fact_id', f.get('id', ''))) + ' · '
        + _escape(f.get('scene_id', '')) + '</span><p>'
        + _escape(f.get('text', '')) + '</p><blockquote>'
        + _escape(f.get('quote', '')) + '</blockquote></div>'
        for f in facts if isinstance(f, dict)
    ) or '<p class="note">暂无可用的事实检索结果。</p>'
    return (
        '<section class="result-panel" id="variant-' + str(index) + '"'
        + ('' if selected else ' hidden') + '><div class="intent"><span>本次作者目标</span><p>'
        + _escape(goal.get('description', '')) + '</p></div>'
        + '<div class="flow"><div><span class="step">01</span><strong>故事记忆</strong><p>'
        + _escape(state.get('scene_count', 0)) + ' 个场景 · ' + str(len(known))
        + ' 条视角人物已知事实</p></div><div><span class="step">02</span><strong>创作素材</strong><p>'
        + _count(summary, 'creative') + ' 份母题、角色与风格资料</p></div>'
        + '<div><span class="step">03</span><strong>推荐知识</strong><p>'
        + _count(summary, 'recommendation') + ' 份技法、节奏与场景资料</p></div>'
        + '<div><span class="step">04</span><strong>推荐模块</strong><p>'
        + str(len(recommendations)) + ' 个候选 · ' + str(len(rejected)) + ' 个策略受限</p></div></div>'
        + '<div class="columns"><main><div class="section-title"><h2>下一场戏的候选计划</h2>'
        + '<span>先检查前提，再解释排序</span></div>' + plans
        + '<details class="wide-detail"><summary>创作素材层实际找到了什么</summary>'
        + '<p class="note">这些是供选择的母题、角色与风格参考，不代表本书已经发生的事实。</p>'
        + material_html + '</details><details class="wide-detail"><summary>查看最终写作输入包</summary>'
        + '<p class="note">这个输入包由推荐结果实际组装；当前版本在此结束，尚未调用写作模型。</p>'
        + '<pre>' + _escape(report.get('writer_prompt', '')) + '</pre></details>'
        + '<details class="wide-detail"><summary>查看各数据层的运行记录</summary><pre>'
        + _json(report.get('trace', [])) + '</pre></details></main>'
        + '<aside><section class="side-card"><span class="eyebrow">当前故事状态</span><h3>从前文出发</h3>'
        + '<dl><div><dt>视角人物</dt><dd>' + _escape(state.get('pov_character', ''))
        + '</dd></div><div><dt>人物已知事实</dt><dd>' + str(len(known))
        + ' 条</dd></div><div><dt>未进入人物知识的事实</dt><dd>' + str(len(unknown))
        + ' 条</dd></div></dl><h4>最近场景的标注强度</h4>' + _rhythm(state)
        + '<p class="note">1–5 为样例中人工标注的相对强度，用于观察顺序变化。</p></section>'
        + '<section class="side-card"><span class="eyebrow">前提检查</span><h3>为什么有些方案不能用</h3>'
        + blocked + '</section><section class="side-card"><span class="eyebrow">前文证据</span>'
        + '<h3>本次取回的已知事实</h3>' + fact_html + '</section></aside></div></section>'
    )


def render_report(report: dict, comparisons: list[dict] | None = None) -> str:
    """Render only executed results; browser controls switch precomputed inputs."""
    variants = comparisons or [{'label': '当前目标', 'report': report}]
    goal = report.get('story_state', {}).get('goal', {})
    goal_id = goal.get('id') if isinstance(goal, dict) else None
    active = 0
    for i, variant in enumerate(variants):
        other = variant['report'].get('story_state', {}).get('goal', {})
        if isinstance(other, dict) and other.get('id') == goal_id:
            active = i
            break
    buttons = ''.join(
        '<button type="button" class="goal-button' + (' active' if i == active else '')
        + '" data-variant="' + str(i) + '" aria-pressed="'
        + ('true' if i == active else 'false') + '">' + _escape(v.get('label', '目标'))
        + '</button>' for i, v in enumerate(variants)
    )
    panels = ''.join(_panel(v['report'], i, i == active) for i, v in enumerate(variants))
    title = _escape(report.get('title', 'Novel Base 推荐原型'))
    return '''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>''' + title + ''' · Novel Base 推荐原型</title>
<style>
:root{--bg:#f5f3ed;--paper:#fffefa;--ink:#182e40;--muted:#697780;--line:#dedfd7;--accent:#255b72;--soft:#e9f0ef;--amber:#8f5c30}
*{box-sizing:border-box}body{margin:0;color:var(--ink);background:var(--bg);font-family:-apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif;font-size:15px;line-height:1.75}button{font:inherit}header,.page,footer{max-width:1260px;margin:auto;padding:0 36px}header{height:82px;display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid var(--line)}.brand{font-weight:750;letter-spacing:.15em;font-size:14px}.mode{font-size:12px;border:1px solid var(--line);padding:4px 12px;border-radius:30px}.hero{padding:42px 0 26px}.eyebrow{color:var(--accent);font-size:11px;letter-spacing:.11em;font-weight:700}.hero h1{font-family:Georgia,"Songti SC",serif;font-size:38px;font-weight:600;letter-spacing:.02em;line-height:1.3;margin:12px 0}.hero p{margin:8px 0;color:var(--muted)}.project-title{font-size:17px;color:var(--ink)!important}.switcher{display:flex;gap:9px;flex-wrap:wrap}.goal-button{border:1px solid var(--line);border-radius:8px;background:var(--paper);padding:10px 18px;cursor:pointer;color:var(--ink)}.goal-button:hover{border-color:var(--accent)}.goal-button.active{background:var(--ink);color:white;border-color:var(--ink)}button:focus-visible,summary:focus-visible{outline:3px solid #e1ac64;outline-offset:3px}.switch-hint{font-size:12px;color:var(--muted);margin:9px 0 20px}.intent{border-left:3px solid var(--accent);padding:8px 18px;margin:20px 0;background:var(--soft)}.intent span{font-size:11px;color:var(--accent);font-weight:650}.intent p{margin:3px 0}.flow{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:10px;overflow:hidden;margin:24px 0 38px}.flow>div{padding:17px 18px;background:var(--paper)}.flow strong{font-size:15px}.flow p{font-size:12px;color:var(--muted);margin:5px 0 0}.step{font-family:Georgia,serif;font-size:17px;color:#819595;margin-right:10px}.columns{display:grid;grid-template-columns:minmax(0,1fr) 340px;gap:26px}.columns main,.columns aside{min-width:0}.section-title{display:flex;justify-content:space-between;align-items:center;margin-bottom:15px}.section-title h2{font-size:21px;margin:0}.section-title>span{font-size:11px;color:var(--muted)}.plan,.side-card{background:var(--paper);border:1px solid var(--line);border-radius:10px;padding:24px;margin-bottom:18px}.plan:first-of-type{border-top:3px solid var(--accent)}.plan-top{display:flex;justify-content:space-between;align-items:center;gap:12px}.score{font-size:11px;background:var(--soft);color:var(--accent);padding:3px 9px;border-radius:20px}.plan h3{font-size:22px;margin:10px 0 6px;line-height:1.5}.effect{color:var(--muted);font-size:13px;margin:0 0 18px}h4{font-size:13px;margin:19px 0 7px}ul,ol{padding-left:21px;margin:7px 0}li{margin-bottom:7px}.beats li{padding-left:4px}.note{font-size:11px;color:var(--muted);margin:10px 0;line-height:1.7}details{border-top:1px solid var(--line);margin-top:15px;padding-top:11px}summary{cursor:pointer;font-size:12px;color:var(--accent);font-weight:650}pre{font:11px/1.8 ui-monospace,SFMono-Regular,Menlo,monospace;white-space:pre-wrap;overflow-wrap:anywhere;background:#f1f3ef;border-radius:6px;padding:14px;max-height:480px;overflow:auto}.source{padding:13px 0}.source+.source{border-top:1px dashed var(--line)}.source strong{font-size:13px}.path{font:10px/1.8 ui-monospace,SFMono-Regular,monospace;color:var(--muted);overflow-wrap:anywhere;margin:5px 0}.hash{font-size:9px;color:var(--muted);overflow-wrap:anywhere}blockquote{margin:8px 0;padding:8px 12px;border-left:2px solid #c9d8d7;background:#f4f6f1;font-size:12px;white-space:pre-wrap;overflow-wrap:anywhere}.side-card h3{font-size:18px;margin:7px 0 17px}.side-card dl{font-size:12px;margin:0}.side-card dl div{display:flex;justify-content:space-between;gap:12px;margin:9px 0}.side-card dt{color:var(--muted)}.side-card dd{margin:0}.rhythm{display:flex;gap:12px;margin:14px 0 8px;align-items:flex-end}.bar-unit{flex:1;text-align:center;min-width:0}.bar-value{font-size:12px}.bar-track{height:65px;display:flex;align-items:flex-end;justify-content:center;background:#f0f3ef;border-radius:4px;overflow:hidden}.bar{background:#467788;width:100%;border-radius:4px 4px 0 0}.bar-label{font:10px ui-monospace,monospace}.bar-unit small{display:block;color:var(--muted);font-size:10px}.blocked{border-left:3px solid #c99e69;padding:9px 12px;background:#faf4e9;margin-top:10px;font-size:12px}.blocked strong{color:var(--amber)}.blocked li{margin-bottom:4px}.fact{padding:8px 0;border-top:1px solid var(--line)}.fact p{font-size:12px;margin:5px 0}.wide-detail{padding:17px 20px;background:var(--paper);border:1px solid var(--line);border-radius:8px;margin-bottom:12px}.empty{padding:25px;border:1px dashed var(--line);background:var(--paper);border-radius:10px}footer{border-top:1px solid var(--line);margin-top:45px;padding-top:20px;padding-bottom:30px;font-size:11px;color:var(--muted)}[hidden]{display:none!important}
@media(max-width:920px){.columns{grid-template-columns:minmax(0,1fr) 280px;gap:16px}.plan,.side-card{padding:18px}.flow{grid-template-columns:repeat(2,1fr)}}
@media(max-width:700px){header,.page,footer{padding-left:20px;padding-right:20px}.hero{padding-top:29px}.hero h1{font-size:29px}.columns{display:flex;flex-direction:column}.section-title{display:block}.section-title>span{display:block;margin-top:4px}.goal-button{padding:9px 12px;font-size:12px}.plan h3{font-size:20px}.flow{margin-bottom:25px}}
@media print{body{background:white}.switcher,.switch-hint{display:none}.columns{display:block}.flow{break-inside:avoid}.plan,.side-card{break-inside:avoid}header{height:55px}.hero{padding-top:20px}}
</style></head><body><header><div class="brand">NOVEL BASE <span style="color:#8c999d;font-weight:400">/ LAB 01</span></div><span class="mode">离线推荐原型</span></header>
<div class="page"><section class="hero"><span class="eyebrow">叙事推荐的数据流</span><h1>从故事事实，到下一场戏</h1><p class="project-title">'''+title+'''</p><p>让创作素材、技巧与节奏各司其职，展示每一项建议的依据。</p></section>
<nav class="switcher" aria-label="切换已运行的作者目标">'''+buttons+'''</nav><p class="switch-hint">切换下方已运行的输入结果，比较作者目标如何影响推荐。网页不调用 AI，也不重新生成故事。</p>
'''+panels+'''</div><footer>当前模式：词面检索 + 显式规则。故事状态由作者标注；优先级用于解释排序。原文定位校验不替代事实语义核验。原始资产保持原目录，分层通过索引和策略卡实现。</footer>
<script>
document.querySelectorAll('[data-variant]').forEach(function(button){
  button.addEventListener('click',function(){
    var chosen=button.dataset.variant;
    document.querySelectorAll('.result-panel').forEach(function(panel){panel.hidden=panel.id!=='variant-'+chosen;});
    document.querySelectorAll('[data-variant]').forEach(function(other){var active=other===button;other.classList.toggle('active',active);other.setAttribute('aria-pressed',String(active));});
  });
});
</script></body></html>'''
