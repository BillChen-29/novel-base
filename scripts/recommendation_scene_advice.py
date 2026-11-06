"""Read-only, author-facing pacing references for one accepted, current action."""
from narrative_prototype import GOALS, run_pipeline
from recommendation_engine import require
from recommendation_session import _expected, canonical_digest, validate_session


_THREAD_FIELDS = {'id', 'description', 'status', 'setup_fact_ids', 'resolution_fact_id', 'reveal_allowed'}


def prepare_scene_advice(session, proposal_id, repo_root, *, expected_token, expected_batch_sha256,
                         goal_id, threads=None):
    """Rank scene strategies using current POV facts and optional author annotations.

    Each open thread uses the narrative prototype's thread schema. Its setup and
    optional resolution must refer to current reviewed base facts. The prototype
    checks those references and the scene order and permission needed for reveals.
    The accepted action binds the report. The existing scorer ranks strategies
    at scene level using author goal, rhythm and reviewed setup.
    """
    checked = validate_session(session)
    _expected(checked, expected_token)
    state, batch = checked['current_state'], checked['current_batch']
    require(state is not None and batch is not None and expected_batch_sha256 == checked['batch_sha256'],
            'stale_or_missing_scene_advice_batch')
    proposal = next((item for item in batch['proposals'] if item['id'] == proposal_id), None)
    require(proposal is not None, 'proposal_not_current')
    require(any(plan['batch_sha256'] == expected_batch_sha256 and plan['token'] == batch['token']
                and plan['proposal'] == proposal and plan['status'] == 'accepted_intent'
                for plan in checked['plans']), 'proposal_not_accepted')
    require(isinstance(goal_id, str) and goal_id in GOALS, 'invalid_scene_goal')

    # validate_session detached the source. Goals and thread descriptions are author
    # annotations. Only POV-known base facts enter the fact list, never action probes.
    project = checked['source']
    facts = state.get('base_facts')
    require(isinstance(facts, list) and all(
        isinstance(fact, dict) and isinstance(fact.get('id'), str) and not fact['id'].startswith('core_')
        and isinstance(fact.get('known_by'), list) and project['pov_character'] in fact['known_by']
        for fact in facts), 'reviewed_pov_base_facts_required')
    project['facts'] = facts
    project['goal'] = {'id': goal_id, 'description': GOALS[goal_id]}
    threads = [] if threads is None else threads
    require(isinstance(threads, list) and all(
        isinstance(thread, dict) and set(thread) == _THREAD_FIELDS and thread['status'] == 'open'
        and isinstance(thread['setup_fact_ids'], list) and thread['setup_fact_ids']
        for thread in threads), 'open_threads_with_reviewed_setup_required')
    project['threads'] = threads
    report = run_pipeline(project, repo_root)

    strategies = []
    for item in report['recommendations']:
        strategy = item['context_packet']['strategy']
        strategies.append({
            **{key: item[key] for key in ('id', 'title', 'score', 'score_breakdown', 'evidence_fact_ids')},
            'function': strategy['function'], 'target_tension': strategy['target_tension'],
            'source_refs': [{key: ref[key] for key in ('path', 'title', 'sha256')} for ref in item['source_refs']],
        })
    return {
        'schema_version': 1, 'token': batch['token'], 'state_sha256': checked['state_sha256'],
        'batch_sha256': checked['batch_sha256'], 'proposal_id': proposal_id, 'action_id': proposal['action_id'],
        'operation': proposal['operation'], 'goal': project['goal'], 'threads_sha256': canonical_digest(threads),
        'known_fact_ids': report['story_state']['known_fact_ids'], 'rhythm': report['story_state']['rhythm'],
        'strategies': strategies,
    }
