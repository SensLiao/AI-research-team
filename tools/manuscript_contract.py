"""Deterministic Paper Design Tokens and immutable manuscript contracts.

The resolver deliberately returns two views: the closed-schema token snapshot
used by ``manuscript_contract`` and rich provenance/caveats used by callers for
review evidence.  This keeps the registered JSON Schema authoritative without
discarding the history needed to explain advisory overrides.
"""

from __future__ import annotations

import copy
import hashlib
import re
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import yaml

from research_agent_teams.tools._manuscript_contract_validation import (
    ManuscriptContractError,
    atomic_create_once as _atomic_create_once,
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
from research_agent_teams.tools.validate_artifact import validate_payload


TOKEN_LAYERS = ("base", "paper_type", "venue", "project", "run")

_BASE_HARD_VALUES = {
    "no_fabrication": True,
    "claim_traceability": "claim-number-citation-closure",
    "terminology_consistency": "frozen-glossary-and-notation",
    "asset_provenance": "hashed-source-and-result-refs",
    "compile_integrity": "references-and-cross-references-must-resolve",
    "no_shell_escape": True,
}
_VENUE_HARD_TOKENS = frozenset(
    {
        "anonymity",
        "build_engine",
        "checklist",
        "column_layout",
        "disclosure",
        "page_limit",
        "requires_pdf",
        "submission_format",
        "supplement_policy",
        "template",
    }
)

_DEFAULT_SECRET_PATTERNS = {
    "credential-bearing-url": re.compile(
        r"\b[a-z][a-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@", re.IGNORECASE
    ),
    "authorization-header": re.compile(
        r"\bauthorization\s*:\s*(?:bearer|basic)\s+\S+", re.IGNORECASE
    ),
    "private-key-block": re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----"),
    "secret-assignment": re.compile(
        r"\b(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*"
        r"[\"']?[A-Za-z0-9_./+=-]{12,}",
        re.IGNORECASE,
    ),
}


def _validate_hard_authority(token: str, entry: Mapping[str, Any], layer: str) -> None:
    if layer == "base" and token in _BASE_HARD_VALUES:
        if (
            entry.get("classification") != "HARD"
            or entry.get("weakenable") is not False
            or entry.get("value") != _BASE_HARD_VALUES[token]
        ):
            _fail(
                "BASE_HARD_POLICY",
                f"base truth token {token!r} must retain its locked hard value",
            )
        return
    if entry.get("classification") != "HARD":
        return
    if layer == "venue" and token in _VENUE_HARD_TOKENS:
        return
    _fail(
        "UNAUTHORIZED_HARD_TOKEN",
        f"token {token!r} cannot become HARD in the {layer} layer",
    )


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
    required = {
        "token",
        "value",
        "classification",
        "resolved_layer",
        "source_ref",
        "source_sha256",
        "weakenable",
    }
    for index, row in enumerate(tokens):
        if not isinstance(row, Mapping) or not required.issubset(row):
            _fail(
                "INVALID_TOKEN_SNAPSHOT",
                f"resolved token row {index} is missing required fields",
            )
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

            if not entry.get("delete") and (
                previous is None or previous["classification"] != "HARD"
            ):
                _validate_hard_authority(token, entry, layer)

            if entry.get("delete") is True:
                if token == "requires_pdf" and previous is None:
                    _fail(
                        "REQUIRES_PDF_AUTHORITY",
                        "requires_pdf cannot be introduced as a deletion",
                    )
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
                        "requires_pdf must originate in the venue profile layer",
                    )
                if not isinstance(entry["value"], bool):
                    _fail("REQUIRES_PDF_TYPE", "requires_pdf must be a boolean")
                valid_official = (
                    entry["classification"] == "HARD"
                    and entry["weakenable"] is False
                )
                valid_provisional = (
                    entry["classification"] == "ADVISORY"
                    and entry["weakenable"] is True
                )
                if not (valid_official or valid_provisional):
                    _fail(
                        "REQUIRES_PDF_AUTHORITY",
                        "requires_pdf must be either non-weakenable HARD official "
                        "venue policy or weakenable ADVISORY provisional venue policy",
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
        "resolver_version": "1.0",
        "mandatory_tokens": sorted(required),
        "source_layers": copy.deepcopy(
            {layer: layers[layer] for layer in TOKEN_LAYERS if layer in layers}
        ),
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


def _validated_token_resolution(
    value: Any,
    source_hashes: Any,
    venue_profile: Any,
) -> dict[str, Any]:
    if not isinstance(value, Mapping) or value.get("resolver_version") != "1.0":
        _fail(
            "TOKEN_RESOLUTION_ATTESTATION",
            "freeze requires the rich output of resolve_paper_design_tokens",
        )
    source_layers = value.get("source_layers")
    mandatory_tokens = value.get("mandatory_tokens")
    if not isinstance(source_layers, Mapping) or not isinstance(mandatory_tokens, list):
        _fail(
            "TOKEN_RESOLUTION_ATTESTATION",
            "token resolution is missing replayable source layers",
        )
    replay = resolve_paper_design_tokens(
        source_layers,
        mandatory_tokens=mandatory_tokens,
    )
    comparable_keys = (
        "cascade_order",
        "tokens",
        "snapshot_sha256",
        "resolved_tokens",
        "resolved",
        "provenance",
        "caveats",
        "hard_failures",
    )
    if any(value.get(key) != replay.get(key) for key in comparable_keys):
        _fail(
            "TOKEN_RESOLUTION_TAMPERED",
            "resolved tokens do not match deterministic replay of their source layers",
        )
    replay_tokens = {row["token"]: row for row in replay["tokens"]}
    missing_truth_tokens = sorted(set(_BASE_HARD_VALUES) - set(replay_tokens))
    if missing_truth_tokens:
        _fail(
            "TOKEN_RESOLUTION_ATTESTATION",
            f"base truth-hard tokens are missing: {missing_truth_tokens}",
        )
    for token, expected_value in _BASE_HARD_VALUES.items():
        row = replay_tokens[token]
        if (
            row["value"] != expected_value
            or row["classification"] != "HARD"
            or row["weakenable"] is not False
            or row["resolved_layer"] != "base"
        ):
            _fail(
                "BASE_HARD_POLICY",
                f"base truth token {token!r} was downgraded or moved",
            )

    if not isinstance(source_hashes, Sequence) or isinstance(source_hashes, (str, bytes)):
        _fail("TOKEN_SOURCE_CLOSURE", "source_hashes must freeze token provenance")
    source_index = {
        row.get("ref"): row
        for row in source_hashes
        if isinstance(row, Mapping) and isinstance(row.get("ref"), str)
    }
    official_pairs: set[tuple[str, str]] = set()
    if isinstance(venue_profile, Mapping):
        official_pairs.update(
            (str(row.get("ref")), str(row.get("sha256")))
            for row in venue_profile.get("official_rule_refs", ())
            if isinstance(row, Mapping)
        )
        official_pairs.add(
            (
                str(venue_profile.get("template_ref")),
                str(venue_profile.get("template_sha256")),
            )
        )
    for token, provenance in replay["provenance"].items():
        for event in provenance["history"]:
            source = source_index.get(event["source_ref"])
            if (
                source is None
                or source.get("sha256") != event["source_sha256"]
                or source.get("kind") not in {"TOKEN_OVERLAY", "VENUE_RULE", "TEMPLATE"}
            ):
                _fail(
                    "TOKEN_SOURCE_CLOSURE",
                    f"token {token!r} has unfrozen override provenance",
                )
            if event["layer"] == "venue" and event["classification"] == "HARD":
                if (
                    source.get("kind") not in {"VENUE_RULE", "TEMPLATE"}
                    or (event["source_ref"], event["source_sha256"])
                    not in official_pairs
                ):
                    _fail(
                        "VENUE_HARD_SOURCE",
                        f"venue hard token {token!r} lacks current official authority",
                    )
    return replay


def _validate_result_receipts(
    payload: Mapping[str, Any],
    verifier: Callable[[Mapping[str, Any]], Mapping[str, Any]] | None,
) -> None:
    results = payload.get("result_refs")
    if not isinstance(results, Sequence) or isinstance(results, (str, bytes)):
        return
    if results and verifier is None:
        _fail(
            "RESULT_VERIFIER_REQUIRED",
            "frozen result refs require an injected receipt verifier",
        )
    for row in results:
        if not isinstance(row, Mapping):
            continue
        try:
            facts = verifier(copy.deepcopy(dict(row))) if verifier else None
        except Exception:
            _fail(
                "RESULT_RECEIPT_UNVERIFIED",
                "the injected verifier rejected a result receipt",
            )
        expected = {
            "verified": True,
            "result_ref": row.get("ref"),
            "result_sha256": row.get("sha256"),
            "receipt_ref": row.get("receipt_ref"),
            "receipt_sha256": row.get("receipt_sha256"),
        }
        if (
            not isinstance(facts, Mapping)
            or facts.get("verified") is not True
            or any(
                facts.get(key) != expected_value
                for key, expected_value in expected.items()
                if key != "verified"
            )
        ):
            _fail(
                "RESULT_RECEIPT_UNVERIFIED",
                f"result {row.get('ref')!r} lacks matching verified receipt facts",
            )


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
    result_receipt_verifier: (
        Callable[[Mapping[str, Any]], Mapping[str, Any]] | None
    ) = None,
    secret_sentinels: Mapping[str, str] | None = None,
    secret_patterns: Mapping[str, str | re.Pattern[str]] | None = None,
) -> dict[str, Any]:
    """Validate, stamp, and atomically freeze a complete manuscript contract."""

    if not isinstance(contract, Mapping):
        _fail("INVALID_CONTRACT", "contract must be an object")
    candidate = copy.deepcopy(dict(contract))
    for required in ("paper_type", "north_star", "source_hashes"):
        if required not in candidate:
            _fail("SCHEMA_INVALID", f"required contract field {required!r} is missing")
    _validate_official_profile(
        candidate,
        now=now,
        max_official_age=max_official_age,
    )
    resolution = _validated_token_resolution(
        candidate.get("resolved_tokens"),
        candidate.get("source_hashes"),
        candidate.get("venue_profile"),
    )
    candidate["resolved_tokens"] = copy.deepcopy(resolution["resolved_tokens"])
    _validate_result_receipts(candidate, result_receipt_verifier)
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
    text = _canonical_json(candidate) + "\n"
    patterns = dict(_DEFAULT_SECRET_PATTERNS)
    patterns.update(secret_patterns or {})
    scan_persisted_text(
        "manuscript_contract",
        text,
        sentinels=secret_sentinels,
        patterns=patterns,
    )

    return _atomic_create_once(target, text, candidate, run_root=run_root)


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
