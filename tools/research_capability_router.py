"""Deterministic, non-executing capability-overlay selector.

The research orchestrator remains the single operational entry point.  This
module only recommends an existing orchestrator mode and two-to-five internal
quality overlays.  The overlays are short clean-room summaries bound to an
audited source commit; third-party skill bodies are never imported or run.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Optional

from research_agent_teams.orchestrator.graph_spec import load_mode_registry
from research_agent_teams.tools.mechanism_council import plan_council
from research_agent_teams.tools import research_plan
from research_agent_teams.tools.path_boundaries import assert_not_vault_path

_PKG_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OVERLAY_CATALOG = _PKG_ROOT / "orchestrator" / "research_capability_overlays.json"
DEFAULT_EXTERNAL_SOURCE_LOCK = (
    _PKG_ROOT / "orchestrator" / "external_research_skill_sources.json"
)

PUBLICATION_KINDS = {
    "quantitative_figure",
    "scientific_diagram",
    "manuscript_methods",
    "manuscript_review",
}

_PUBLICATION_ALIASES = {
    "figure": "quantitative_figure",
    "quantitative-figure": "quantitative_figure",
    "plot": "quantitative_figure",
    "diagram": "scientific_diagram",
    "scientific-diagram": "scientific_diagram",
    "methods": "manuscript_methods",
    "method": "manuscript_methods",
    "manuscript-methods": "manuscript_methods",
    "review": "manuscript_review",
    "peer-review": "manuscript_review",
    "manuscript-review": "manuscript_review",
}

_PUBLICATION_MODE_PREFERENCES: dict[str, tuple[str, ...]] = {
    "quantitative_figure": ("analysis_audit_panel", "manuscript_authoring"),
    "scientific_diagram": ("manuscript_authoring",),
    "manuscript_methods": ("manuscript_authoring", "design_experiment"),
    "manuscript_review": ("manuscript_review", "venue_readiness"),
}

# Intent and tier membership come only from plan_catalog.yaml.  These phrases
# merely disambiguate two operated modes that the same intent deliberately
# places in its tier menu; they can never admit a mode outside that catalog.
_TIER_MODE_SIGNALS: dict[str, tuple[str, ...]] = {
    "gap_breadth": ("扫空白", "扫一遍空白点", "空白点", "gap scan", "white space"),
    "ingest_paper": ("收进库", "收论文", "论文入库", "ingest paper"),
    "read_paper_deep": ("精读", "深读", "拆解方法", "read this paper", "deep read"),
    "manuscript_authoring": (
        "写论文", "写稿", "起草论文", "写初稿", "write the paper", "draft the paper",
        "author manuscript",
    ),
    "manuscript_review": (
        "审稿", "审一遍", "同行评审", "返修", "peer review", "review my manuscript",
        "rebuttal",
    ),
}

_DEFAULT_OPERATED_FALLBACK = "deep_research"

_FALLBACK_OVERLAYS: tuple[str, ...] = (
    "results_to_claim_contract",
    "blind_handoff_contract",
    "hypothesis_prediction_contract",
    "power_unit_of_analysis_contract",
    "submission_freshness_contract",
)


class ResearchCapabilityRouterError(ValueError):
    """Raised when a mode request or overlay catalog is invalid."""


#: The SAFETY half of the catalog policy: pinned by equality, never negotiable. These are the
#: read-never-execute boundary, so a catalog that weakens any of them is rejected outright.
_REQUIRED_SAFETY_POLICY: dict[str, Any] = {
    "network_default": "DENY",
    "external_execution": False,
    "copy_third_party_code": False,
    "copy_third_party_long_text": False,
}

#: The VOLUME half is a window, not a constant. It used to be pinned to selection_min=2 /
#: selection_max=5 by equality here AND in the in-memory validator AND in task_frame.schema.json
#: AND by a literal in two tests -- four locks agreeing that at most five method lenses could ever
#: reach a worker, no matter how large the catalog grew. That is why the 358 vendored upstream
#: bundles felt unreachable. Widening is now a one-line catalog edit; only sanity is enforced.
#: Raised 24 -> 28 on 2026-08-07 when the catalog gained the four innovation/rigor cards
#: (creative_operator_ladder, ai_research_failure_modes, productive_disagreement_council,
#: innovation_cognitive_map). The ceiling must stay >= the catalog's selection_max AND
#: <= task_frame.schema.json /capability_overlay_plan/overlays maxItems -- three places, one number.
_SELECTION_WINDOW_CEILING = 28


def _check_selection_window(policy: dict[str, Any]) -> None:
    """Validate the selection window as a window: sane, ordered, and bounded -- not pinned."""
    try:
        low = int(policy["selection_min"])
        high = int(policy["selection_max"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ResearchCapabilityRouterError(
            "catalog policy needs integer selection_min and selection_max"
        ) from exc
    if low < 1:
        raise ResearchCapabilityRouterError("selection_min must be at least 1")
    if high < low:
        raise ResearchCapabilityRouterError("selection_max must be >= selection_min")
    if high > _SELECTION_WINDOW_CEILING:
        raise ResearchCapabilityRouterError(
            f"selection_max {high} exceeds the structural ceiling {_SELECTION_WINDOW_CEILING}; "
            "raise task_frame.schema.json /capability_overlay_plan/overlays maxItems first"
        )


def _load_json(path: str | Path, *, kind: str) -> dict[str, Any]:
    candidate = Path(path)
    if not candidate.is_file():
        raise ResearchCapabilityRouterError(f"{kind} not found: {candidate}")
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ResearchCapabilityRouterError(f"cannot read UTF-8 {kind}: {candidate}") from exc
    if not isinstance(value, dict):
        raise ResearchCapabilityRouterError(f"{kind} must be a JSON object")
    return value


def _is_repository_relative_path(value: Any) -> bool:
    if not isinstance(value, str) or not value or "\\" in value:
        return False
    candidate = PurePosixPath(value)
    return not candidate.is_absolute() and ".." not in candidate.parts


def _validate_source_records(sources: Any, *, context: str) -> dict[str, dict[str, Any]]:
    if not isinstance(sources, list) or not sources:
        raise ResearchCapabilityRouterError(f"{context} requires a non-empty sources list")
    source_by_id: dict[str, dict[str, Any]] = {}
    text_fields = (
        "source_id",
        "repository",
        "commit",
        "snapshot_dir",
        "license_status",
        "license_spdx",
        "copy_policy",
        "commercial_use_policy",
        "admission",
        "implementation_status",
    )
    allowed_implementation_statuses = {"guidance_only", "planned_adapter", "rejected"}
    for source in sources:
        if not isinstance(source, dict):
            raise ResearchCapabilityRouterError(f"every {context} source must be an object")
        for field in text_fields:
            if not isinstance(source.get(field), str) or not source[field].strip():
                raise ResearchCapabilityRouterError(
                    f"every {context} source requires non-empty {field}"
                )
        source_id = source["source_id"]
        if source_id in source_by_id:
            raise ResearchCapabilityRouterError(f"duplicate source_id in {context}: {source_id}")
        if not source["repository"].startswith("https://github.com/"):
            raise ResearchCapabilityRouterError(
                f"source {source_id} lacks an official repository URL"
            )
        if not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
            raise ResearchCapabilityRouterError(f"source {source_id} lacks a pinned commit")
        if not _is_repository_relative_path(source["snapshot_dir"]):
            raise ResearchCapabilityRouterError(
                f"source {source_id} has an invalid snapshot_dir"
            )
        if not isinstance(source.get("skill_count"), int) or source["skill_count"] < 1:
            raise ResearchCapabilityRouterError(
                f"source {source_id} requires a positive skill_count"
            )
        if not isinstance(source.get("selectable"), bool):
            raise ResearchCapabilityRouterError(f"source {source_id} requires selectable boolean")
        if not isinstance(source.get("attribution_required"), bool):
            raise ResearchCapabilityRouterError(
                f"source {source_id} requires attribution_required boolean"
            )
        if source["implementation_status"] not in allowed_implementation_statuses:
            raise ResearchCapabilityRouterError(
                f"source {source_id} has invalid implementation_status"
            )
        if (source["implementation_status"] == "rejected") == source["selectable"]:
            raise ResearchCapabilityRouterError(
                f"source {source_id} rejected/selectable state is inconsistent"
            )
        license_file = source.get("license_file")
        if license_file is not None and not _is_repository_relative_path(license_file):
            raise ResearchCapabilityRouterError(
                f"source {source_id} has an invalid license_file"
            )
        artifacts = source.get("source_artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            raise ResearchCapabilityRouterError(
                f"source {source_id} requires source_artifacts"
            )
        artifact_paths: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict) or set(artifact) != {"path", "sha256", "role"}:
                raise ResearchCapabilityRouterError(
                    f"source {source_id} has an invalid source_artifact object"
                )
            artifact_path = artifact.get("path")
            if not _is_repository_relative_path(artifact_path):
                raise ResearchCapabilityRouterError(
                    f"source {source_id} has an invalid source_artifact path"
                )
            if artifact_path in artifact_paths:
                raise ResearchCapabilityRouterError(
                    f"source {source_id} repeats source_artifact {artifact_path}"
                )
            artifact_paths.add(artifact_path)
            if not re.fullmatch(r"[0-9a-f]{64}", str(artifact.get("sha256") or "")):
                raise ResearchCapabilityRouterError(
                    f"source {source_id} source_artifact lacks SHA-256"
                )
            if not isinstance(artifact.get("role"), str) or not artifact["role"].strip():
                raise ResearchCapabilityRouterError(
                    f"source {source_id} source_artifact lacks role"
                )
        if license_file is not None and license_file not in artifact_paths:
            raise ResearchCapabilityRouterError(
                f"source {source_id} license_file is not hash-locked"
            )
        source_by_id[source_id] = source
    return source_by_id


def load_external_source_lock(
    path: str | Path = DEFAULT_EXTERNAL_SOURCE_LOCK,
) -> dict[str, Any]:
    """Load the immutable nine-repository source and file-hash inventory."""
    source_lock = _load_json(path, kind="external research skill source lock")
    if source_lock.get("schema_version") != "external-research-skill-sources/v1":
        raise ResearchCapabilityRouterError("unsupported external source lock schema")
    if source_lock.get("source_count") != 9 or source_lock.get("skill_count_total") != 359:
        raise ResearchCapabilityRouterError(
            "external source lock must record exactly 9 sources and 359 SKILL.md files"
        )
    source_by_id = _validate_source_records(
        source_lock.get("sources"), context="external source lock"
    )
    if len(source_by_id) != source_lock["source_count"]:
        raise ResearchCapabilityRouterError("external source lock source_count mismatch")
    if sum(source["skill_count"] for source in source_by_id.values()) != source_lock["skill_count_total"]:
        raise ResearchCapabilityRouterError("external source lock skill_count_total mismatch")
    rejected = {source_id for source_id, source in source_by_id.items() if not source["selectable"]}
    if rejected != {"drawio_scientific_illustrator"}:
        raise ResearchCapabilityRouterError(
            "external source lock must retain only drawio_scientific_illustrator as rejected"
        )
    return source_lock


def load_overlay_catalog(
    path: str | Path = DEFAULT_OVERLAY_CATALOG,
    *,
    source_lock_path: str | Path = DEFAULT_EXTERNAL_SOURCE_LOCK,
) -> dict[str, Any]:
    """Load and structurally verify the local metadata-only overlay catalog."""
    catalog = _load_json(path, kind="overlay catalog")
    source_lock = load_external_source_lock(source_lock_path)
    policy = catalog.get("policy")
    sources = catalog.get("sources")
    overlays = catalog.get("overlays")
    if not isinstance(policy, dict) or not isinstance(sources, list) or not isinstance(overlays, list):
        raise ResearchCapabilityRouterError("catalog requires policy, sources, and overlays")
    for key, expected in _REQUIRED_SAFETY_POLICY.items():
        if policy.get(key) != expected:
            raise ResearchCapabilityRouterError(f"unsafe or invalid catalog policy: {key}")
    _check_selection_window(policy)
    forbidden = set(policy.get("forbidden_actions") or [])
    expected_forbidden = {"installer", "hook", "mcp", "auto_update", "whole_repo_execution"}
    if not expected_forbidden.issubset(forbidden):
        raise ResearchCapabilityRouterError("catalog policy is missing forbidden actions")

    source_by_id = _validate_source_records(sources, context="overlay catalog")
    locked_by_id = {
        source["source_id"]: source for source in source_lock["sources"]
    }
    if set(source_by_id) != set(locked_by_id):
        raise ResearchCapabilityRouterError("overlay catalog sources differ from source lock")
    for source_id, source in source_by_id.items():
        if source != locked_by_id[source_id]:
            raise ResearchCapabilityRouterError(
                f"overlay catalog source {source_id} differs from source lock"
            )
    source_ids = set(source_by_id)
    selectable_source_ids = {
        source_id for source_id, source in source_by_id.items() if source["selectable"]
    }

    overlay_ids: set[str] = set()
    for overlay in overlays:
        if not isinstance(overlay, dict):
            raise ResearchCapabilityRouterError("every overlay must be an object")
        overlay_id = overlay.get("overlay_id")
        if not isinstance(overlay_id, str) or not overlay_id:
            raise ResearchCapabilityRouterError("every overlay requires an overlay_id")
        if overlay_id in overlay_ids:
            raise ResearchCapabilityRouterError(f"duplicate overlay_id: {overlay_id}")
        overlay_ids.add(overlay_id)
        refs = overlay.get("provenance_refs")
        if not isinstance(refs, list) or not refs or any(ref not in source_ids for ref in refs):
            raise ResearchCapabilityRouterError(f"overlay {overlay_id} has invalid provenance_refs")
        rejected_refs = sorted(set(refs) - selectable_source_ids)
        if rejected_refs:
            raise ResearchCapabilityRouterError(
                f"overlay {overlay_id} references non-selectable sources: {rejected_refs}"
            )
        if not isinstance(overlay.get("summary"), str) or not overlay["summary"].strip():
            raise ResearchCapabilityRouterError(f"overlay {overlay_id} lacks a summary")
    return catalog


def _validate_in_memory_overlay_catalog(catalog: Mapping[str, Any]) -> dict[str, Any]:
    """Apply the disk-catalog trust boundary to caller-supplied metadata.

    The A/B evaluator passes an in-memory catalog.  It must not become a path
    around the commit/source/selectability checks enforced by
    :func:`load_overlay_catalog`.
    """
    value = dict(catalog)
    policy = value.get("policy")
    sources = value.get("sources")
    overlays = value.get("overlays")
    if not isinstance(policy, dict) or not isinstance(sources, list) or not isinstance(overlays, list):
        raise ResearchCapabilityRouterError("catalog requires policy, sources, and overlays")
    for key, expected in _REQUIRED_SAFETY_POLICY.items():
        if policy.get(key) != expected:
            raise ResearchCapabilityRouterError(f"unsafe or invalid catalog policy: {key}")
    _check_selection_window(policy)
    expected_forbidden = {"installer", "hook", "mcp", "auto_update", "whole_repo_execution"}
    if not expected_forbidden.issubset(set(policy.get("forbidden_actions") or [])):
        raise ResearchCapabilityRouterError("catalog policy is missing forbidden actions")

    source_by_id = _validate_source_records(sources, context="overlay catalog")
    locked = load_external_source_lock()
    locked_by_id = {row["source_id"]: row for row in locked["sources"]}
    if set(source_by_id) != set(locked_by_id):
        raise ResearchCapabilityRouterError("overlay catalog sources differ from source lock")
    for source_id, source in source_by_id.items():
        if source != locked_by_id[source_id]:
            raise ResearchCapabilityRouterError(
                f"overlay catalog source {source_id} differs from source lock"
            )

    selectable = {
        source_id for source_id, source in source_by_id.items() if source["selectable"]
    }
    overlay_ids: set[str] = set()
    for overlay in overlays:
        if not isinstance(overlay, dict):
            raise ResearchCapabilityRouterError("every overlay must be an object")
        overlay_id = overlay.get("overlay_id")
        if not isinstance(overlay_id, str) or not overlay_id:
            raise ResearchCapabilityRouterError("every overlay requires an overlay_id")
        if overlay_id in overlay_ids:
            raise ResearchCapabilityRouterError(f"duplicate overlay_id: {overlay_id}")
        overlay_ids.add(overlay_id)
        refs = overlay.get("provenance_refs")
        if not isinstance(refs, list) or not refs or any(ref not in source_by_id for ref in refs):
            raise ResearchCapabilityRouterError(f"overlay {overlay_id} has invalid provenance_refs")
        rejected_refs = sorted(set(refs) - selectable)
        if rejected_refs:
            raise ResearchCapabilityRouterError(
                f"overlay {overlay_id} references non-selectable sources: {rejected_refs}"
            )
        if not isinstance(overlay.get("summary"), str) or not overlay["summary"].strip():
            raise ResearchCapabilityRouterError(f"overlay {overlay_id} lacks a summary")
    return value


def _normalize_publication_kind(publication_kind: Optional[str]) -> Optional[str]:
    if publication_kind is None:
        return None
    normalized = publication_kind.strip().lower().replace(" ", "_")
    normalized = _PUBLICATION_ALIASES.get(normalized, normalized)
    if normalized not in PUBLICATION_KINDS:
        raise ResearchCapabilityRouterError(
            f"unknown publication_kind {publication_kind!r}; valid: {sorted(PUBLICATION_KINDS)}"
        )
    return normalized


def _mode_honesty(mode: str, spec: Mapping[str, Any]) -> dict[str, Any]:
    if spec.get("operated") is True:
        return {
            "state": "operated",
            "one_button_operable": True,
            "reason": "mode_registry marks this mode operated",
        }
    maturity = spec.get("product_maturity")
    maturity = maturity if isinstance(maturity, dict) else {}
    return {
        "state": "spec_only",
        "one_button_operable": False,
        "maturity_level": str(maturity.get("level") or "registry_routable_spec_only"),
        "reason": str(
            maturity.get("reason")
            or "mode is registry-routable but is not marked operated"
        ),
    }


def _operated_mode_names(modes: Mapping[str, Any]) -> set[str]:
    return {
        str(mode)
        for mode, spec in modes.items()
        if isinstance(spec, Mapping) and spec.get("operated") is True
    }


def _tier_id_for_mode(tiers: list[dict[str, Any]], mode: str,
                      preferred: Optional[Mapping[str, Any]]) -> Optional[str]:
    if preferred and mode in (preferred.get("modes") or []):
        return str(preferred.get("id") or "") or None
    for tier in tiers:
        if mode in (tier.get("modes") or []):
            return str(tier.get("id") or "") or None
    return None


def resolve_operated_mode(
    request_text: str,
    *,
    intent: Optional[str] = None,
    publication_kind: Optional[str] = None,
    registry: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Resolve the one operated mode that ``begin --mode auto`` may start.

    ``plan_catalog.yaml`` owns natural-language intent matching and the tier
    menu.  This resolver chooses only among operated modes admitted by that
    matched intent.  Small mode signals disambiguate modes inside the same
    catalog menu (for example, manuscript writing versus manuscript review).
    A spec-only mode is never returned by automatic routing.
    """
    request = str(request_text or "").strip()
    if not request:
        raise ResearchCapabilityRouterError("request_text must be non-empty")
    normalized_kind = _normalize_publication_kind(publication_kind)
    registry_doc = dict(registry) if registry is not None else load_mode_registry()
    modes = registry_doc.get("modes")
    if not isinstance(modes, Mapping) or not modes:
        raise ResearchCapabilityRouterError("mode registry requires a non-empty modes mapping")
    operated = _operated_mode_names(modes)
    if not operated:
        raise ResearchCapabilityRouterError("mode registry has no operated modes")

    # Publication output types are a secondary entry surface.  Their ordered
    # preferences are filtered through the same operated-only boundary.
    if normalized_kind:
        for preferred in _PUBLICATION_MODE_PREFERENCES[normalized_kind]:
            if preferred in operated:
                return {
                    "mode": preferred,
                    "intent": None,
                    "tier": None,
                    "matched": True,
                    "candidate_modes": [preferred],
                    "matched_signals": [f"publication_kind:{normalized_kind}"],
                    "proposal": None,
                }

    try:
        proposal = research_plan.propose_for_request(request, intent=intent)
    except (KeyError, OSError, ValueError) as exc:
        raise ResearchCapabilityRouterError(f"cannot resolve plan-catalog intent: {exc}") from exc

    intent_blocks = list(proposal.get("intents") or [])
    matched = bool(proposal.get("matched"))
    if not matched or not intent_blocks:
        fallback = _DEFAULT_OPERATED_FALLBACK if _DEFAULT_OPERATED_FALLBACK in operated else sorted(operated)[0]
        return {
            "mode": fallback,
            "intent": None,
            "tier": None,
            "matched": False,
            "candidate_modes": [fallback],
            "matched_signals": ["plan_catalog:unmatched", "operated_fallback"],
            "proposal": proposal,
        }

    intent_block = intent_blocks[0]
    intent_id = str(intent_block.get("intent") or "")
    tiers = [tier for tier in (intent_block.get("tiers") or []) if isinstance(tier, dict)]
    preferred_tier = research_plan.recommended_tier(tiers)
    admitted_in_order: list[str] = []
    for tier in tiers:
        for mode in tier.get("modes") or []:
            if mode in operated and mode not in admitted_in_order:
                admitted_in_order.append(mode)
    if not admitted_in_order:
        raise ResearchCapabilityRouterError(
            f"plan-catalog intent {intent_id!r} has no operated mode in the live registry"
        )

    text = request.casefold()
    signal_matches: list[tuple[int, int, str, list[str]]] = []
    for order, (mode, phrases) in enumerate(_TIER_MODE_SIGNALS.items()):
        if mode not in admitted_in_order:
            continue
        hits = [phrase for phrase in phrases if phrase.casefold() in text]
        if hits:
            signal_matches.append((sum(len(hit) for hit in hits), -order, mode, hits))

    if signal_matches:
        _, _, selected_mode, hits = max(signal_matches)
        tier_id = _tier_id_for_mode(tiers, selected_mode, preferred_tier)
        signals = [f"intent:{intent_id}"]
        if tier_id:
            signals.append(f"tier:{tier_id}")
        signals.extend(f"mode_signal:{hit}" for hit in hits)
    else:
        preferred_candidates = [
            mode for mode in ((preferred_tier or {}).get("modes") or []) if mode in operated
        ]
        candidates = preferred_candidates or admitted_in_order
        selected_mode = candidates[-1]
        tier_id = _tier_id_for_mode(tiers, selected_mode, preferred_tier)
        signals = [f"intent:{intent_id}"]
        if tier_id:
            signals.append(f"tier:{tier_id}")
        signals.append("plan_catalog:recommended_operated_mode")

    return {
        "mode": selected_mode,
        "intent": intent_id,
        "tier": tier_id,
        "matched": True,
        "candidate_modes": admitted_in_order,
        "matched_signals": signals,
        "proposal": proposal,
    }


def _select_overlays(
    request_text: str,
    mode: str,
    mode_spec: Mapping[str, Any],
    publication_kind: Optional[str],
    catalog: Mapping[str, Any],
) -> list[dict[str, Any]]:
    text = request_text.casefold()
    scored: list[tuple[int, int, str, dict[str, Any], list[str]]] = []
    for overlay in catalog["overlays"]:
        declared_kinds = set(overlay.get("publication_kinds") or [])
        if publication_kind and declared_kinds and publication_kind not in declared_kinds:
            # A generic mode match must not leak a diagram-only adapter into a
            # quantitative-figure request (or vice versa).
            continue
        reasons: list[str] = []
        score = 0
        if mode in (overlay.get("modes") or []):
            score += 35
            reasons.append(f"mode:{mode}")
        if publication_kind and publication_kind in (overlay.get("publication_kinds") or []):
            score += 55
            reasons.append(f"publication_kind:{publication_kind}")
        keyword_hits = [
            str(keyword)
            for keyword in (overlay.get("keywords") or [])
            if str(keyword).casefold() in text
        ]
        if keyword_hits:
            score += min(36, 12 * len(keyword_hits))
            reasons.append("keywords:" + ",".join(keyword_hits[:3]))
        entry_stage = str(mode_spec.get("entry_stage") or "")
        if entry_stage and entry_stage in (overlay.get("stages") or []):
            score += 3
        if score:
            scored.append(
                (
                    score,
                    int(overlay.get("priority") or 0),
                    str(overlay["overlay_id"]),
                    overlay,
                    reasons,
                )
            )

    scored.sort(key=lambda row: (-row[0], -row[1], row[2]))
    chosen: list[tuple[dict[str, Any], list[str]]] = [
        (row[3], row[4]) for row in scored[: int(catalog["policy"]["selection_max"])]
    ]
    chosen_ids = {item[0]["overlay_id"] for item in chosen}
    by_id = {item["overlay_id"]: item for item in catalog["overlays"]}
    for overlay_id in _FALLBACK_OVERLAYS:
        if len(chosen) >= int(catalog["policy"]["selection_min"]):
            break
        if overlay_id not in chosen_ids and overlay_id in by_id:
            chosen.append((by_id[overlay_id], ["minimum_safe_overlay_set"]))
            chosen_ids.add(overlay_id)

    minimum = int(catalog["policy"]["selection_min"])
    maximum = int(catalog["policy"]["selection_max"])
    if not minimum <= len(chosen) <= maximum:
        raise ResearchCapabilityRouterError(
            f"overlay selection must contain {minimum}-{maximum} items; got {len(chosen)}"
        )

    source_by_id = {source["source_id"]: source for source in catalog["sources"]}
    selected: list[dict[str, Any]] = []
    for overlay, reasons in chosen:
        selected.append(
            {
                "overlay_id": overlay["overlay_id"],
                "title": overlay["title"],
                "summary": overlay["summary"],
                "stages": list(overlay.get("stages") or []),
                "selection_reasons": reasons,
                "allowed_use": overlay["allowed_use"],
                "non_goals": list(overlay.get("non_goals") or []),
                "provenance": [
                    {
                        "source_id": source_by_id[source_id]["source_id"],
                        "repository": source_by_id[source_id]["repository"],
                        "commit": source_by_id[source_id]["commit"],
                        "snapshot_dir": source_by_id[source_id]["snapshot_dir"],
                        "skill_count": source_by_id[source_id]["skill_count"],
                        "license_status": source_by_id[source_id]["license_status"],
                        "license_spdx": source_by_id[source_id]["license_spdx"],
                        "license_file": source_by_id[source_id]["license_file"],
                        "copy_policy": source_by_id[source_id]["copy_policy"],
                        "commercial_use_policy": source_by_id[source_id]["commercial_use_policy"],
                        "attribution_required": source_by_id[source_id]["attribution_required"],
                        "admission": source_by_id[source_id]["admission"],
                        "selectable": source_by_id[source_id]["selectable"],
                        "implementation_status": source_by_id[source_id]["implementation_status"],
                        "source_artifacts": [
                            dict(artifact)
                            for artifact in source_by_id[source_id]["source_artifacts"]
                        ],
                    }
                    for source_id in overlay["provenance_refs"]
                ],
            }
        )
    return selected


def route_research_capabilities(
    request_text: str,
    *,
    explicit_mode: Optional[str] = None,
    intent: Optional[str] = None,
    publication_kind: Optional[str] = None,
    registry: Optional[Mapping[str, Any]] = None,
    overlay_catalog: Optional[Mapping[str, Any]] = None,
    manual_council_roles: Optional[list[str]] = None,
    force_council: Optional[bool] = None,
) -> dict[str, Any]:
    """Recommend one existing mode plus a bounded set of safe overlays.

    This function has no network, process, installer, hook, MCP, update, or
    third-party import path.  It performs metadata selection only.
    """
    request = str(request_text or "").strip()
    if not request:
        raise ResearchCapabilityRouterError("request_text must be non-empty")
    normalized_kind = _normalize_publication_kind(publication_kind)
    registry_doc = dict(registry) if registry is not None else load_mode_registry()
    modes = registry_doc.get("modes")
    if not isinstance(modes, Mapping) or not modes:
        raise ResearchCapabilityRouterError("mode registry requires a non-empty modes mapping")

    catalog = (
        _validate_in_memory_overlay_catalog(overlay_catalog)
        if overlay_catalog is not None
        else load_overlay_catalog()
    )

    resolution: Optional[dict[str, Any]] = None
    if explicit_mode is not None:
        selected_mode = explicit_mode.strip()
        if selected_mode not in modes:
            raise ResearchCapabilityRouterError(
                f"unknown explicit mode {selected_mode!r}; known: {sorted(modes)}"
            )
        selection_source = "manual_override"
        matched_signals = [f"explicit_mode:{selected_mode}"]
    else:
        resolution = resolve_operated_mode(
            request,
            intent=intent,
            publication_kind=normalized_kind,
            registry=registry_doc,
        )
        selected_mode = resolution["mode"]
        matched_signals = list(resolution["matched_signals"])
        selection_source = "automatic_suggestion"

    mode_spec = modes[selected_mode]
    overlays = _select_overlays(
        request,
        selected_mode,
        mode_spec,
        normalized_kind,
        catalog,
    )
    policy = catalog["policy"]
    return {
        "contract_version": "research-capability-route/v1",
        "request_text": request,
        "publication_kind": normalized_kind,
        "routing": {
            "mode": selected_mode,
            "selection_source": selection_source,
            "matched_signals": matched_signals,
            "intent": resolution.get("intent") if resolution else None,
            "tier": resolution.get("tier") if resolution else None,
            "honesty": _mode_honesty(selected_mode, mode_spec),
            "note": "Routing is a recommendation; it does not execute the selected mode.",
        },
        "capability_overlays": overlays,
        "mechanism_council_plan": plan_council(
            request,
            manual_roles=manual_council_roles,
            force=force_council,
        ),
        "safety": {
            "network_default": policy["network_default"],
            "external_execution": False,
            "third_party_code_copied": False,
            "third_party_long_text_copied": False,
            "forbidden_actions": sorted(set(policy["forbidden_actions"])),
            "side_effects": [],
        },
    }


def render_route_json(route: Mapping[str, Any], *, indent: int = 2) -> str:
    """Serialize a route without ASCII-escaping Chinese or other Unicode text."""
    return json.dumps(route, ensure_ascii=False, indent=indent, sort_keys=False)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Suggest one RAT mode and safe provenance-bound capability overlays."
    )
    parser.add_argument("request", help="Natural-language research request (UTF-8).")
    parser.add_argument("--mode", dest="explicit_mode", help="Explicit existing mode; overrides auto routing.")
    parser.add_argument("--intent", help="Optional plan-catalog intent override for automatic routing.")
    parser.add_argument("--publication-kind", choices=sorted(PUBLICATION_KINDS))
    parser.add_argument(
        "--council-role",
        action="append",
        dest="council_roles",
        help="Manual mechanism-council role override; dependencies are added automatically.",
    )
    parser.add_argument(
        "--council",
        choices=("auto", "on", "off"),
        default="auto",
        help="Optional mechanism-council activation override.",
    )
    parser.add_argument("--out", help="Optional UTF-8 JSON output path outside the knowledge vault.")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)
    force_council = None if args.council == "auto" else args.council == "on"
    route = route_research_capabilities(
        args.request,
        explicit_mode=args.explicit_mode,
        intent=args.intent,
        publication_kind=args.publication_kind,
        manual_council_roles=args.council_roles,
        force_council=force_council,
    )
    payload = render_route_json(route, indent=args.indent) + "\n"
    if args.out:
        out = assert_not_vault_path(args.out, purpose="write capability route")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_EXTERNAL_SOURCE_LOCK",
    "DEFAULT_OVERLAY_CATALOG",
    "PUBLICATION_KINDS",
    "ResearchCapabilityRouterError",
    "load_external_source_lock",
    "load_overlay_catalog",
    "main",
    "render_route_json",
    "resolve_operated_mode",
    "route_research_capabilities",
]
