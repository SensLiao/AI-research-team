"""Deterministic Paper Design Tokens and immutable manuscript contracts.

The resolver deliberately returns two views: the closed-schema token snapshot
used by ``manuscript_contract`` and rich provenance/caveats used by callers for
review evidence.  This keeps the registered JSON Schema authoritative without
discarding the history needed to explain advisory overrides.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml

from research_agent_teams.tools._manuscript_contract_validation import (
    ManuscriptContractError,
    canonical_json as _canonical_json,
    canonical_sha256 as _canonical_sha256,
    fail as _fail,
    require_reference as _require_reference,
    require_sha256 as _require_sha256,
    validate_dependency_slice_hashes as _validate_dependency_slice_hashes,
    validate_official_profile as _validate_official_profile,
    validate_outline as _validate_outline,
    validate_source_closure as _validate_source_closure,
)
from research_agent_teams.tools.manuscript_security import (
    scan_persisted_text,
    validate_run_owned_path,
)
from research_agent_teams.tools.runstore import atomic_write_text
from research_agent_teams.tools.validate_artifact import validate_payload


TOKEN_LAYERS = ("base", "paper_type", "venue", "project", "run")

_DEFAULT_SECRET_PATTERNS = {
    "credential-bearing-url": re.compile(
        r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@", re.IGNORECASE
    ),
    "authorization-header": re.compile(
        r"\bauthorization\s*:\s*(?:bearer|basic)\s+\S+", re.IGNORECASE
    ),
}


def _layer_tokens(raw_layer: Any, layer: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if raw_layer is None:
        return {}, {}
    if not isinstance(raw_layer, Mapping):
        _fail("INVALID_TOKEN_LAYER", f"{layer} layer must be an object")
    document = dict(raw_layer)
    if "layer" in document and document["layer"] != layer:
        _fail(
            "TOKEN_LAYER_MISMATCH",
            f"layer {layer!r} declares itself as {document['layer']!r}",
        )
    if "tokens" in document:
        tokens = document["tokens"]
        metadata = document
    else:
        tokens = document
        metadata = {}
    if not isinstance(tokens, Mapping):
        _fail("INVALID_TOKEN_LAYER", f"{layer}.tokens must be an object")
    return dict(tokens), metadata


def _normalise_token_entry(
    token: str,
    raw_entry: Any,
    *,
    layer: str,
    metadata: Mapping[str, Any],
    inherited_classification: str | None,
) -> dict[str, Any]:
    if not isinstance(token, str) or not token or re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]*", token
    ) is None:
        _fail("INVALID_TOKEN_NAME", f"invalid token name {token!r}")
    if raw_entry is None:
        return {"delete": True}
    if not isinstance(raw_entry, Mapping):
        _fail("INVALID_TOKEN_ENTRY", f"token {token!r} in {layer} must be an object")
    entry = dict(raw_entry)
    if entry.get("delete") is True:
        return {"delete": True}
    if "value" not in entry:
        _fail("MISSING_TOKEN_VALUE", f"token {token!r} in {layer} has no value")

    classification = entry.get("classification")
    if classification is None and "hard" in entry:
        classification = "HARD" if bool(entry["hard"]) else "ADVISORY"
    if classification is None:
        classification = inherited_classification or "ADVISORY"
    if classification not in {"HARD", "ADVISORY"}:
        _fail(
            "INVALID_TOKEN_CLASSIFICATION",
            f"token {token!r} in {layer} has invalid classification",
        )

    weakenable = entry.get("weakenable", classification == "ADVISORY")
    if not isinstance(weakenable, bool):
        _fail("INVALID_TOKEN_ENTRY", f"token {token!r} weakenable must be boolean")
    if classification == "HARD" and weakenable:
        _fail(
            "HARD_RULE_WEAKENING",
            f"hard token {token!r} in {layer} cannot be weakenable",
        )

    source_ref = entry.get("source_ref", metadata.get("source_ref"))
    source_sha256 = entry.get("source_sha256", metadata.get("source_sha256"))
    return {
        "value": copy.deepcopy(entry["value"]),
        "classification": classification,
        "weakenable": weakenable,
        "source_ref": _require_reference(
            source_ref, label=f"{layer}.{token}.source_ref"
        ),
        "source_sha256": _require_sha256(
            source_sha256,
            code="TOKEN_SOURCE_HASH",
            label=f"{layer}.{token}.source_sha256",
        ),
    }


def _token_snapshot(tokens: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [
        {
            "token": row["token"],
            "value": copy.deepcopy(row["value"]),
            "classification": row["classification"],
            "resolved_layer": row["resolved_layer"],
            "source_ref": row["source_ref"],
            "source_sha256": row["source_sha256"],
            "weakenable": row["weakenable"],
        }
        for row in sorted(tokens, key=lambda item: str(item["token"]))
    ]
    unsigned = {"cascade_order": list(TOKEN_LAYERS), "tokens": rows}
    return {**unsigned, "snapshot_sha256": _canonical_sha256(unsigned)}


def resolve_paper_design_tokens(
    layers: Mapping[str, Mapping[str, Any] | None],
    *,
    mandatory_tokens: Iterable[str] = (),
) -> dict[str, Any]:
    """Resolve the fixed five-layer cascade without mutating caller input.

    Layer documents may put ``source_ref``/``source_sha256`` at document level,
    or each token may carry its own source facts.  ``hard`` is accepted as a
    compatibility alias for ``classification``; output always uses the closed
    schema's ``HARD``/``ADVISORY`` vocabulary.
    """

    if not isinstance(layers, Mapping):
        _fail("INVALID_TOKEN_LAYERS", "layers must be a mapping")
    unknown_layers = sorted(set(layers) - set(TOKEN_LAYERS))
    if unknown_layers:
        _fail("UNKNOWN_TOKEN_LAYER", f"unknown layers: {unknown_layers}")

    required = {str(token) for token in mandatory_tokens}
    state: dict[str, dict[str, Any]] = {}
    histories: dict[str, list[dict[str, Any]]] = {}
    caveats: list[dict[str, Any]] = []

    for layer in TOKEN_LAYERS:
        tokens, metadata = _layer_tokens(layers.get(layer), layer)
        layer_mandatory = metadata.get("mandatory_tokens", ())
        if not isinstance(layer_mandatory, Sequence) or isinstance(
            layer_mandatory, (str, bytes)
        ):
            _fail(
                "INVALID_MANDATORY_TOKENS",
                f"{layer}.mandatory_tokens must be a list",
            )
        required.update(str(token) for token in layer_mandatory)

        for token in sorted(tokens):
            previous = state.get(token)
            entry = _normalise_token_entry(
                token,
                tokens[token],
                layer=layer,
                metadata=metadata,
                inherited_classification=(
                    str(previous["classification"]) if previous else None
                ),
            )

            if entry.get("delete") is True:
                if previous and previous["classification"] == "HARD":
                    _fail(
                        "HARD_RULE_DELETE",
                        f"hard token {token!r} cannot be deleted by {layer}",
                    )
                if previous:
                    caveats.append(
                        {
                            "code": "ADVISORY_DELETE",
                            "token": token,
                            "from_layer": previous["resolved_layer"],
                            "to_layer": layer,
                            "prior_value": copy.deepcopy(previous["value"]),
                            "value": None,
                            "blocking": False,
                            "daily_state": "USABLE_WITH_CAVEATS",
                        }
                    )
                    del state[token]
                continue

            if token == "requires_pdf" and previous is None:
                if layer != "venue":
                    _fail(
                        "REQUIRES_PDF_AUTHORITY",
                        "requires_pdf must originate in the official venue layer",
                    )
                if not isinstance(entry["value"], bool):
                    _fail("REQUIRES_PDF_TYPE", "requires_pdf must be a boolean")
                if entry["classification"] != "HARD" or entry["weakenable"]:
                    _fail(
                        "REQUIRES_PDF_AUTHORITY",
                        "requires_pdf must be non-weakenable HARD venue policy",
                    )

            if previous and previous["classification"] == "HARD":
                if entry["value"] != previous["value"]:
                    _fail(
                        "HARD_RULE_OVERRIDE",
                        f"hard token {token!r} cannot be changed by {layer}",
                    )
                if entry["classification"] != "HARD":
                    _fail(
                        "HARD_RULE_RECLASSIFICATION",
                        f"hard token {token!r} cannot be reclassified by {layer}",
                    )
                if entry["weakenable"]:
                    _fail(
                        "HARD_RULE_WEAKENING",
                        f"hard token {token!r} cannot be weakened by {layer}",
                    )
                histories.setdefault(token, []).append(
                    {
                        "layer": layer,
                        "source_ref": entry["source_ref"],
                        "source_sha256": entry["source_sha256"],
                        "classification": "HARD",
                        "weakenable": False,
                        "prior_value": copy.deepcopy(previous["value"]),
                        "value": copy.deepcopy(entry["value"]),
                        "accepted_noop": True,
                    }
                )
                continue

            if previous and previous["classification"] != entry["classification"]:
                if layer != "venue" or entry["classification"] != "HARD":
                    _fail(
                        "TOKEN_RECLASSIFICATION",
                        f"token {token!r} cannot be reclassified by {layer}",
                    )
            if previous is None and layer in {"project", "run"} and entry[
                "classification"
            ] == "HARD":
                _fail(
                    "LOWER_LAYER_HARD_RULE",
                    f"{layer} cannot introduce hard token {token!r}",
                )

            prior_value = copy.deepcopy(previous["value"]) if previous else None
            event = {
                "layer": layer,
                "source_ref": entry["source_ref"],
                "source_sha256": entry["source_sha256"],
                "classification": entry["classification"],
                "weakenable": entry["weakenable"],
                "prior_value": prior_value,
                "value": copy.deepcopy(entry["value"]),
                "accepted_noop": False,
            }
            histories.setdefault(token, []).append(event)
            if previous and previous["value"] != entry["value"]:
                caveats.append(
                    {
                        "code": (
                            "OFFICIAL_AUTHORITY_OVERRIDE"
                            if entry["classification"] == "HARD"
                            else "ADVISORY_OVERRIDE"
                        ),
                        "token": token,
                        "from_layer": previous["resolved_layer"],
                        "to_layer": layer,
                        "prior_value": prior_value,
                        "value": copy.deepcopy(entry["value"]),
                        "blocking": False,
                        "daily_state": "USABLE_WITH_CAVEATS",
                    }
                )
            state[token] = {
                **entry,
                "resolved_layer": layer,
            }

    unresolved_mandatory = sorted(token for token in required if token not in state)
    if unresolved_mandatory:
        _fail(
            "UNKNOWN_MANDATORY_TOKEN",
            f"mandatory tokens are unknown or unresolved: {unresolved_mandatory}",
        )
    if not state:
        _fail("EMPTY_TOKEN_SNAPSHOT", "at least one resolved token is required")

    rows = [
        {
            "token": token,
            "value": copy.deepcopy(row["value"]),
            "classification": row["classification"],
            "resolved_layer": row["resolved_layer"],
            "source_ref": row["source_ref"],
            "source_sha256": row["source_sha256"],
            "weakenable": row["weakenable"],
        }
        for token, row in sorted(state.items())
    ]
    snapshot = _token_snapshot(rows)
    provenance = {}
    for token, row in sorted(state.items()):
        history = copy.deepcopy(histories[token])
        provenance[token] = {
            "layer": row["resolved_layer"],
            "source_ref": row["source_ref"],
            "source_sha256": row["source_sha256"],
            "classification": row["classification"],
            "hard": row["classification"] == "HARD",
            "weakenable": row["weakenable"],
            "prior_value": history[-1]["prior_value"],
            "history": history,
        }
    return {
        **copy.deepcopy(snapshot),
        "resolved_tokens": copy.deepcopy(snapshot),
        "resolved": {token: copy.deepcopy(row["value"]) for token, row in sorted(state.items())},
        "provenance": provenance,
        "caveats": caveats,
        "hard_failures": [],
    }


def _load_yaml_mapping(path: Path) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        parsed = yaml.safe_load(raw.decode("utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        _fail("TOKEN_PROFILE_LOAD", f"cannot load {path.name}: {exc}")
    if not isinstance(parsed, Mapping):
        _fail("TOKEN_PROFILE_SHAPE", f"{path.name} must contain a mapping")
    return dict(parsed), hashlib.sha256(raw).hexdigest()


def load_paper_design_token_profiles(
    profile_root: str | Path,
    *,
    paper_type: str,
) -> dict[str, dict[str, Any]]:
    """Load the shipped base, paper-type, and AI-research default overlays."""

    root = Path(profile_root)
    base, base_sha = _load_yaml_mapping(root / "base.yaml")
    typed, typed_sha = _load_yaml_mapping(root / "paper_types.yaml")
    ai_defaults, ai_sha = _load_yaml_mapping(root / "ai_research.yaml")

    paper_types = typed.get("paper_types")
    selected = paper_types.get(paper_type) if isinstance(paper_types, Mapping) else None
    if not isinstance(selected, Mapping):
        _fail("UNKNOWN_PAPER_TYPE", f"paper type {paper_type!r} has no token overlay")

    def document(
        source_name: str,
        source_sha256: str,
        layer: str,
        data: Mapping[str, Any],
    ) -> dict[str, Any]:
        tokens = data.get("tokens")
        if not isinstance(tokens, Mapping):
            _fail("TOKEN_PROFILE_SHAPE", f"{source_name} has no tokens mapping")
        return {
            "layer": layer,
            "source_ref": f"profiles/paper_design_tokens/{source_name}",
            "source_sha256": source_sha256,
            "mandatory_tokens": list(data.get("mandatory_tokens", ())),
            "tokens": copy.deepcopy(dict(tokens)),
        }

    return {
        "base": document("base.yaml", base_sha, "base", base),
        "paper_type": document(
            "paper_types.yaml", typed_sha, "paper_type", selected
        ),
        "project": document(
            "ai_research.yaml", ai_sha, "project", ai_defaults
        ),
    }


def _schema_token_projection(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        _fail("INVALID_TOKEN_SNAPSHOT", "resolved_tokens must be an object")
    candidate: Any = value.get("resolved_tokens", value)
    if not isinstance(candidate, Mapping):
        _fail("INVALID_TOKEN_SNAPSHOT", "resolved token projection must be an object")
    tokens = candidate.get("tokens")
    if not isinstance(tokens, Sequence) or isinstance(tokens, (str, bytes)):
        _fail("INVALID_TOKEN_SNAPSHOT", "resolved token rows must be a list")
    return _token_snapshot(tokens)


def canonical_contract_hash(contract: Mapping[str, Any]) -> str:
    """Hash a contract canonically while excluding its self-referential stamp."""

    if not isinstance(contract, Mapping):
        _fail("INVALID_CONTRACT", "contract must be an object")
    unsigned = copy.deepcopy(dict(contract))
    unsigned.pop("manuscript_snapshot_sha256", None)
    if "resolved_tokens" in unsigned:
        unsigned["resolved_tokens"] = _schema_token_projection(
            unsigned["resolved_tokens"]
        )
    return _canonical_sha256(unsigned)


def freeze_manuscript_contract(
    contract: Mapping[str, Any],
    output_path: str | Path,
    *,
    run_root: str | Path,
    now: datetime,
    max_official_age: timedelta,
    secret_sentinels: Mapping[str, str] | None = None,
    secret_patterns: Mapping[str, str | re.Pattern[str]] | None = None,
) -> dict[str, Any]:
    """Validate, stamp, and atomically freeze a complete manuscript contract."""

    if not isinstance(contract, Mapping):
        _fail("INVALID_CONTRACT", "contract must be an object")
    candidate = copy.deepcopy(dict(contract))
    if "resolved_tokens" in candidate:
        candidate["resolved_tokens"] = _schema_token_projection(
            candidate["resolved_tokens"]
        )

    _validate_official_profile(
        candidate,
        now=now,
        max_official_age=max_official_age,
    )
    _validate_dependency_slice_hashes(candidate)
    candidate["manuscript_snapshot_sha256"] = canonical_contract_hash(candidate)
    schema_errors = validate_payload("manuscript_contract", candidate)
    if schema_errors:
        _fail("SCHEMA_INVALID", "; ".join(schema_errors))

    _validate_outline(candidate)
    _validate_source_closure(candidate)
    candidate["manuscript_snapshot_sha256"] = canonical_contract_hash(candidate)
    final_errors = validate_payload("manuscript_contract", candidate)
    if final_errors:
        _fail("SCHEMA_INVALID", "; ".join(final_errors))

    path_result = validate_run_owned_path(
        output_path,
        run_root=run_root,
        purpose="write",
    )
    target = Path(path_result["path"])
    validate_run_owned_path(
        Path(str(target) + ".tmp"),
        run_root=run_root,
        purpose="write",
    )
    text = _canonical_json(candidate) + "\n"
    patterns = dict(_DEFAULT_SECRET_PATTERNS)
    patterns.update(secret_patterns or {})
    scan_persisted_text(
        "manuscript_contract",
        text,
        sentinels=secret_sentinels,
        patterns=patterns,
    )

    if target.exists():
        try:
            existing = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            _fail(
                "FROZEN_CONTRACT_CONFLICT",
                "existing contract is unreadable and will not be overwritten",
            )
        if existing == candidate:
            return copy.deepcopy(candidate)
        _fail(
            "FROZEN_CONTRACT_CONFLICT",
            "a different contract is already frozen at the target path",
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(target, text)
    return copy.deepcopy(candidate)


def affected_descendants(
    changed_nodes: str | Iterable[str],
    dependency_graph: Mapping[str, Sequence[str]],
) -> list[str]:
    """Return the deterministic transitive closure of explicit consumer edges."""

    if not isinstance(dependency_graph, Mapping):
        _fail("INVALID_DEPENDENCY_GRAPH", "dependency graph must be an object")
    graph: dict[str, list[str]] = {}
    declared_order: list[str] = []
    for source, consumers in dependency_graph.items():
        if not isinstance(source, str) or not isinstance(consumers, Sequence) or isinstance(
            consumers, (str, bytes)
        ):
            _fail("INVALID_DEPENDENCY_GRAPH", "graph edges must be string lists")
        graph[source] = []
        if source not in declared_order:
            declared_order.append(source)
        for consumer in consumers:
            if not isinstance(consumer, str):
                _fail("INVALID_DEPENDENCY_GRAPH", "graph nodes must be strings")
            if consumer not in graph[source]:
                graph[source].append(consumer)
            if consumer not in declared_order:
                declared_order.append(consumer)

    visit_state: dict[str, int] = {}

    def detect_cycle(node: str) -> None:
        if visit_state.get(node) == 1:
            _fail("DEPENDENCY_CYCLE", f"dependency graph contains a cycle at {node!r}")
        if visit_state.get(node) == 2:
            return
        visit_state[node] = 1
        for child in graph.get(node, ()):
            detect_cycle(child)
        visit_state[node] = 2

    for node in declared_order:
        detect_cycle(node)

    changed = {changed_nodes} if isinstance(changed_nodes, str) else set(changed_nodes)
    known = set(declared_order)
    unknown = sorted(changed - known)
    if unknown:
        _fail("UNKNOWN_DEPENDENCY_NODE", f"unknown changed nodes: {unknown}")

    queue = deque(node for node in declared_order if node in changed)
    impacted: set[str] = set()
    while queue:
        current = queue.popleft()
        for consumer in graph.get(current, ()):
            if consumer not in changed and consumer not in impacted:
                impacted.add(consumer)
                queue.append(consumer)
    return [node for node in declared_order if node in impacted]


__all__ = [
    "TOKEN_LAYERS",
    "ManuscriptContractError",
    "affected_descendants",
    "canonical_contract_hash",
    "freeze_manuscript_contract",
    "load_paper_design_token_profiles",
    "resolve_paper_design_tokens",
]
