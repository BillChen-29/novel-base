#!/usr/bin/env python3
"""Execute authored, source-bound motif conditions on imported fact reviews.

This is a deterministic experiment, not automatic motif extraction or a writing
model. Exact claim templates prevent relabelling an unrelated supported fact as a
condition. Semantic judgments still come from the separately supplied review.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
from pathlib import Path
from string import Formatter
import sys

from narrative_prototype import _asset_path
from semantic_review import apply_review, _digest, _read_json, _validate_evidence

KINDS = {'content', 'carrier', 'acquisition_event', 'communication_event', 'world_state'}
EVENT_KINDS = {'acquisition_event', 'communication_event'}
KNOWLEDGE_KINDS = {'motif', 'technique', 'situation'}
STAGE_MODES = {'progression', 'alternatives'}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, label):
    _require(isinstance(value, str) and bool(value.strip()), 'invalid_' + label)
    return value


def _objects(value, label):
    _require(isinstance(value, list) and all(isinstance(x, dict) for x in value), 'invalid_' + label)
    return value


def _indexed(value, label):
    result = {}
    for item in _objects(value, label):
        ident = _text(item.get('id'), label + '_id')
        _require(ident not in result, 'duplicate_' + label + '_id')
        result[ident] = item
    return result


def _refs(value, known, label):
    _require(isinstance(value, list), 'invalid_' + label)
    for ref in value:
        _text(ref, label)
    _require(len(set(value)) == len(value) and set(value) <= set(known), 'invalid_' + label)
    return value


def _validate_catalog(catalog, repo_root):
    _require(isinstance(catalog, dict) and type(catalog.get('schema_version')) is int
             and catalog['schema_version'] == 1, 'invalid_catalog_schema')
    _require(catalog.get('status') == 'experimental_operationalization', 'invalid_catalog_status')
    motifs = _indexed(catalog.get('motifs'), 'motifs')
    for motif in motifs.values():
        _text(motif.get('title'), 'motif_title')
        knowledge_kind = motif.get('knowledge_kind', 'motif')
        _require(isinstance(knowledge_kind, str) and knowledge_kind in KNOWLEDGE_KINDS,
                 'invalid_knowledge_kind')
        stage_mode = motif.get('stage_mode', 'progression')
        _require(isinstance(stage_mode, str) and stage_mode in STAGE_MODES,
                 'invalid_stage_mode')
        source = motif.get('source')
        _require(isinstance(source, dict), 'invalid_motif_source')
        path = _asset_path(Path(repo_root), source.get('path'))
        raw = path.read_bytes()
        _require(hashlib.sha256(raw).hexdigest() == source.get('sha256'), 'source_hash_mismatch')
        text = raw.decode('utf-8')
        evidence = _objects(source.get('evidence'), 'source_evidence')
        _require(bool(evidence), 'source_evidence_required')
        for ref in evidence:
            start, end = ref.get('start'), ref.get('end')
            _require(type(start) is int and type(end) is int and 0 <= start < end <= len(text),
                     'invalid_source_span')
            _require(text[start:end] == _text(ref.get('quote'), 'source_quote'), 'source_quote_mismatch')
        roles = motif.get('roles')
        _require(isinstance(roles, dict), 'invalid_roles')
        for name, kind in roles.items():
            _text(name, 'role_name')
            _require(name.isidentifier() and kind in ('character', 'object'), 'invalid_role')
        conditions = _indexed(motif.get('conditions'), 'conditions')
        _require(bool(conditions), 'conditions_required')
        for condition in conditions.values():
            template = _text(condition.get('claim_template'), 'claim_template')
            _require(isinstance(condition.get('kind'), str) and condition['kind'] in KINDS,
                     'invalid_condition_kind')
            try:
                fields = list(Formatter().parse(template))
            except ValueError as error:
                raise ValueError('invalid_claim_template') from error
            for _, field, spec, conversion in fields:
                _require(field is None or field in roles and not spec and conversion is None,
                         'invalid_template_role')
        _refs(motif.get('entry_conditions'), conditions, 'entry_conditions')
        stages = _indexed(motif.get('stages'), 'stages')
        _require(bool(stages), 'stages_required')
        for stage in stages.values():
            _text(stage.get('title'), 'stage_title')
            required = _refs(stage.get('requires'), conditions, 'stage_requires')
            _require(bool(required), 'stage_requires_empty')
            chronological = _refs(stage.get('chronological'), required, 'chronological')
            _require(all(conditions[x]['kind'] in EVENT_KINDS for x in chronological),
                     'chronology_requires_event_conditions')
        for variant in _indexed(motif.get('variants'), 'variants').values():
            _text(variant.get('title'), 'variant_title')
            _text(variant.get('proposal'), 'variant_proposal')
            _require(isinstance(variant.get('from_stage'), str) and variant['from_stage'] in stages,
                     'invalid_variant_stage')
            _refs(variant.get('requires'), conditions, 'variant_requires')
    return motifs


def _state(decision, world=False):
    if not decision or world and decision.get('epistemic_type') != 'established':
        return 'unknown'
    return {'supported': 'true', 'contradicted': 'false'}.get(decision.get('verdict'), 'unknown')


def _status(states):
    return 'blocked' if 'false' in states else 'needs_evidence' if 'unknown' in states else 'eligible'


def _chronology_metadata(review, packet, atom_kinds):
    """Validate imported occurrence judgments; candidate quotes are not clocks."""
    sources = {s['id']: s for s in packet['scenes']}
    verdict = 'insufficient_evidence'
    if 'chronology_review' in review:
        sequence = review['chronology_review']
        _require(isinstance(sequence, dict), 'invalid_chronology_review')
        verdict = sequence.get('verdict')
        _require(isinstance(verdict, str) and verdict in
                 ('supported', 'contradicted', 'insufficient_evidence'), 'invalid_chronology_verdict')
        _require(sequence.get('relation') == 'forward_occurrence', 'invalid_chronology_relation')
        _require(sequence.get('scene_ids') == [s['id'] for s in packet['scenes']],
                 'chronology_scene_binding_mismatch')
        _text(sequence.get('reason'), 'chronology_reason')
    anchors = {}
    for decision in review['decisions']:
        if 'event_anchor' not in decision:
            continue
        _require(decision['verdict'] == 'supported' and decision['epistemic_type'] == 'established'
                 and atom_kinds.get(decision['fact_id']) in EVENT_KINDS, 'invalid_event_anchor_state')
        anchor = decision['event_anchor']
        _require(isinstance(anchor, dict) and anchor.get('relation') == 'occurs_here',
                 'invalid_event_anchor_relation')
        checked = _validate_evidence([anchor], 'supported', sources)[0]
        evidence = _validate_evidence(decision['evidence'], 'supported', sources)
        _require(checked in evidence, 'anchor_not_review_evidence')
        anchors[decision['fact_id']] = checked
    return verdict, anchors


def _anchor_order(ordered, anchors, scene_order):
    relations = []
    for first, second in zip(ordered, ordered[1:]):
        left, right = anchors[first['fact_id']], anchors[second['fact_id']]
        left_scene, right_scene = scene_order[left['scene_id']], scene_order[right['scene_id']]
        if left_scene < right_scene or left_scene == right_scene and left['end'] <= right['start']:
            relations.append('supported')
        elif left_scene > right_scene or left_scene == right_scene and right['end'] <= left['start']:
            relations.append('contradicted')
        else:
            relations.append('unknown')
    return 'contradicted' if 'contradicted' in relations else 'unknown' if 'unknown' in relations else 'supported'


def _stage_results(motif, conditions, anchors, scene_order, sequence_verdict, mode):
    results = []
    for stage in motif['stages']:
        required = list(dict.fromkeys(motif['entry_conditions'] + stage['requires']))
        status = _status([conditions[c][mode] for c in required])
        order_state = 'not_required'
        if stage['chronological']:
            ordered = [conditions[c] for c in stage['chronological']]
            if status != 'eligible':
                order_state = 'unknown'
            elif sequence_verdict == 'contradicted':
                order_state = 'contradicted'
            elif sequence_verdict != 'supported' or any(c['fact_id'] not in anchors for c in ordered):
                order_state = 'unknown'
            else:
                order_state = _anchor_order(ordered, anchors, scene_order)
            if order_state == 'contradicted':
                status = 'blocked'
            elif order_state == 'unknown' and status == 'eligible':
                status = 'needs_evidence'
        results.append({'id': stage['id'], 'title': stage['title'], 'status': status,
                        'chronology': order_state})
    supported = [s['id'] for s in results if s['status'] == 'eligible']
    current = supported[-1] if supported and motif.get('stage_mode', 'progression') == 'progression' else None
    return results, current


def match_motifs(project, packet, review, catalog, repo_root):
    """Return author-only diagnostics and a separately filtered POV writing packet.

    Template/role labels are authored operationalizations. The imported review
    evaluates each exact instantiated proposition. Chronology applies only to
    explicitly reviewed occurrence anchors and a prefix-bound sequence review.
    """
    reviewed = apply_review(project, packet, review)
    motifs = _validate_catalog(catalog, repo_root)
    annotations = project.get('motif_annotations')
    _require(isinstance(annotations, dict), 'invalid_motif_annotations')
    _require(annotations.get('catalog_sha256') == _digest(catalog), 'catalog_binding_mismatch')
    all_facts = {f['id']: f for f in project['facts']}
    candidates = {c['fact_id']: c for c in packet['candidates']}
    decisions = {d['fact_id']: d for d in review['decisions']}
    scene_order = {s['id']: s['order'] for s in packet['scenes']}
    pov = project['pov_character']
    characters = project['characters']

    def states(fact_id):
        decision = decisions.get(fact_id) if fact_id in candidates else None
        knowledge = {x['character_id']: x for x in decision['knowledge']} if decision else {}
        return _state(decision, world=True), {c: _state(knowledge.get(c)) for c in characters}

    atom_view, atom_kinds = [], {}
    for atom in _objects(annotations.get('atoms'), 'atoms'):
        fact_id = _text(atom.get('fact_id'), 'atom_fact_id')
        _require(fact_id in all_facts and fact_id not in atom_kinds, 'unknown_or_duplicate_atom')
        kind = atom.get('kind')
        _require(isinstance(kind, str) and kind in KINDS, 'invalid_atom_kind')
        atom_kinds[fact_id] = kind
        if fact_id in candidates:
            world, knowledge = states(fact_id)
            atom_view.append({'fact_id': fact_id, 'kind': kind, 'text': candidates[fact_id]['text'],
                              'world': world, 'knowledge': knowledge})

    sequence_verdict, anchors = _chronology_metadata(review, packet, atom_kinds)

    audit, variants = [], []
    for instance in _indexed(annotations.get('instances'), 'instances').values():
        motif_id = _text(instance.get('motif_id'), 'instance_motif_id')
        _require(motif_id in motifs, 'unknown_motif')
        motif = motifs[motif_id]
        bindings = instance.get('bindings')
        _require(isinstance(bindings, dict) and set(bindings) == set(motif['roles']), 'invalid_role_bindings')
        for name, role_kind in motif['roles'].items():
            value = _text(bindings[name], 'role_binding')
            _require(role_kind != 'character' or value in characters, 'unknown_role_character')
        mapping = instance.get('condition_facts')
        condition_defs = {c['id']: c for c in motif['conditions']}
        _require(isinstance(mapping, dict) and set(mapping) <= set(condition_defs), 'invalid_condition_mapping')
        for cond_id, fact_id in mapping.items():
            _text(fact_id, 'condition_fact_id')
            _require(fact_id in all_facts, 'unknown_condition_fact')
            definition = condition_defs[cond_id]
            expected = definition['claim_template'].format(**bindings)
            _require(all_facts[fact_id]['text'] == expected, 'condition_claim_mismatch:' + cond_id)
            _require(atom_kinds.get(fact_id) == definition['kind'], 'condition_atom_kind_mismatch')
        conditions = {}
        for cond_id in condition_defs:
            fact_id = mapping.get(cond_id)
            visible_id = fact_id if fact_id in candidates else None
            world, knowledge = states(visible_id)
            # Only affirmative, established knowledge can affect a POV plan.
            # The raw knowledge verdict remains available in author-only audit.
            usable = 'true' if world == 'true' and knowledge[pov] == 'true' else 'unknown'
            conditions[cond_id] = {'id': cond_id, 'fact_id': visible_id,
                'question': condition_defs[cond_id]['claim_template'].format(**bindings),
                'claim': candidates[visible_id]['text'] if visible_id else None,
                'world': world, 'knowledge': knowledge, 'pov': usable}
        author_stages, author_current = _stage_results(motif, conditions, anchors, scene_order, sequence_verdict, 'world')
        pov_stages, pov_current = _stage_results(motif, conditions, anchors, scene_order, sequence_verdict, 'pov')
        progression = motif.get('stage_mode', 'progression') == 'progression'
        supported_stages = [s['id'] for s in author_stages if s['status'] == 'eligible']
        applicability = ('eligible' if supported_stages else 'needs_evidence'
                         if any(s['status'] == 'needs_evidence' for s in author_stages) else 'blocked')
        usable_stages = ({pov_current} if progression else
                         {s['id'] for s in pov_stages if s['status'] == 'eligible'})
        current_index = next((i for i, s in enumerate(motif['stages']) if s['id'] == pov_current), -1)
        # A later event can be known to have happened even when its order is
        # unresolved. Do not respond by proposing to perform it again. Only
        # POV-usable facts participate; hidden progress cannot affect this gate.
        # Alternative operations have no cross-branch temporal priority. Their
        # own chronology checks still gate each branch independently.
        progress_uncertain = progression and any(
            all(conditions[c]['pov'] == 'true' for c in motif['entry_conditions'] + stage['requires'])
            and pov_stages[index]['chronology'] in ('unknown', 'contradicted')
            for index, stage in enumerate(motif['stages']) if index > current_index)
        audit.append({'instance_id': instance['id'], 'motif_id': motif_id, 'title': motif['title'],
            'knowledge_kind': motif.get('knowledge_kind', 'motif'),
            'entry_status': _status([conditions[c]['world'] for c in motif['entry_conditions']]),
            'applicability_status': applicability,
            'supported_stage_ids': supported_stages,
            'supported_condition_ids': [cid for cid,c in conditions.items() if c['world']=='true'],
            'unknown_condition_ids': [cid for cid,c in conditions.items() if c['world']=='unknown'],
            'contradicted_condition_ids': [cid for cid,c in conditions.items() if c['world']=='false'],
            'conditions': list(conditions.values()), 'stages': author_stages, 'current_stage': author_current,
            'pov_progress_uncertain': progress_uncertain})
        for variant in motif['variants']:
            if progress_uncertain or variant['from_stage'] not in usable_stages:
                continue
            stage = next(s for s in motif['stages'] if s['id'] == variant['from_stage'])
            needed = list(dict.fromkeys(motif['entry_conditions'] + stage['requires'] + variant['requires']))
            if not all(conditions[c]['pov'] == 'true' for c in needed):
                continue
            fact_ids = list(dict.fromkeys(conditions[c]['fact_id'] for c in needed))
            # Never serialize instance IDs, role bindings, source excerpts or
            # diagnostic text into the writing packet: they can encode secrets.
            variants.append({'id': variant['id'], 'title': variant['title'], 'stage': stage['id'],
                             'knowledge_kind': motif.get('knowledge_kind', 'motif'),
                             'proposal': variant['proposal'], 'status': 'creative_proposal',
                             'evidence_fact_ids': fact_ids})
    used = {ident for variant in variants for ident in variant['evidence_fact_ids']}
    safe_facts = [{'id': f['id'], 'text': f['text'], 'scene_id': f['scene_id']}
                  for f in reviewed['project']['facts'] if f['id'] in used and pov in f['known_by']]
    packet_out = {'facts': safe_facts, 'proposals': variants}
    pov_facts = [{'id': f['id'], 'text': f['text'], 'scene_id': f['scene_id']}
                 for f in reviewed['project']['facts'] if pov in f['known_by']]
    return {'schema_version': 1, 'project_id': packet['project_id'],
        'mode': 'reviewed-explicit-motif-conditions',
        'provenance': {'project_sha256': packet['project_sha256'], 'packet_sha256': packet['packet_sha256'],
            'review_sha256': reviewed['audit']['review_sha256'], 'catalog_sha256': _digest(catalog),
            'cutoff': copy.deepcopy(packet['cutoff'])},
        'annotation_origin': '来源条目由当前研究者操作化；条件命题经导入审核，程序执行显式规则。',
        'atom_view': atom_view, 'author_audit': audit,
        'pov_view': {'facts': pov_facts, 'variants': copy.deepcopy(variants)},
        'writer_packet': packet_out,
        'writer_prompt': ('以下仅含当前视角已审核事实与可选创作提案。提案尚未发生，不得写回既有记忆。\n'
                          + json.dumps(packet_out, ensure_ascii=False, indent=2)),
        'limitations': ['母题条件、角色槽位和原子分类是本轮标注，不是自动语义抽取。',
            '未知不等于否定；角色知情判断不能证明未经确认的世界命题。',
            '次序依据独立审核的事件发生锚点与顺叙判断；旧候选引用、计划或回忆位置不作为事件发生时间。',
            'progression 模式的当前阶段是所选操作化阶段中最后一个证据完整者，不宣称覆盖整个母题。',
            'progression 模式中，视角已知更后面的事件但次序尚未确认时暂停承接，避免重复已发生的行动。',
            'alternatives 模式按各分支自身条件与次序审核，不以分支列表位置表示时间或优先级。',
            '作者审计可能含视角人物不知道的事实；写作只能使用 writer_packet。']}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ('project', 'packet', 'review', 'catalog'):
        parser.add_argument('--' + flag, required=True, type=Path)
    parser.add_argument('--repo-root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args(argv)
    try:
        result = match_motifs(*[_read_json(getattr(args, name)) for name in ('project', 'packet', 'review', 'catalog')],
                              args.repo_root)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, OSError, UnicodeError) as error:
        print(json.dumps({'ok': False, 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
