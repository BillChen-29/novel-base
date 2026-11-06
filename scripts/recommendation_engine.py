"""Embeddable, offline recommendation loop using imported semantic judgments.

Functions never write files or call models; catalog validation reads assets.
Review requests contain author context; only a
batch's writer_packet is suitable for a POV writing model. Hashes detect stale
or altered data, not malicious reviewers. No model or filesystem writes here.
"""
from __future__ import annotations

import copy
import re
from string import Formatter

from knowledge_candidate_preparer import prepare_candidates
from motif_matcher import _validate_catalog, match_motifs
from narrative_prototype import _validate_project
from recommendation_session import (validate_session, source_token, canonical_digest,
    install_state, install_batch, accept_proposal)
from recommendation_retrieval import prepare_embedding_bundle, rank_cards
from semantic_review import prepare_review, apply_review

OPERATIONS = {'read', 'use', 'check', 'respond', 'investigate'}
STATES = {'pending', 'in_progress', 'completed', 'cancelled', 'unknown', 'proposed'}
STATE_TEXT = {'pending': '尚未开始且仍待进行', 'in_progress': '已经开始、尚未完成且仍在进行',
              'completed': '已经完成', 'cancelled': '已经取消或放弃'}
ROLES = {'actor': 'character', 'target': 'object', 'task': 'object', 'action': 'object'}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def text(value):
    require(isinstance(value, str) and bool(value.strip()), 'nonempty_text_required')
    return value


def indexed(rows, name):
    require(isinstance(rows, list), 'invalid_' + name)
    result = {}
    for row in rows:
        require(isinstance(row, dict), 'invalid_' + name)
        ident = row.get('id')
        require(isinstance(ident, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,79}', ident), 'invalid_registry_id')
        require(ident not in result, 'duplicate_' + name)
        result[ident] = row
    return result


def signature(action):
    # Task ID, display wording and action ID cannot disguise the same operation.
    return (action['actor_id'], action['operation'], tuple(sorted(action['target_ids'])))


def target_pair(a, b):
    return canonical_digest(sorted((a,b)))


def validate_annotations(session, annotations):
    require(isinstance(annotations, dict) and set(annotations) == {'facts', 'registry'}, 'invalid_annotations')
    registry = annotations['registry']
    require(isinstance(registry, dict) and set(registry) == {'characters', 'entities', 'tasks', 'actions'}, 'invalid_registry')
    groups = {k: indexed(registry[k], k) for k in registry}
    for kind in ('characters', 'entities', 'tasks'):
        labels = []
        for row in groups[kind].values():
            require(set(row) == {'id', 'label'}, 'invalid_identity_fields')
            labels.append(text(row['label']))
        require(len(set(labels)) == len(labels), 'ambiguous_identity_labels')
    require(set(x['label'] for x in groups['characters'].values()) == set(session['source']['characters']), 'character_registry_mismatch')
    source_scenes = {s['id']: s for s in session['source']['scenes']}
    for action in groups['actions'].values():
        mandatory = {'id','actor_id','target_ids','task_id','operation','description','origin','status','anchor'}
        require(mandatory <= set(action) <= mandatory | {'repeat_of','retry_reason'}, 'invalid_action_fields')
        require(action['actor_id'] in groups['characters'] and action['task_id'] in groups['tasks'], 'unknown_action_binding')
        targets = action['target_ids']
        require(isinstance(targets,list) and targets and all(isinstance(t,str) for t in targets)
                and len(set(targets)) == len(targets) and set(targets) <= set(groups['entities']), 'unknown_action_targets')
        require(isinstance(action['operation'],str) and action['operation'] in OPERATIONS, 'invalid_operation')
        text(action['description'])
        require(action['origin'] in ('observed','proposed') and isinstance(action['status'],str) and action['status'] in STATES, 'invalid_action_state')
        require((action['origin'] == 'proposed') == (action['status'] == 'proposed'), 'proposal_is_not_observed_state')
        anchor = action['anchor']
        require(isinstance(anchor,dict) and set(anchor) == {'scene_id','start','end'}, 'invalid_action_anchor')
        require(anchor['scene_id'] in source_scenes, 'action_anchor_outside_source')
        length = len(source_scenes[anchor['scene_id']]['text'])
        require(type(anchor['start']) is int and type(anchor['end']) is int and 0 <= anchor['start'] < anchor['end'] <= length, 'invalid_action_span')
        if 'repeat_of' in action:
            require(action['repeat_of'] in groups['actions'] and action['repeat_of'] != action['id'], 'invalid_repeat_parent')
            require(signature(action) == signature(groups['actions'][action['repeat_of']]), 'repeat_signature_mismatch')
            text(action.get('retry_reason'))
        else:
            require('retry_reason' not in action, 'retry_requires_parent')
    for action in groups['actions'].values():
        visited, cursor = set(), action
        while 'repeat_of' in cursor:
            require(cursor['id'] not in visited, 'repeat_cycle')
            visited.add(cursor['id']); cursor = groups['actions'][cursor['repeat_of']]
    # Stable IDs persist across re-review and source revisions. Semantic content
    # is re-evaluated; the registry is not treated as evidence of current state.
    prior = [h['registry'] for h in session['registry_history']]
    if session['current_state']:
        prior.append(session['current_state']['registry'])
    for old in prior:
        for kind in ('characters','entities','tasks','actions'):
            for row in old[kind]:
                require(row['id'] in groups[kind], 'registry_identity_removed')
                fields = ('actor_id','task_id','target_ids','operation','description','repeat_of','retry_reason') if kind == 'actions' else ('label',)
                current = groups[kind][row['id']]
                require(all(current.get(f) == row.get(f) for f in fields), 'registry_identity_rebound')
                if kind == 'actions' and row['origin'] == 'observed':
                    require(current['origin'] == 'observed', 'observed_action_cannot_become_proposal')
    project = copy.deepcopy(session['source']); project['facts'] = copy.deepcopy(annotations['facts'])
    require(all(not f.get('id','').startswith('core_') for f in project['facts']), 'reserved_fact_id')
    _validate_project(project)
    return groups


def action_bindings(groups, action):
    return {'actor': groups['characters'][action['actor_id']]['label'],
            'target': '、'.join(groups['entities'][t]['label'] for t in sorted(action['target_ids'])),
            'task': groups['tasks'][action['task_id']]['label'], 'action': action['description']}


def prepare_state(session, annotations):
    session = validate_session(session)
    groups = validate_annotations(session, annotations)
    project = copy.deepcopy(session['source']); project['facts'] = copy.deepcopy(annotations['facts'])
    claims = {}
    scenes = {s['id']:s for s in project['scenes']}
    for aid, action in groups['actions'].items():
        binding = action_bindings(groups, action)
        context = '人物：{actor}；对象：{target}；任务：{task}；具体动作：{action}'.format(**binding)
        texts = {'binding': '此动作绑定准确对应当前前文中的人物、对象和任务，动作描述未暗含未经确认的结果；该动作可以是尚未采纳的提案，不表示已经发生。（' + context + '）'}
        if action['origin'] == 'proposed':
            texts['fresh'] = ('截至当前前文末尾，这次具体操作尚未开始；不是把已开始或已完成的操作重新命名成新提案。'
                              '这需要前文依据，不能仅凭未登记完成记录或新编号认定；不要求人物此前已作出计划。（' + context + '）')
        if action['status'] in STATE_TEXT:
            texts['status'] = '截至当前前文末尾，这一具体动作' + STATE_TEXT[action['status']] + '。（' + context + '）'
        if 'repeat_of' in action:
            texts['retry'] = ('当前已有明确的新依据允许再次执行同一对象上的同类动作，而不是重复已经结束的那次行动；依据：'
                              + action['retry_reason'] + '。（' + context + '）')
        claims[aid] = {}
        for kind, claim in texts.items():
            fid = 'core_' + kind + '_' + aid; claims[aid][kind] = fid
            anchor = action['anchor']; scene = scenes[anchor['scene_id']]
            project['facts'].append({'id':fid,'text':claim,**anchor,
                'quote':scene['text'][anchor['start']:anchor['end']], 'known_by':list(project['characters'])})
    # Different IDs alone cannot prove different objects. Review distinctions
    # only where the same actor/operation could otherwise bypass repetition.
    distinctions = {}
    actions = list(groups['actions'].values())
    for i, left in enumerate(actions):
        for right in actions[i+1:]:
            if (left['actor_id'],left['operation']) != (right['actor_id'],right['operation']):
                continue
            for a in left['target_ids']:
                for b in right['target_ids']:
                    if a == b or target_pair(a,b) in distinctions:
                        continue
                    key = target_pair(a,b); fid = 'core_distinct_' + key
                    distinctions[key] = fid
                    anchor = left['anchor']; scene = scenes[anchor['scene_id']]
                    claim = ('就当前视角人物可知的事实而言，对象「' + groups['entities'][a]['label']
                             + '」和「' + groups['entities'][b]['label']
                             + '」是不同对象，并非同一对象的两种称呼；不能仅以不同编号作为依据。')
                    project['facts'].append({'id':fid,'text':claim,**anchor,
                        'quote':scene['text'][anchor['start']:anchor['end']], 'known_by':list(project['characters'])})
    packet = prepare_review(project)
    return {'schema_version':1,'token':source_token(session),'base_state_sha256':session['state_sha256'],
            'annotations':copy.deepcopy(annotations),
            'project':project,'packet':packet,'action_claims':claims,'distinct_target_claims':distinctions,
            'instructions':['只依据当前前文末尾的状态，不把引用位置当发生时间。',
                'binding 只核验提案的指代及描述前提，不证明行动发生；status 另审。',
                '基础事实应拆开传闻、观察、信息内容、载体及角色知情。',
                '登记新 ID 不是新事实；引用与精确引文通过校验不等于语义正确。']}


def review_state(session, request, review):
    session = validate_session(session)
    expected = prepare_state(session, request['annotations'])
    require(request == expected, 'state_request_changed_or_stale')
    result = apply_review(request['project'], request['packet'], review)
    pov = session['source']['pov_character']
    accepted = {f['id']: f for f in result['project']['facts']}
    usable = {fid for fid,f in accepted.items() if pov in f['known_by']}
    actions = {}
    for action in request['annotations']['registry']['actions']:
        aid = action['id']; claims = request['action_claims'][aid]
        bound = claims['binding'] in usable
        state = 'proposed' if action['origin'] == 'proposed' and bound and claims.get('fresh') in usable else 'unknown'
        if bound and claims.get('status') in usable:
            state = action['status']
        actions[aid] = {'binding_usable':bound, 'status':state,
            'retry_usable':claims.get('retry') in usable,
            'evidence_fact_ids':[fid for fid in claims.values() if fid in usable]}
    base_ids = {f['id'] for f in request['annotations']['facts']}
    state = {'schema_version':1,'token':source_token(session),
        'registry':copy.deepcopy(request['annotations']['registry']), 'actions':actions,
        'distinct_targets':{key:fid for key,fid in request['distinct_target_claims'].items() if fid in usable},
        'base_facts':[f for fid,f in accepted.items() if fid in usable and fid in base_ids],
        'usable_facts':[f for fid,f in accepted.items() if fid in usable],
        'provenance':{'request_sha256':canonical_digest(request),'review_sha256':canonical_digest(review)},
        'author_audit':{**result['audit'],'imported_review':copy.deepcopy(review)}}
    return install_state(session,state,source_token(session))


def validate_catalog(catalog, repo_root):
    cards = _validate_catalog(catalog, repo_root)
    for card in cards.values():
        require(card['roles'] == ROLES, 'action_card_roles_required')
        text(card.get('retrieval_text'))
        for variant in card['variants']:
            for name, known in (('operations',OPERATIONS),('action_states',{'proposed','pending','in_progress'})):
                value = variant.get(name)
                require(isinstance(value,list) and value and all(isinstance(v,str) for v in value) and len(set(value)) == len(value) and set(value) <= known,'invalid_variant_' + name)
            template = text(variant.get('proposal_template'))
            for _,field,spec,conv in Formatter().parse(template):
                require(field is None or field in ROLES and not spec and conv is None, 'invalid_proposal_template')
    return cards


def action_block_reason(action, state):
    current = state['actions'][action['id']]
    if not current['binding_usable']:
        return 'binding_not_pov_established'
    if current['status'] not in {'proposed','pending','in_progress'}:
        return 'action_' + current['status']
    actions = {a['id']:a for a in state['registry']['actions']}
    ancestors, parent = set(), action.get('repeat_of')
    while parent is not None:
        ancestors.add(parent); parent = actions[parent].get('repeat_of')
    if ancestors:
        direct = state['actions'][action['repeat_of']]
        if not current['retry_usable'] or not direct['binding_usable'] or direct['status'] not in {'completed','cancelled'}:
            return 'retry_not_established'
    for aid, peer in actions.items():
        if aid == action['id'] or aid in ancestors:
            continue
        observed = state['actions'][aid]
        if not observed['binding_usable'] or (peer['actor_id'],peer['operation']) != (action['actor_id'],action['operation']):
            continue
        if signature(peer) != signature(action):
            if set(peer['target_ids']) & set(action['target_ids']):
                return 'overlapping_operation_' + observed['status']
            if any(target_pair(a,b) not in state['distinct_targets'] for a in peer['target_ids'] for b in action['target_ids'] if a != b):
                return 'target_identity_unresolved'
            continue
        # A child retry is not a second independent action competing with parent.
        cursor = peer; descendants = set()
        while 'repeat_of' in cursor:
            descendants.add(cursor['repeat_of']); cursor = actions[cursor['repeat_of']]
        if action['id'] in descendants:
            continue
        return 'same_operation_' + observed['status']
    return None


def _retrieval_inputs(session, catalog, cards):
    context = {'token':source_token(session),'state_sha256':session['state_sha256'],
               'catalog_sha256':canonical_digest(catalog)}
    query = '\n'.join(f['text'] for f in session['current_state']['base_facts'])
    return context, query, list(cards.values())


def prepare_retrieval_embeddings(session, catalog, repo_root):
    """Export a source-bound local embedding job; never invoke a model."""
    session = validate_session(session)
    require(session['current_state'] is not None, 'reviewed_state_required')
    cards = validate_catalog(catalog, repo_root)
    return prepare_embedding_bundle(*_retrieval_inputs(session,catalog,cards))


def _current_actions(state, pov):
    groups = {k:{r['id']:r for r in v} for k,v in state['registry'].items()}
    available, blocked = [], []
    for action in state['registry']['actions']:
        reason = action_block_reason(action, state)
        if not reason:
            binding = action_bindings(groups, action)
            if binding['actor'] == pov:
                available.append((action, binding, state['actions'][action['id']]['status']))
                continue
            reason = 'actor_not_current_pov'
        blocked.append({'action_id': action['id'], 'reason': reason})
    return available, blocked


def _variant_matches(variant, operation, status):
    return operation in variant['operations'] and status in variant['action_states']


def _card_matches(card, operation, status):
    return any(_variant_matches(v, operation, status) for v in card['variants'])


def prepare_recommendations(session, catalog, repo_root, top_k=2, *,
                            retrieval_method='bm25', embedding_artifact=None, candidate_policy='global'):
    """Allocate one shared card budget, then review each matching action separately.

    action_compatible takes the earliest hits matching a current unblocked POV
    action. action_coverage gives slots to hits covering the most additional
    action IDs, then restores retrieval order within the chosen cards.
    """
    session = validate_session(session)
    require(session['current_state'] is not None, 'reviewed_state_required')
    require(type(top_k) is int and 0 <= top_k <= 50, 'invalid_top_k')
    require(candidate_policy in ('global', 'action_compatible', 'action_coverage'), 'invalid_candidate_policy')
    state = session['current_state']; cards = validate_catalog(catalog, repo_root)
    available, blocked = _current_actions(state, session['source']['pov_character'])
    action_ids_by_card = {}
    if candidate_policy != 'global':
        for card in cards.values():
            action_ids = {action['id'] for action, _, status in available
                          if _card_matches(card, action['operation'], status)}
            if action_ids:
                action_ids_by_card[card['id']] = action_ids
    context, query, card_list = _retrieval_inputs(session,catalog,cards)
    retrieval = rank_cards(context,query,card_list,method=retrieval_method,top_k=top_k,
                           embedding_artifact=embedding_artifact,
                           eligible_card_ids=set(action_ids_by_card) if candidate_policy == 'action_compatible' else None,
                           action_ids_by_card=action_ids_by_card if candidate_policy == 'action_coverage' else None)
    ranking = retrieval['ranking']
    project = copy.deepcopy(session['source'])
    # Reviewed state facts remain separate. Probe reviews cannot change which
    # original facts produced retrieval, or downgrade/re-authorize the registry.
    project['facts'] = []
    instances = []
    for action, binding, status in available:
        for hit in ranking:
            card = cards[hit['source_path']]
            if not _card_matches(card, action['operation'], status):
                continue
            iid = 'i_' + canonical_digest([card['id'],action['id']])[:24]
            spec = {'id':iid,'motif_id':card['id'],'bindings':binding,
                'anchors':{c['id']:copy.deepcopy(action['anchor']) for c in card['conditions']}}
            prepared = prepare_candidates(project,catalog,[spec],repo_root)
            instances.append({'id':iid,'card_id':card['id'],'action_id':action['id'],'prepared':prepared})
    result = {'schema_version':1,'token':source_token(session),'state_sha256':session['state_sha256'],
        'catalog_sha256':canonical_digest(catalog),'top_k':top_k,'retrieval_method':retrieval_method + '_reviewed_state',
        'query':query,'ranking':ranking,'instances':instances,'blocked_actions':blocked}
    if candidate_policy != 'global':
        result.update(candidate_policy=candidate_policy, compatible_card_ids=sorted(action_ids_by_card))
    if candidate_policy == 'action_coverage':
        result['covered_action_ids'] = sorted({instance['action_id'] for instance in instances})
    if retrieval_method != 'bm25':
        result['retrieval_provenance'] = retrieval['provenance']
    return result


def review_recommendations(session, request, reviews, catalog, repo_root, *, embedding_artifact=None):
    session = validate_session(session)
    methods = {name + '_reviewed_state':name for name in ('bm25','vector','hybrid')}
    require(isinstance(request,dict) and isinstance(request.get('retrieval_method'),str)
            and request['retrieval_method'] in methods, 'invalid_retrieval_method')
    method = methods[request['retrieval_method']]
    expected = prepare_recommendations(session,catalog,repo_root,request['top_k'],
        retrieval_method=method,embedding_artifact=embedding_artifact,
        candidate_policy=request.get('candidate_policy', 'global'))
    require(request == expected, 'recommendation_request_changed_or_stale')
    require(isinstance(reviews,dict) and set(reviews) == {i['id'] for i in request['instances']}, 'instance_review_coverage')
    cards = validate_catalog(catalog,repo_root); state = session['current_state']
    groups = {k:{r['id']:r for r in v} for k,v in state['registry'].items()}
    # A reviewed claim can be known while its surrounding quote contains a
    # secret. Source spans remain in the author audit, never the writer view.
    safe_fact = lambda f: {k:f[k] for k in ('id','text','scene_id')}
    proposals, audits, facts = [], [], {f['id']:safe_fact(f) for f in state['base_facts']}
    for instance in request['instances']:
        prepared = instance['prepared']; iid = instance['id']; review = reviews[iid]
        match = match_motifs(prepared['project'],prepared['packet'],review,catalog,repo_root)
        action = groups['actions'][instance['action_id']]; binding = action_bindings(groups,action)
        variants = {v['id']:v for v in cards[instance['card_id']]['variants']}
        audits.append({'instance_id':iid,'match':match['author_audit'],'review_sha256':canonical_digest(review),
                       'imported_review':copy.deepcopy(review),
                       'fact_claims':{c['fact_id']:c['text'] for c in prepared['packet']['candidates']}})
        for choice in match['writer_packet']['proposals']:
            variant = variants[choice['id']]
            if not _variant_matches(variant, action['operation'], state['actions'][action['id']]['status']):
                continue
            evidence_ids = []
            for fact in match['writer_packet']['facts']:
                if fact['id'] not in choice['evidence_fact_ids']:
                    continue
                qualified = iid + ':' + fact['id']; facts[qualified] = dict(fact,id=qualified); evidence_ids.append(qualified)
            action_evidence = list(state['actions'][action['id']]['evidence_fact_ids'])
            for peer in state['registry']['actions']:
                if (peer['actor_id'],peer['operation']) != (action['actor_id'],action['operation']) or not state['actions'][peer['id']]['binding_usable']:
                    continue
                for a in action['target_ids']:
                    for b in peer['target_ids']:
                        fid = state['distinct_targets'].get(target_pair(a,b)) if a != b else None
                        if fid and fid not in action_evidence:
                            action_evidence.append(fid)
            for fact in state['usable_facts']:
                if fact['id'] in action_evidence:
                    facts[fact['id']] = safe_fact(fact); evidence_ids.append(fact['id'])
            identity = [canonical_digest(request),canonical_digest(review),iid,choice['id']]
            proposals.append({'id':'proposal_' + canonical_digest(identity)[:32],
                'actor_id':action['actor_id'],'task_id':action['task_id'],'action_id':action['id'],
                'target_ids':copy.deepcopy(action['target_ids']),'operation':action['operation'],
                'card_id':instance['card_id'],'variant_id':choice['id'],'knowledge_kind':choice['knowledge_kind'],
                'text':variant['proposal_template'].format(**binding),'status':'creative_proposal',
                'evidence_fact_ids':evidence_ids})
    # Registry/source IDs are author metadata, and may themselves name secrets.
    # Keep them in the author-facing batch; writer-local IDs are opaque hashes.
    fact_ids = {fid:'fact_' + canonical_digest([source_token(session),fid]) for fid in facts}
    writer_facts = [{'id':fact_ids[fid],'text':fact['text']} for fid,fact in facts.items()]
    writer_proposals = [{**{k:p[k] for k in ('id','text','status','knowledge_kind')},
                        'evidence_fact_ids':[fact_ids[fid] for fid in p['evidence_fact_ids']]} for p in proposals]
    batch = {'schema_version':1,'token':source_token(session),'state_sha256':session['state_sha256'],
        'catalog_sha256':canonical_digest(catalog),'request_sha256':canonical_digest(request),
        'reviews_sha256':canonical_digest(reviews),'proposals':proposals,
        'writer_packet':{'facts':writer_facts,'proposals':writer_proposals,
                         'instruction':'仅 facts 可作为当前视角事实；proposals 是未来选择，采纳不代表已经发生。'},
        'author_audit':{'ranking':request['ranking'],'blocked_actions':request['blocked_actions'],
                        'writer_fact_ids':fact_ids,'matches':audits}}
    if 'candidate_policy' in request:
        batch['author_audit']['candidate_policy'] = request['candidate_policy']
        batch['author_audit']['compatible_card_ids'] = list(request['compatible_card_ids'])
    if 'covered_action_ids' in request:
        batch['author_audit']['covered_action_ids'] = list(request['covered_action_ids'])
    if method != 'bm25':
        batch['author_audit']['retrieval_provenance'] = copy.deepcopy(request['retrieval_provenance'])
        batch['author_audit']['retrieval_method'] = request['retrieval_method']
    return install_batch(session,batch,source_token(session))


def accept_current(session, proposal_id, expected_token, batch_sha256, catalog, repo_root):
    session = validate_session(session)
    validate_catalog(catalog,repo_root)
    require(session['current_batch'] is not None and session['current_batch']['catalog_sha256'] == canonical_digest(catalog), 'catalog_changed_or_batch_missing')
    return accept_proposal(session,proposal_id,expected_token,batch_sha256)
