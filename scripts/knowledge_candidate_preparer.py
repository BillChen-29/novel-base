#!/usr/bin/env python3
"""Instantiate source-bound knowledge questions for a separately supplied review.

The caller supplies an already permitted story prefix and authored role/context
bindings. Anchors identify review context, never establish that a claim is true.
No model, retrieval service, or canonical memory write occurs here.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys

from narrative_prototype import _validate_project
from motif_matcher import _validate_catalog, _require, _text, _indexed
from semantic_review import prepare_review, _digest, _read_json


def prepare_candidates(project, catalog, instances, repo_root):
    """Return a derived review project; absent anchors stay unbound/unknown.

    ``instances`` is a list of {id, motif_id, bindings, anchors}; each optional
    condition anchor is {scene_id, start, end}, counting Unicode characters in
    the supplied raw scene text. All supplied scenes are allowed; callers must
    truncate/select the desired prefix before invoking this function.
    """
    derived = _validate_project(project)
    _require('motif_annotations' not in derived, 'existing_motif_annotations')
    motifs = _validate_catalog(catalog, repo_root)
    specs = _indexed(instances, 'candidate_instances')
    scenes = {s['id']:s for s in derived['scenes']}
    reserved = {x['id'] for group in ('scenes','facts','threads') for x in derived[group]}
    atoms = [{'fact_id':f['id'],'kind':'world_state'} for f in derived['facts']]
    bound_instances, generated, unbound = [], [], []
    next_id = 1
    for spec in specs.values():
        _require(set(spec) == {'id','motif_id','bindings','anchors'}, 'invalid_candidate_instance_fields')
        motif_id = _text(spec.get('motif_id'), 'motif_id')
        _require(motif_id in motifs, 'unknown_candidate_motif')
        motif = motifs[motif_id]
        bindings = spec.get('bindings')
        _require(isinstance(bindings,dict) and set(bindings)==set(motif['roles']), 'invalid_candidate_bindings')
        for role, kind in motif['roles'].items():
            value = _text(bindings[role], 'candidate_role')
            _require(kind!='character' or value in derived['characters'], 'unknown_candidate_character')
        anchors = spec.get('anchors')
        conditions = {c['id']:c for c in motif['conditions']}
        _require(isinstance(anchors,dict) and set(anchors)<=set(conditions), 'invalid_candidate_anchors')
        mapping = {}
        for condition in motif['conditions']:
            cid = condition['id']
            if cid not in anchors:
                unbound.append({'instance_id':spec['id'],'condition_id':cid,'reason':'no_review_context_bound'})
                continue
            anchor = anchors[cid]
            _require(isinstance(anchor,dict) and set(anchor)=={'scene_id','start','end'}, 'invalid_context_anchor')
            sid = _text(anchor.get('scene_id'), 'context_scene_id')
            _require(sid in scenes, 'context_scene_outside_supplied_prefix')
            start, end = anchor.get('start'), anchor.get('end')
            text = scenes[sid]['text']
            _require(type(start) is int and type(end) is int and 0<=start<end<=len(text), 'invalid_context_span')
            quote = _text(text[start:end], 'context_quote')
            while f'probe_{next_id:04d}' in reserved:
                next_id += 1
            ident = f'probe_{next_id:04d}';next_id += 1;reserved.add(ident)
            fact = {'id':ident,'text':condition['claim_template'].format(**bindings),
                    'scene_id':sid,'quote':quote,'start':start,'end':end,
                    'known_by':copy.deepcopy(derived['characters']),
                    'epistemic_status':'unreviewed_condition_probe'}
            derived['facts'].append(fact)
            atoms.append({'fact_id':ident,'kind':condition['kind']})
            mapping[cid] = ident
            generated.append({'instance_id':spec['id'],'condition_id':cid,'fact_id':ident,
                              'anchor_role':'review_context_not_entailment'})
        bound_instances.append({'id':spec['id'],'motif_id':motif_id,'bindings':copy.deepcopy(bindings),
                                'condition_facts':mapping})
    derived['motif_annotations']={'catalog_sha256':_digest(catalog),'atoms':atoms,'instances':bound_instances}
    derived['annotation_method']='derived_condition_review: anchors are review context, not entailment; known_by lists claims to review, not confirmed knowledge'
    packet = prepare_review(derived)
    return {'project':derived,'packet':packet,'preparation_audit':{
        'source_project_sha256':_digest(project),'derived_project_sha256':packet['project_sha256'],
        'packet_sha256':packet['packet_sha256'],'catalog_sha256':_digest(catalog),
        'generated_probes':generated,'unbound_conditions':unbound,
        'limitations':['全部输入场景均作为允许前文；调用者应先截断正文。',
                       '上下文锚点不证明命题成立；知情者列表是待审核主张，不是已确认知情。',
                       '原有候选的类别暂标为 world_state，并未重新解释其语义；未绑定条件保持未知。',
                       '生成派生审核输入，不修改原项目或正式故事记忆。']}}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    for flag in ('project','catalog','instances'):
        parser.add_argument('--'+flag,required=True,type=Path)
    parser.add_argument('--repo-root',type=Path,default=Path(__file__).resolve().parents[1])
    args=parser.parse_args(argv)
    try:
        result=prepare_candidates(*[_read_json(getattr(args,flag)) for flag in ('project','catalog','instances')],args.repo_root)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0
    except (ValueError,OSError,UnicodeError) as error:
        print(json.dumps({'ok':False,'error':str(error)},ensure_ascii=False),file=sys.stderr)
        return 1


if __name__=='__main__':
    raise SystemExit(main())
