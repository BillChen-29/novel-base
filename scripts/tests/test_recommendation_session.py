"""Pure session contracts: source facts, reviewed state, and intent stay separate."""
from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor
import unittest

from recommendation_session import (
    accept_proposal, append_scene, canonical_digest, install_batch, install_state,
    new_session, replace_source, source_token, validate_session,
)


def source(project_id="雨夜-project"):
    return {"schema_version": 1, "project_id": project_id, "title": "雨夜 🗝️",
            "characters": ["林舟", "许岚"], "pov_character": "林舟",
            "goal": {"id": "recover_and_investigate", "description": "调查线索"},
            "scenes": [{"id": "s1", "order": 1, "text": "林舟捡到钥匙。",
                        "function": "action", "tension": 3,
                        "present_characters": ["林舟"]}], "facts": [], "threads": []}


def state(session):
    return {"token": source_token(session), "registry": [{"id": "thread1", "status": "open"}],
            "actions": [{"id": "action1", "completed": False}], "review": "confirmed"}


def batch(session):
    return {"token": source_token(session), "state_sha256": session["state_sha256"],
            "proposals": [{"id": "p1", "actor_id": "林舟", "task_id": "thread1",
                           "action_id": "action1", "target_ids": ["许岚"],
                           "operation": "investigate", "text": "询问许岚 '钥匙' 的去向 🗝️",
                           "status": "creative_proposal"}]}


def ready():
    session = new_session(source())
    session = install_state(session, state(session), source_token(session))
    return install_batch(session, batch(session), source_token(session))


class SessionContracts(unittest.TestCase):
    def test_initialization_normalizes_and_detaches_source(self):
        project = source()
        session = new_session(project)
        self.assertEqual(session["revision"], 1)
        self.assertEqual(source_token(session), {
            "project_id": project["project_id"], "revision": 1,
            "source_sha256": canonical_digest(session["source"])})
        self.assertIsNone(session["current_state"])
        self.assertIsNone(session["current_batch"])
        project["scenes"][0]["text"] = "修改"
        self.assertEqual(session["source"]["scenes"][0]["text"], "林舟捡到钥匙。")
        checked = validate_session(session)
        checked["source"]["title"] = "detached"
        self.assertEqual(session["source"]["title"], "雨夜 🗝️")

    def test_source_requires_valid_raw_project(self):
        invalid = [None, [], {}, "project"]
        for field, value in [("facts", [{}]), ("threads", [{}]),
                             ("motif_annotations", []), ("scenes", []),
                             ("characters", []), ("schema_version", True)]:
            project = source()
            project[field] = value
            invalid.append(project)
        for project in invalid:
            with self.subTest(project=project), self.assertRaises(ValueError):
                new_session(project)

    def test_accept_is_only_intent_and_idempotent(self):
        session = ready()
        original = copy.deepcopy(session)
        accepted = accept_proposal(session, "p1", source_token(session), session["batch_sha256"])
        self.assertEqual(session, original)
        self.assertEqual(accepted["source"], original["source"])
        self.assertEqual(accepted["current_state"], original["current_state"])
        self.assertEqual(accepted["current_batch"], original["current_batch"])
        self.assertFalse(accepted["current_state"]["actions"][0]["completed"])
        self.assertEqual(len(accepted["plans"]), 1)
        plan = accepted["plans"][0]
        self.assertEqual(plan["status"], "accepted_intent")
        self.assertEqual(plan["proposal"], original["current_batch"]["proposals"][0])
        self.assertEqual(plan["token"], source_token(session))
        repeated = accept_proposal(accepted, "p1", source_token(accepted), accepted["batch_sha256"])
        self.assertEqual(repeated, accepted)
        repeated["plans"][0]["proposal"]["text"] = "changed"
        self.assertNotEqual(repeated, accepted)

    def test_append_and_edit_invalidate_state_and_preserve_labeled_history(self):
        session = ready()
        session = accept_proposal(session, "p1", source_token(session), session["batch_sha256"])
        old = copy.deepcopy(session)
        next_scene = {"id": "s2", "order": 2, "text": "许岚出现了。", "function": "dialogue",
                      "tension": 1, "present_characters": ["许岚"]}
        changed = append_scene(session, next_scene, source_token(session))
        self.assertEqual(session, old)
        self.assertEqual(changed["revision"], 2)
        self.assertIsNone(changed["current_state"])
        self.assertIsNone(changed["current_batch"])
        self.assertIsNone(changed["state_sha256"])
        self.assertIsNone(changed["batch_sha256"])
        self.assertEqual(changed["plans"], session["plans"])
        self.assertEqual(changed["source_history"], [{"token": source_token(session),
                                                        "source": session["source"]}])
        self.assertEqual(changed["registry_history"], [{"token": source_token(session),
                                                          "registry": session["current_state"]["registry"]}])
        edited = copy.deepcopy(changed["source"])
        edited["scenes"][0]["text"] = "林舟丢掉了钥匙。"
        third = replace_source(changed, edited, source_token(changed))
        self.assertEqual(third["revision"], 3)
        self.assertEqual(third["source_history"][0]["source"]["scenes"][0]["text"], "林舟捡到钥匙。")
        self.assertEqual(third["source_history"][1]["source"], changed["source"])
        self.assertEqual(third["registry_history"], changed["registry_history"])
        self.assertEqual(third["plans"][0]["token"]["revision"], 1)

    def test_expected_token_blocks_stale_cross_project_and_malformed_operations(self):
        session = ready()
        for token in [None, {}, {**source_token(session), "revision": 0},
                      {**source_token(session), "project_id": "other"},
                      {**source_token(session), "revision": True},
                      {**source_token(session), "source_sha256": "0" * 64}]:
            for operation in [lambda: replace_source(session, source(), token),
                              lambda: append_scene(session, source()["scenes"][0], token),
                              lambda: install_state(session, state(session), token),
                              lambda: install_batch(session, batch(session), token),
                              lambda: accept_proposal(session, "p1", token, session["batch_sha256"])]:
                with self.subTest(token=token), self.assertRaises(ValueError):
                    operation()
        with self.assertRaises(ValueError):
            replace_source(session, source("another"), source_token(session))

    def test_new_state_review_invalidates_old_batch_even_on_same_source(self):
        session = ready()
        reviewed = state(session)
        reviewed["review"] = "rejected annotation"
        replaced = install_state(session, reviewed, source_token(session))
        self.assertIsNone(replaced["current_batch"])
        self.assertIsNone(replaced["batch_sha256"])
        self.assertNotEqual(replaced["state_sha256"], session["state_sha256"])
        with self.assertRaises(ValueError):
            install_batch(replaced, session["current_batch"], source_token(replaced))
        with self.assertRaises(ValueError):
            accept_proposal(replaced, "p1", source_token(replaced), session["batch_sha256"])

    def test_state_and_batch_inputs_are_copied_and_bound_to_current_source(self):
        session = new_session(source())
        reviewed = state(session)
        installed = install_state(session, reviewed, source_token(session))
        reviewed["registry"].clear()
        self.assertEqual(len(installed["current_state"]["registry"]), 1)
        proposed = batch(installed)
        with_batch = install_batch(installed, proposed, source_token(installed))
        proposed["proposals"].clear()
        self.assertEqual(len(with_batch["current_batch"]["proposals"]), 1)
        for invalid in [None, {}, {"token": source_token(session)},
                        {"token": source_token(session), "registry": None},
                        {**state(session), "token": {**source_token(session), "revision": 99}}]:
            with self.subTest(state=invalid), self.assertRaises(ValueError):
                install_state(session, invalid, source_token(session))
        with self.assertRaises(ValueError):
            install_batch(session, batch(installed), source_token(session))

    def test_batch_rejects_wrong_state_token_and_ill_formed_proposals(self):
        session = ready()
        invalid_batches = [None, {}, {**batch(session), "state_sha256": "0" * 64},
                           {**batch(session), "token": {**source_token(session), "project_id": "other"}},
                           {**batch(session), "proposals": None}]
        duplicate = batch(session)
        duplicate["proposals"] *= 2
        invalid_batches.append(duplicate)
        for field, value in [("id", ""), ("actor_id", None), ("task_id", []),
                             ("action_id", 3), ("target_ids", ["x", "x"]),
                             ("target_ids", "许岚"), ("operation", ""), ("text", ""),
                             ("status", "fact")]:
            proposed = batch(session)
            proposed["proposals"][0][field] = value
            invalid_batches.append(proposed)
        for proposed in invalid_batches:
            with self.subTest(batch=proposed), self.assertRaises(ValueError):
                install_batch(session, proposed, source_token(session))
        empty = batch(session)
        empty["proposals"] = []
        self.assertEqual(install_batch(session, empty, source_token(session))["current_batch"]["proposals"], [])

    def test_accept_rejects_unknown_id_wrong_hash_and_obsolete_batch(self):
        session = ready()
        for proposal_id, digest in [(None, session["batch_sha256"]), ("missing", session["batch_sha256"]),
                                    ("p1", None), ("p1", "0" * 64)]:
            with self.subTest(proposal_id=proposal_id), self.assertRaises(ValueError):
                accept_proposal(session, proposal_id, source_token(session), digest)
        newer = batch(session)
        newer["proposals"][0]["text"] = "新的建议"
        changed = install_batch(session, newer, source_token(session))
        with self.assertRaises(ValueError):
            accept_proposal(changed, "p1", source_token(changed), session["batch_sha256"])
        accepted = accept_proposal(session, "p1", source_token(session), session["batch_sha256"])
        newer = install_batch(accepted, newer, source_token(accepted))
        twice = accept_proposal(newer, "p1", source_token(newer), newer["batch_sha256"])
        self.assertEqual(len(twice["plans"]), 2)

    def test_accidental_mutations_to_each_persisted_layer_are_detected(self):
        session = ready()
        session = accept_proposal(session, "p1", source_token(session), session["batch_sha256"])
        for mutate in [lambda s: s["source"]["scenes"][0].update(text="篡改"),
                       lambda s: s["current_state"]["registry"].clear(),
                       lambda s: s["current_batch"]["proposals"][0].update(text="篡改"),
                       lambda s: s["plans"][0]["proposal"].update(text="篡改"),
                       lambda s: s.update(revision=True), lambda s: s.update(project_id="other")]:
            modified = copy.deepcopy(session)
            mutate(modified)
            for operation in [lambda: validate_session(modified), lambda: source_token(modified)]:
                with self.assertRaises(ValueError):
                    operation()
        changed = replace_source(session, source(), source_token(session))
        for key in ("source_history", "registry_history"):
            modified = copy.deepcopy(changed)
            modified[key].clear()
            with self.assertRaises(ValueError):
                validate_session(modified)

    def test_invalid_sessions_and_non_json_values_raise_value_error(self):
        for session in (None, [], {}, {"schema_version": True}):
            with self.subTest(session=session), self.assertRaises(ValueError):
                validate_session(session)
        for value in (float("nan"), float("inf"), object(), {1: "value"}, {"set": {1, 2}}, (1, 2)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                canonical_digest(value)
        cyclic = []
        cyclic.append(cyclic)
        with self.assertRaises(ValueError):
            canonical_digest(cyclic)

    def test_independent_sessions_and_concurrent_pure_operations(self):
        first, second = ready(), ready()
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda _: accept_proposal(first, "p1", source_token(first),
                                                              first["batch_sha256"]), range(8)))
        self.assertEqual(first["plans"], [])
        self.assertEqual(first, second)
        self.assertTrue(all(len(result["plans"]) == 1 for result in results))
        results[0]["plans"].clear()
        self.assertEqual(len(results[1]["plans"]), 1)

    def test_large_scene_sources_and_boundary_tension_are_supported(self):
        project = source()
        project["scenes"] = [{**project["scenes"][0], "id": f"s{i}", "order": i,
                              "tension": 1 if i % 2 else 5} for i in range(1, 10001)]
        session = new_session(project)
        self.assertEqual(len(session["source"]["scenes"]), 10000)
        self.assertEqual(validate_session(session), session)


if __name__ == "__main__":
    unittest.main()
