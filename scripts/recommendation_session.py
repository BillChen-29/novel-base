"""Pure revision-bound recommendation sessions; no persistence or external IO.

Adapters establish the meaning of reviewed state. This module preserves source
snapshots and accepts only creative intentions: acceptance never updates facts,
registry status, or action completion. Digests detect accidental content changes;
they do not authenticate a caller or prove a review happened.
"""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re

from narrative_prototype import _validate_project


_FIELDS = {"schema_version", "project_id", "revision", "source_sha256", "source",
           "source_history", "current_state", "state_sha256", "current_batch",
           "batch_sha256", "registry_history", "plans", "integrity_sha256"}
_TOKEN_FIELDS = {"project_id", "revision", "source_sha256"}


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _hash(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _json_value(value, active):
    if value is None or type(value) in (str, bool, int):
        return
    if type(value) is float:
        _require(math.isfinite(value), "non-finite JSON number")
        return
    _require(type(value) in (dict, list), "value must contain only JSON types")
    _require(id(value) not in active, "cyclic JSON value")
    active.add(id(value))
    if isinstance(value, dict):
        _require(all(type(key) is str for key in value), "JSON object keys must be strings")
        children = value.values()
    else:
        children = value
    for child in children:
        _json_value(child, active)
    active.remove(id(value))


def canonical_digest(value):
    """Return canonical JSON SHA256 (content integrity, never authentication)."""
    try:
        _json_value(value, set())
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, OverflowError, RecursionError, UnicodeError) as error:
        raise ValueError("value is not finite UTF-8 JSON") from error
    return hashlib.sha256(raw).hexdigest()


def _source(project):
    _require(isinstance(project, dict), "source must be a project object")
    _require(project.get("facts") == [] and project.get("threads") == [],
             "raw source facts and threads must be empty")
    _require("motif_annotations" not in project, "raw source cannot contain motif_annotations")
    canonical_digest(project)
    return _validate_project(project)


def _token(token):
    _require(isinstance(token, dict) and set(token) == _TOKEN_FIELDS, "invalid source token")
    _require(_text(token["project_id"]) and type(token["revision"]) is int and
             token["revision"] >= 1 and _hash(token["source_sha256"]), "invalid source token")
    return token


def _current_token(session):
    return {key: session[key] for key in ("project_id", "revision", "source_sha256")}


def _expected(session, expected_token):
    _require(_token(expected_token) == _current_token(session), "stale or cross-project source token")


def _state(state, token):
    _require(isinstance(state, dict), "state must be an object")
    _require(_token(state.get("token")) == token, "state belongs to another source")
    _require(isinstance(state.get("registry"), (dict, list)), "state.registry must be an object or list")


def _proposal(proposal):
    _require(isinstance(proposal, dict), "proposal must be an object")
    for field in ("id", "actor_id", "task_id", "action_id", "operation", "text"):
        _require(_text(proposal.get(field)), f"proposal.{field} must be nonempty text")
    targets = proposal.get("target_ids")
    _require(isinstance(targets, list) and all(_text(item) for item in targets),
             "proposal.target_ids must be a string list")
    _require(len(set(targets)) == len(targets), "duplicate proposal target")
    _require(proposal.get("status") == "creative_proposal", "proposal must be creative_proposal")


def _batch(batch, token, state_sha256):
    _require(isinstance(batch, dict), "batch must be an object")
    _require(_token(batch.get("token")) == token, "batch belongs to another source")
    _require(_hash(state_sha256) and batch.get("state_sha256") == state_sha256,
             "batch belongs to another reviewed state")
    proposals = batch.get("proposals")
    _require(isinstance(proposals, list), "batch.proposals must be a list")
    identifiers = set()
    for proposal in proposals:
        _proposal(proposal)
        _require(proposal["id"] not in identifiers, "duplicate proposal id")
        identifiers.add(proposal["id"])


def _seal(session):
    session["integrity_sha256"] = canonical_digest(
        {key: value for key, value in session.items() if key != "integrity_sha256"})
    return session


def validate_session(session):
    """Validate structure and content bindings, returning an independent copy."""
    _require(isinstance(session, dict) and set(session) == _FIELDS, "invalid session structure")
    _require(type(session["schema_version"]) is int and session["schema_version"] == 1,
             "unsupported session schema")
    token = _token(_current_token(session))
    _require(_hash(session["integrity_sha256"]) and session["integrity_sha256"] == canonical_digest(
        {key: value for key, value in session.items() if key != "integrity_sha256"}),
        "session content digest mismatch")
    project = _source(session["source"])
    _require(project == session["source"] and project["project_id"] == token["project_id"] and
             canonical_digest(project) == token["source_sha256"], "source binding mismatch")
    history = session["source_history"]
    _require(isinstance(history, list) and len(history) == token["revision"] - 1,
             "source history must contain each earlier revision")
    tokens = {token["revision"]: token}
    for revision, snapshot in enumerate(history, 1):
        _require(isinstance(snapshot, dict) and set(snapshot) == {"token", "source"}, "invalid source snapshot")
        old_source = _source(snapshot["source"])
        old_token = _token(snapshot["token"])
        _require(old_source == snapshot["source"] and old_source["project_id"] == token["project_id"] and
                 old_token == {"project_id": token["project_id"], "revision": revision,
                               "source_sha256": canonical_digest(old_source)}, "invalid snapshot binding")
        tokens[revision] = old_token
    registry_history = session["registry_history"]
    _require(isinstance(registry_history, list), "registry_history must be a list")
    for item in registry_history:
        _require(isinstance(item, dict) and set(item) == {"token", "registry"}, "invalid registry snapshot")
        prior_token = _token(item["token"])
        _require(tokens.get(prior_token["revision"]) == prior_token and
                 isinstance(item["registry"], (dict, list)), "invalid registry snapshot binding")
    state = session["current_state"]
    if state is None:
        _require(session["state_sha256"] is None and session["current_batch"] is None,
                 "batch requires current reviewed state")
    else:
        _state(state, token)
        _require(session["state_sha256"] == canonical_digest(state), "state digest mismatch")
    batch = session["current_batch"]
    if batch is None:
        _require(session["batch_sha256"] is None, "missing batch content")
    else:
        _batch(batch, token, session["state_sha256"])
        _require(session["batch_sha256"] == canonical_digest(batch), "batch digest mismatch")
    _require(isinstance(session["plans"], list), "plans must be a list")
    identities = set()
    for plan in session["plans"]:
        _require(isinstance(plan, dict) and set(plan) == {"proposal", "batch_sha256", "token", "status"},
                 "invalid plan structure")
        origin = _token(plan["token"])
        _require(tokens.get(origin["revision"]) == origin and plan["status"] == "accepted_intent" and
                 _hash(plan["batch_sha256"]), "invalid accepted intention")
        _proposal(plan["proposal"])
        identity = (plan["batch_sha256"], plan["proposal"]["id"])
        _require(identity not in identities, "duplicate accepted intention")
        identities.add(identity)
    return copy.deepcopy(session)


def new_session(project):
    """Create revision 1 from unannotated raw source."""
    source = _source(project)
    return _seal({"schema_version": 1, "project_id": source["project_id"], "revision": 1,
                  "source_sha256": canonical_digest(source), "source": source,
                  "source_history": [], "current_state": None, "state_sha256": None,
                  "current_batch": None, "batch_sha256": None, "registry_history": [], "plans": []})


def source_token(session):
    """Return a detached optimistic-concurrency token after session validation."""
    return _current_token(validate_session(session))


def _archive_registry(session):
    if session["current_state"] is not None:
        session["registry_history"].append({"token": _current_token(session),
                                             "registry": copy.deepcopy(session["current_state"]["registry"])})


def replace_source(session, project, expected_token):
    """Archive a source revision; invalidate current review and recommendations."""
    result = validate_session(session)
    _expected(result, expected_token)
    source = _source(project)
    _require(source["project_id"] == result["project_id"], "cannot replace source across projects")
    result["source_history"].append({"token": _current_token(result), "source": result["source"]})
    _archive_registry(result)
    result.update(source=source, revision=result["revision"] + 1,
                  source_sha256=canonical_digest(source), current_state=None, state_sha256=None,
                  current_batch=None, batch_sha256=None)
    return _seal(result)


def append_scene(session, scene, expected_token):
    """Append a valid scene using the same revision checks as source replacement."""
    checked = validate_session(session)
    _expected(checked, expected_token)
    project = checked["source"]
    project["scenes"].append(copy.deepcopy(scene))
    return replace_source(session, project, expected_token)


def install_state(session, state, expected_token):
    """Install trusted adapter output; state semantics remain adapter-owned."""
    result = validate_session(session)
    _expected(result, expected_token)
    _state(state, _current_token(result))
    _archive_registry(result)
    result.update(current_state=copy.deepcopy(state), state_sha256=canonical_digest(state),
                  current_batch=None, batch_sha256=None)
    return _seal(result)


def install_batch(session, batch, expected_token):
    """Install proposals bound to this source and its current reviewed state."""
    result = validate_session(session)
    _expected(result, expected_token)
    _require(result["current_state"] is not None, "reviewed state required before proposals")
    _batch(batch, _current_token(result), result["state_sha256"])
    result.update(current_batch=copy.deepcopy(batch), batch_sha256=canonical_digest(batch))
    return _seal(result)


def accept_proposal(session, proposal_id, expected_token, batch_sha256):
    """Record a stored creative proposal as intent, idempotently within its batch."""
    result = validate_session(session)
    _expected(result, expected_token)
    _require(_text(proposal_id), "proposal_id must be nonempty text")
    _require(result["current_batch"] is not None and _hash(batch_sha256) and
             batch_sha256 == result["batch_sha256"], "stale or missing recommendation batch")
    proposal = next((item for item in result["current_batch"]["proposals"] if item["id"] == proposal_id), None)
    _require(proposal is not None, "proposal does not exist in current batch")
    if not any(plan["batch_sha256"] == batch_sha256 and plan["proposal"]["id"] == proposal_id
               for plan in result["plans"]):
        result["plans"].append({"proposal": copy.deepcopy(proposal), "batch_sha256": batch_sha256,
                                "token": _current_token(result), "status": "accepted_intent"})
    return _seal(result)
