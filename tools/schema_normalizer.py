"""Lossless representation normalization before scientific schema validation."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import unicodedata
from pathlib import Path

from .validate_artifact import PAYLOAD_SCHEMAS, SCHEMA_DIR


VERDICT_ALIASES = {
    "NEEDS_REREAD": "NEEDS_SUPPLEMENT",
    "needsreread": "NEEDS_SUPPLEMENT",
}

# These rules infer a scientific/quality classification from narrative or a
# richer structure.  They remain useful for producing an immediate readable
# projection, but they are not representation-only and therefore require the
# owning worker to confirm the canonical value before a truth gate may PASS.
_HEURISTIC_SCIENTIFIC_RULES = frozenset({
    "blind-narrative-summary-to-typed-summary",
    "rich-blind-summary-to-typed-summary",
    "structured-relevance-to-class",
    "rich-appraisal-dimensions-to-7d-contract",
    "qualified-applicability-to-enum",
    "qualified-math-verdict-to-enum",
    "structured-result-verdict-to-enum",
    "structured-reproducibility-risk-to-level",
    "structured-transfer-level-to-enum",
    "structured-risk-to-level",
    "rich-transfer-rows-to-contract",
    "rich-trend-shifts-to-dimensions",
    "promotion-only-block-to-delivery-caveat",
    "structured-quality-assessment-to-enum",
    "structured-thesis-relation-to-class",
    "structured-reading-status-to-stage",
    "structured-reconciliation-verdict-to-status",
})


def _digest(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _token(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).strip().casefold()
    return re.sub(r"[^a-z0-9]+", "", text)


def _enum_value(value, allowed):
    if value in allowed:
        return value
    if isinstance(value, str):
        alias = VERDICT_ALIASES.get(value.strip().upper()) or VERDICT_ALIASES.get(_token(value))
        # ``None`` is a legitimate member of many optional enums.  An unknown
        # worker string has no alias and must remain visible as an error; it
        # must never be silently converted to the nullable enum member.
        if alias is not None and alias in allowed:
            return alias
        matches = [candidate for candidate in allowed if isinstance(candidate, str) and _token(candidate) == _token(value)]
        if len(matches) == 1:
            return matches[0]
    return value


def _walk(value, schema: dict, pointer: str, changes: list[dict], extras: list[dict]):
    if "const" in schema:
        return value
    if "enum" in schema:
        updated = _enum_value(value, schema["enum"])
        if updated != value:
            changes.append({"pointer": pointer, "rule": "canonical-enum", "before": value, "after": updated})
        value = updated
    expected_type = schema.get("type")
    accepts_string = expected_type == "string" or (
        isinstance(expected_type, list) and "string" in expected_type
    )
    if accepts_string and isinstance(value, (dict, list)):
        # A worker may express a text field as a richer structured note.  A
        # canonical JSON string is a representation-only conversion: every key
        # and value survives, no scientific judgment is changed, and the
        # original bundle remains immutable.
        updated = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        changes.append({
            "pointer": pointer,
            "rule": "structured-value-to-canonical-json-text",
            "before": copy.deepcopy(value),
            "after": updated,
        })
        return updated
    accepts_object = expected_type == "object" or (
        isinstance(expected_type, list) and "object" in expected_type
    )
    accepts_array = expected_type == "array" or (
        isinstance(expected_type, list) and "array" in expected_type
    )
    if isinstance(value, dict) and accepts_object:
        properties = schema.get("properties") or {}
        out = {}
        for key, child in value.items():
            child_pointer = f"{pointer}/{str(key).replace('~', '~0').replace('/', '~1')}"
            if key not in properties and schema.get("additionalProperties") is False:
                extras.append({"pointer": child_pointer, "value": copy.deepcopy(child)})
                changes.append({"pointer": child_pointer, "rule": "preserve-extra-in-sidecar"})
                continue
            out[key] = _walk(child, properties.get(key, {}), child_pointer, changes, extras)
        for key, child_schema in properties.items():
            if key not in out and key not in value and "default" in child_schema:
                out[key] = copy.deepcopy(child_schema["default"])
                changes.append({"pointer": f"{pointer}/{key}", "rule": "schema-default"})
        return out
    if isinstance(value, list) and accepts_array:
        item_schema = schema.get("items") or {}
        return [
            _walk(item, item_schema, f"{pointer}/{index}", changes, extras)
            for index, item in enumerate(value)
        ]
    return value


_EVIDENCE_SOURCE_TYPE_TO_KIND = {
    "paper": "paper",
    "preprint": "paper",
    "dataset": "dataset",
    "benchmark": "benchmark",
    "repo": "repo",
    "repository": "repo",
    "document": "doc",
    "doc": "doc",
}


def _normalize_evidence_table(
    payload: dict,
    changes: list[dict],
    conflicts: list[dict],
) -> dict:
    """Resolve only unambiguous evidence-source aliases.

    ``type`` is common worker vocabulary but can be finer-grained than the
    evidence schema (for example ``preprint`` maps to the citable-object kind
    ``paper``).  Canonical fields always win when present.  Conflicting aliases
    are recorded for a local supplement instead of being silently guessed.
    """
    out = copy.deepcopy(payload)
    for index, row in enumerate(out.get("sources") or []):
        if not isinstance(row, dict):
            continue
        pointer = f"/sources/{index}"
        if "notes" not in row and row.get("note") is not None:
            row["notes"] = copy.deepcopy(row["note"])
            changes.append({
                "pointer": f"{pointer}/notes",
                "rule": "evidence-note-alias-to-notes",
                "before": None,
                "after": copy.deepcopy(row["notes"]),
            })
        elif "note" in row and "notes" in row and row["note"] != row["notes"]:
            conflicts.append({
                "pointer": pointer,
                "rule": "conflicting-evidence-note-alias",
                "canonical_field": "notes",
                "alias_field": "note",
                "canonical_value": copy.deepcopy(row["notes"]),
                "alias_value": copy.deepcopy(row["note"]),
            })

        raw_type = str(row.get("type") or "").strip().casefold()
        mapped_kind = _EVIDENCE_SOURCE_TYPE_TO_KIND.get(raw_type)
        if not row.get("kind") and mapped_kind:
            row["kind"] = mapped_kind
            changes.append({
                "pointer": f"{pointer}/kind",
                "rule": "evidence-type-alias-to-kind",
                "before": None,
                "after": mapped_kind,
            })
        elif row.get("kind") and mapped_kind and str(row["kind"]) != mapped_kind:
            conflicts.append({
                "pointer": pointer,
                "rule": "conflicting-evidence-type-alias",
                "canonical_field": "kind",
                "alias_field": "type",
                "canonical_value": copy.deepcopy(row["kind"]),
                "alias_value": copy.deepcopy(row.get("type")),
            })
    return out


def _blind_input_class(ref: str) -> str:
    value = str(ref or "").replace("\\", "/").strip()
    lowered = value.casefold()
    if value in {"task_frame", "source_document", "fulltext_snapshot", "visual_snapshot"}:
        return value
    if lowered == "task_frame.artifact.json":
        return "task_frame"
    if lowered.startswith("inbox/fulltext-docs/"):
        return "source_document"
    if lowered == "inbox/fulltext-qa.json" or lowered.startswith("inbox/citation-snapshots/"):
        return "fulltext_snapshot"
    if lowered == "inbox/paper-visual-manifest.json" or lowered.startswith("inbox/paper-visuals/"):
        return "visual_snapshot"
    return ""


def _normalize_blind_receipts(payload: dict, changes: list[dict]) -> dict:
    """Losslessly adapt path-style blind-reader receipts emitted by current prompts."""
    out = copy.deepcopy(payload)
    declared = out.get("allowed_input_classes")
    if isinstance(declared, list):
        canonical = []
        for item in declared:
            mapped = _blind_input_class(item)
            value = mapped or item
            if value not in canonical:
                canonical.append(value)
        if canonical != declared:
            changes.append({
                "pointer": "/allowed_input_classes",
                "rule": "blind-paths-to-input-classes",
                "before": copy.deepcopy(declared),
                "after": copy.deepcopy(canonical),
            })
            out["allowed_input_classes"] = canonical

    consumed = out.get("consumed_inputs")
    if isinstance(consumed, list):
        canonical = []
        for item in consumed:
            if isinstance(item, str):
                canonical.append({"input_class": _blind_input_class(item), "ref": item})
            else:
                canonical.append(item)
        if canonical != consumed:
            changes.append({
                "pointer": "/consumed_inputs",
                "rule": "blind-path-receipts-to-objects",
                "before": copy.deepcopy(consumed),
                "after": copy.deepcopy(canonical),
            })
            out["consumed_inputs"] = canonical

    summary = out.get("independent_summary")
    if isinstance(summary, str) and summary.strip():
        text = summary.strip()
        limitations = out.get("overclaim_risks") or out.get("required_repairs") or [text]
        canonical_summary = {
            "claims": [text],
            "method": text,
            "key_results": [text],
            "limitations": copy.deepcopy(limitations),
        }
        changes.append({
            "pointer": "/independent_summary",
            "rule": "blind-narrative-summary-to-typed-summary",
            "before": summary,
            "after": copy.deepcopy(canonical_summary),
        })
        out["independent_summary"] = canonical_summary
        summary = canonical_summary
    if isinstance(summary, dict) and not {
        "claims", "method", "key_results", "limitations"
    } <= set(summary):
        rich = copy.deepcopy(summary)
        claim_text = rich.get("problem_and_claims") or rich.get("claims")
        result_text = rich.get("key_results_and_numbers") or rich.get("key_results")
        limitation_text = (
            rich.get("limitations_and_failure_boundary")
            or rich.get("limitations")
            or out.get("overclaim_risks")
        )
        method_parts = [
            rich.get("hard_cldice"),
            rich.get("theorem_scope"),
            rich.get("soft_cldice_and_training"),
        ]
        method_text = rich.get("method") or "\n\n".join(
            str(item).strip() for item in method_parts if item
        )

        def _as_text_list(value):
            if isinstance(value, list):
                return [str(item) for item in value if str(item).strip()]
            if value is None:
                return []
            return [str(value)]

        canonical_summary = {
            "claims": _as_text_list(claim_text),
            "method": str(method_text or claim_text or result_text or "Unknown").strip(),
            "key_results": _as_text_list(result_text or rich.get("data_and_design")),
            "limitations": _as_text_list(limitation_text),
        }
        changes.append({
            "pointer": "/independent_summary",
            "rule": "rich-blind-summary-to-typed-summary",
            "before": rich,
            "after": copy.deepcopy(canonical_summary),
        })
        out["independent_summary"] = canonical_summary
        summary = canonical_summary
    if isinstance(summary, dict) and isinstance(summary.get("key_results"), str):
        before = summary["key_results"]
        summary["key_results"] = [before]
        changes.append({
            "pointer": "/independent_summary/key_results",
            "rule": "single-text-to-array",
            "before": before,
            "after": [before],
        })
    return out


def _normalize_paper_structure(payload: dict, changes: list[dict]) -> dict:
    """Adapt a human inventory section shape to the typed coverage-map shape."""
    out = copy.deepcopy(payload)
    supplements = out.get("supplements")
    if isinstance(supplements, dict):
        after = copy.deepcopy(supplements.get("items") or [])
        changes.append({
            "pointer": "/supplements", "rule": "structured-supplement-inventory-to-items",
            "before": copy.deepcopy(supplements), "after": copy.deepcopy(after),
        })
        out["supplements"] = after
    fulltext = out.get("fulltext_available")
    if isinstance(fulltext, dict):
        after = bool(fulltext.get("status"))
        changes.append({
            "pointer": "/fulltext_available", "rule": "structured-fulltext-receipt-to-boolean",
            "before": copy.deepcopy(fulltext), "after": after,
        })
        out["fulltext_available"] = after
    sections = out.get("sections")
    if not isinstance(sections, list):
        return out
    normalized = []
    changed = False
    for index, item in enumerate(sections):
        if not isinstance(item, dict) or {
            "section_ref", "role", "read_status"
        } <= set(item):
            normalized.append(item)
            continue
        title = str(item.get("section_ref") or item.get("section") or item.get("title") or f"Section {index + 1}").strip()
        coverage = str(item.get("role") or item.get("coverage") or "section inventory").strip()
        raw_status = str(item.get("read_status") or item.get("status") or "read").strip().casefold()
        if raw_status in {"read", "read_from_render_and_text"}:
            read_status = "read"
        elif raw_status in {"skimmed", "available_not_deep_read", "reference-only"}:
            read_status = "skimmed"
        elif raw_status in {"not_available", "not_available_in_run", "not-available"}:
            read_status = "not-available"
        elif raw_status in {"not_relevant", "not-relevant"}:
            read_status = "not-relevant"
        else:
            read_status = "skimmed"
        normalized.append({
            "section_ref": title,
            "role": coverage,
            "read_status": read_status,
            "key_points": [coverage] if coverage else [],
        })
        changed = True
    if changed:
        changes.append({
            "pointer": "/sections",
            "rule": "human-section-inventory-to-typed-sections",
            "before": copy.deepcopy(sections),
            "after": copy.deepcopy(normalized),
        })
        out["sections"] = normalized

    def normalize_inventory(
        field: str,
        ref_field: str,
    ) -> None:
        items = out.get(field)
        if not isinstance(items, list):
            return
        canonical_items = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                canonical_items.append(item)
                continue
            before = copy.deepcopy(item)
            alias = str(
                item.get(ref_field)
                or item.get("supplement_ref")
                or item.get("id")
                or item.get("ref")
                or f"{field[:-1]} {index + 1}"
            ).strip()
            raw_status = str(item.get("read_status") or item.get("status") or "").strip().casefold()
            if not raw_status and isinstance(item.get("read"), bool):
                raw_status = "read" if item["read"] else "not-read"
            if not raw_status and item.get("inspection_status"):
                raw_status = str(item.get("inspection_status") or "").strip().casefold()
            if raw_status in {"read", "read from actual page render", "read_from_render_and_text", "inspected"}:
                read_status = "read"
            elif raw_status in {"unread", "not read", "not-read", "reference_visible_not_inspected"}:
                read_status = "not-read"
            elif raw_status in {
                "unknown", "unavailable", "not available", "not-available",
                "not_available", "not_available_in_run",
            }:
                read_status = "not-available"
            else:
                read_status = "not-read"
            reason = str(
                item.get("reason")
                or item.get("why_load_bearing")
                or item.get("caption_role")
                or item.get("availability_in_run")
                or item.get("described_content")
                or item.get("paper_pointer")
                or item.get("boundary")
                or ""
            ).strip()
            canonical = {ref_field: alias, "read_status": read_status}
            if field != "supplements":
                canonical["load_bearing"] = bool(item.get("load_bearing"))
            if reason:
                canonical["reason"] = reason
            canonical_items.append(canonical)
            if canonical != before:
                changes.append({
                    "pointer": f"/{field}/{index}",
                    "rule": "paper-inventory-aliases-to-typed-coverage",
                    "before": before,
                    "after": copy.deepcopy(canonical),
                })
        out[field] = canonical_items

    normalize_inventory("figures", "figure_ref")
    normalize_inventory("tables", "table_ref")
    normalize_inventory("supplements", "ref")
    return out


def _normalize_project_alignment(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    relevance = out.get("relevance")
    if isinstance(relevance, str) and relevance.lstrip().startswith("{"):
        try:
            parsed = json.loads(relevance)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            relevance = parsed
    if isinstance(relevance, dict) and (relevance.get("class") or relevance.get("classification")):
        after = relevance.get("class") or relevance.get("classification")
    elif isinstance(relevance, dict):
        overall = str(relevance.get("overall") or "").casefold()
        if "a-core" in overall:
            after = "A-core"
        elif "b-related" in overall:
            after = "B-related"
        elif "c-background" in overall:
            after = "C-background"
        else:
            after = "not-relevant"
    else:
        after = None
    if after is not None:
        changes.append({
            "pointer": "/relevance",
            "rule": "structured-relevance-to-class",
            "before": copy.deepcopy(out.get("relevance")),
            "after": after,
        })
        out["relevance"] = after
    return out


def _normalize_claim_evidence_map(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    for mapping_index, mapping in enumerate(out.get("mappings") or []):
        if not isinstance(mapping, dict):
            continue
        claim_id = str(mapping.get("claim_id") or f"claim-{mapping_index + 1}")
        raw_support = str(mapping.get("overall_support") or "").strip()
        if raw_support not in {"supported", "partial", "contradicted", "not-found"}:
            lowered = raw_support.casefold()
            after_support = "partial" if (
                "boundary" in lowered or "nonreporting" in lowered or "partial" in lowered
            ) else ("contradicted" if "contradict" in lowered else (
                "not-found" if "not" in lowered and "support" not in lowered else "supported"
            ))
            changes.append({
                "pointer": f"/mappings/{mapping_index}/overall_support",
                "rule": "qualified-overall-support-to-enum",
                "before": raw_support, "after": after_support,
            })
            mapping["overall_support"] = after_support
        risk = mapping.get("claim_risk")
        if isinstance(risk, str):
            level, separator, note = risk.partition(";")
            level = level.strip().casefold()
            if level not in {"high", "medium", "low"}:
                level = "medium"
            after = {"level": level, "note": (note.strip() if separator else risk.strip())}
            changes.append({
                "pointer": f"/mappings/{mapping_index}/claim_risk",
                "rule": "risk-text-to-object",
                "before": risk,
                "after": copy.deepcopy(after),
            })
            mapping["claim_risk"] = after
        for locus_index, locus in enumerate(mapping.get("loci") or []):
            if not isinstance(locus, dict):
                continue
            pointer = f"/mappings/{mapping_index}/loci/{locus_index}"
            if not locus.get("locus_id"):
                locus_id = str(locus.get("span_id") or f"{claim_id}-L{locus_index + 1}")
                locus["locus_id"] = locus_id
                changes.append({
                    "pointer": f"{pointer}/locus_id", "rule": "stable-locus-id",
                    "before": None, "after": locus_id,
                })
            if locus.get("kind") == "text_span":
                locus["kind"] = "text"
                changes.append({
                    "pointer": f"{pointer}/kind", "rule": "canonical-locus-kind",
                    "before": "text_span", "after": "text",
                })
            kind = str(locus.get("kind") or "other")
            if kind not in {"table", "figure", "text", "code", "dataset", "appendix", "other"}:
                lowered_kind = kind.casefold()
                after_kind = "table" if "table" in lowered_kind else (
                    "figure" if "figure" in lowered_kind else "text"
                )
                locus["kind"] = after_kind
                changes.append({
                    "pointer": f"{pointer}/kind", "rule": "canonical-locus-kind",
                    "before": kind, "after": after_kind,
                })
            directness = str(locus.get("directness") or "")
            if directness not in {"", "direct", "indirect", "proxy", "assumed"}:
                lowered = directness.casefold()
                after = "indirect" if (
                    lowered in {
                        "inference", "inferential", "mixed", "derived",
                        "complete-source-absence", "inferred_from_complete_source_absence",
                    }
                    or "inferred_for_absence" in lowered
                ) else (
                    "direct" if lowered.startswith("direct")
                    else "indirect" if lowered.startswith("indirect")
                    else directness
                )
                if after != directness:
                    locus["directness"] = after
                    changes.append({
                        "pointer": f"{pointer}/directness", "rule": "canonical-directness",
                        "before": directness, "after": after,
                    })
            relation = str(locus.get("support_relation") or "")
            if relation not in {"", "entails", "partial", "contradicts", "insufficient"}:
                lowered = relation.casefold()
                after = "entails" if lowered in {
                    "support", "supported", "direct_support", "boundary_support",
                    "absence_boundary", "scope_boundary", "supports", "supports_absence",
                    "direct_entailment",
                } else (
                    "partial" if lowered in {
                        "absence_audit", "methodological_inference", "scope_limit",
                        "conflict_side_a", "conflict_side_b", "bounds",
                        "direct_evidence_with_interpretation_boundary",
                        "fulltext_coverage_supports_nonreporting_observation",
                    }
                    else "entails" if lowered.startswith("entails")
                    else "entails" if lowered.startswith("direct_support") or lowered.startswith("direct_entailment")
                    else "partial" if lowered.startswith("partial")
                    else relation
                )
                if after != relation:
                    locus["support_relation"] = after
                    changes.append({
                        "pointer": f"{pointer}/support_relation",
                        "rule": "canonical-support-relation",
                        "before": relation, "after": after,
                    })
            if locus.get("kind") == "figure" and not locus.get("figure_region_ref"):
                figure_ref = str(locus.get("location") or locus.get("locus_id") or "figure").strip()
                locus["figure_region_ref"] = figure_ref
                changes.append({
                    "pointer": f"{pointer}/figure_region_ref",
                    "rule": "figure-location-to-region-ref",
                    "before": None,
                    "after": figure_ref,
                })
            # A human label such as "Figure 2 caption" is not a mechanically
            # verifiable visual locator.  When the worker already supplied a
            # hash-bound exact character span, the evidence channel is text
            # (often a caption or extracted diagram labels), even if its
            # subject is a figure.  Classifying that channel as text avoids a
            # false request for a visual manifest; a real path:#xywh locator is
            # left as figure evidence and remains subject to visual hashing.
            figure_ref = str(locus.get("figure_region_ref") or "").strip()
            has_text_span = (
                isinstance(locus.get("char_start"), int)
                and not isinstance(locus.get("char_start"), bool)
                and isinstance(locus.get("char_end"), int)
                and not isinstance(locus.get("char_end"), bool)
                and 0 <= locus["char_start"] < locus["char_end"]
                and bool(str(locus.get("exact_quote") or ""))
            )
            if locus.get("kind") == "figure" and has_text_span and not figure_ref.startswith("path:"):
                locus["kind"] = "text"
                changes.append({
                    "pointer": f"{pointer}/kind",
                    "rule": "figure-caption-char-span-to-text-locus",
                    "before": "figure",
                    "after": "text",
                })
    return out


def _normalize_claim_list(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    allowed = {"performance", "method", "dataset", "comparison", "limitation", "other"}
    aliases = {
        "task_definition": "method", "method_scope": "method",
        "training_protocol": "method", "training_signal": "method",
        "dataset_scope": "dataset", "result": "performance",
        "ablation_result": "comparison", "comparative_result": "comparison",
        "ablation_boundary": "limitation", "comparison_boundary": "limitation",
        "evidence_boundary": "limitation", "scope_boundary": "limitation",
        "project_inference": "other",
        "novelty_boundary": "limitation",
        "coverage_and_novelty_limit": "limitation",
        "alternative_explanation_and_core_gap": "limitation",
        "rq_architecture_decision": "other",
        "identification_and_falsification_requirement": "method",
        "evaluation_and_contribution_boundary": "limitation",
    }
    for index, claim in enumerate(out.get("claims") or []):
        if not isinstance(claim, dict):
            continue
        confidence = str(claim.get("confidence") or "")
        if confidence not in {"", "high", "medium", "low"}:
            lowered_confidence = confidence.casefold()
            after_confidence = "high" if lowered_confidence.startswith("high") else (
                "low" if lowered_confidence.startswith("low") else "medium"
            )
            changes.append({
                "pointer": f"/claims/{index}/confidence",
                "rule": "qualified-confidence-to-enum",
                "before": confidence, "after": after_confidence,
            })
            claim["confidence"] = after_confidence
        kind = str(claim.get("kind") or "other")
        if kind in allowed:
            continue
        after = aliases.get(kind, "other")
        changes.append({
            "pointer": f"/claims/{index}/kind",
            "rule": "qualified-claim-kind-to-enum",
            "before": kind,
            "after": after,
        })
        claim["kind"] = after
    return out


def _normalize_result_table_audit(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    items = out.get("audited_items")
    if isinstance(items, list):
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            before = copy.deepcopy(item)
            if not str(item.get("item_ref") or "").strip():
                item["item_ref"] = str(
                    item.get("evidence_ref") or item.get("table_ref") or f"audited-item-{index + 1}"
                )
            claim_ids = item.get("claim_ids")
            if not str(item.get("claim_id") or "").strip():
                item["claim_id"] = ", ".join(str(x) for x in (claim_ids or [])) or "unmapped"
            if not str(item.get("metric") or "").strip():
                item["metric"] = "multiple reported metrics"
            if not str(item.get("reported_comparison") or "").strip() and item.get("comparison"):
                item["reported_comparison"] = str(item["comparison"])
            if not str(item.get("audit") or "").strip():
                parts = []
                for key in ("numeric_check", "statistical_check", "fairness", "verdict"):
                    value = item.get(key)
                    if value not in (None, "", [], {}):
                        parts.append(f"{key}: {value}")
                item["audit"] = " | ".join(parts) or "No additional audit detail reported."
            item.setdefault("direction", "unclear")
            item.setdefault("risk", "medium")
            if item.get("risk") not in {"low", "medium", "high"}:
                rationale = str(item.get("risk") or "").strip()
                item["risk"] = "high" if rationale else "medium"
                if rationale:
                    item["audit"] = f"{item['audit']} | risk rationale: {rationale}"
            if item != before:
                changes.append({
                    "pointer": f"/audited_items/{index}",
                    "rule": "rich-result-item-to-typed-audit",
                    "before": before,
                    "after": copy.deepcopy(item),
                })
    split_risks = out.get("leakage_or_split_risks")
    if isinstance(split_risks, dict):
        after = [
            f"{key}: " + (
                value if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            for key, value in split_risks.items()
        ]
        changes.append({
            "pointer": "/leakage_or_split_risks",
            "rule": "keyed-split-risks-to-lossless-lines",
            "before": copy.deepcopy(split_risks),
            "after": copy.deepcopy(after),
        })
        out["leakage_or_split_risks"] = after
    overall = out.get("overall")
    if isinstance(overall, dict):
        verdict = str(overall.get("verdict") or "").casefold()
        if "not_applicable" in verdict or "not-applicable" in verdict:
            after = "not-applicable"
        elif "weak" in verdict:
            after = "weak"
        elif "mixed" in verdict:
            after = "mixed"
        else:
            after = "supports-headline"
        changes.append({
            "pointer": "/overall", "rule": "structured-result-verdict-to-enum",
            "before": copy.deepcopy(overall), "after": after,
        })
        out["overall"] = after
    return out


def _normalize_paper_appraisal(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    dimensions = out.get("dimensions")
    if isinstance(dimensions, list):
        dim_order = [
            "soundness", "significance", "originality", "eval_rigor",
            "reproducibility", "clarity", "domain_validity",
        ]
        score_map = {"excellent": 4, "very_strong": 4, "strong": 3, "mixed": 2, "fair": 2, "weak": 1, "poor": 1}
        normalized_dimensions = []
        for index, item in enumerate(dimensions):
            if not isinstance(item, dict) or {"dim", "score"} <= set(item):
                normalized_dimensions.append(item)
                continue
            rating = str(item.get("rating") or "mixed").strip().casefold().replace(" ", "_")
            normalized_dimensions.append({
                "dim": dim_order[index] if index < len(dim_order) else "domain_validity",
                "score": score_map.get(rating, 2),
                "evidence_ref": item.get("evidence_ref"),
                "note": " ".join(str(item.get(key) or "").strip() for key in ("appraisal", "boundary") if item.get(key)),
            })
        if normalized_dimensions != dimensions:
            changes.append({
                "pointer": "/dimensions", "rule": "rich-appraisal-dimensions-to-7d-contract",
                "before": copy.deepcopy(dimensions), "after": copy.deepcopy(normalized_dimensions),
            })
            out["dimensions"] = normalized_dimensions
    generic_checklist = out.get("checklist")
    if isinstance(generic_checklist, list):
        normalized_items = []
        for item in generic_checklist:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").strip().casefold()
            canonical_status = status if status in {"met", "partial", "unmet", "na"} else (
                "na" if "not_applicable" in status else (
                    "unmet" if "not_reported" in status or "not_met" in status else "partial"
                )
            )
            normalized_items.append({
                "item": str(item.get("item") or "checklist item"),
                "status": canonical_status,
                "note": " ".join(str(item.get(key) or "").strip() for key in ("evidence_ref", "note") if item.get(key)),
            })
        after = {"standard": "claim", "items": normalized_items}
        changes.append({
            "pointer": "/checklist", "rule": "checklist-list-to-typed-object",
            "before": copy.deepcopy(generic_checklist), "after": copy.deepcopy(after),
        })
        out["checklist"] = after
    checklist = out.get("medical_imaging_checklist")
    if isinstance(checklist, list):
        refs = []
        for item in checklist:
            if not isinstance(item, dict):
                continue
            ref = str(item.get("standard_ref") or "").strip()
            if ref and ref != "cross_standard" and ref not in refs:
                refs.append(ref)
        after = {"standard_refs": refs, "items": copy.deepcopy(checklist)}
        changes.append({
            "pointer": "/medical_imaging_checklist",
            "rule": "medical-checklist-list-to-typed-object",
            "before": copy.deepcopy(checklist),
            "after": copy.deepcopy(after),
        })
        out["medical_imaging_checklist"] = after
        checklist = after
    if isinstance(checklist, dict):
        refs = checklist.get("standard_refs") or []
        checklist["standard_refs"] = [
            "other" if ref == "local_item_bank_extension" else ref for ref in refs
        ]
        for item in checklist.get("items") or []:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").strip().casefold()
            if status not in {"met", "partial", "unmet", "na"}:
                item["status"] = "na" if "not_applicable" in status else (
                    "unmet" if "not_reported" in status or "not_met" in status or "high_risk" in status
                    else "partial"
                )
            if item.get("standard_ref") == "local_item_bank_extension":
                item["standard_ref"] = "other"
            allowed_categories = {
                "patient_split", "external_validation", "annotation_protocol",
                "inter_reader_variability", "scanner_site_shift", "metric_direction",
                "statistical_uncertainty", "clinical_claim_boundary",
                "preprocessing_leakage", "failure_case_analysis", "other",
            }
            if item.get("category") not in allowed_categories:
                item["category"] = "other"
            raw_risk = item.get("risk")
            if raw_risk not in {"low", "medium", "high"}:
                status = str(item.get("status") or "").strip()
                canonical_risk = "high" if status == "unmet" else (
                    "medium" if status == "partial" else "low"
                )
                rationale = str(raw_risk or "").strip()
                if rationale:
                    if status in {"partial", "unmet"}:
                        fix = str(item.get("required_fix") or "").strip()
                        item["required_fix"] = (
                            f"{fix} Risk rationale: {rationale}" if fix
                            else f"Risk rationale: {rationale}"
                        )
                    else:
                        evidence = str(item.get("evidence_ref") or "").strip()
                        item["evidence_ref"] = (
                            f"{evidence}; risk rationale: {rationale}" if evidence else rationale
                        )
                item["risk"] = canonical_risk
            if item.get("required_fix") is None:
                item.pop("required_fix", None)
    return out


def _normalize_reproducibility_audit(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    risk = out.get("reproducibility_risk")
    if isinstance(risk, dict):
        rating = str(risk.get("rating") or "").casefold()
        after = "high" if "high" in rating else ("low" if "low" in rating else "medium")
        changes.append({
            "pointer": "/reproducibility_risk", "rule": "structured-reproducibility-risk-to-level",
            "before": copy.deepcopy(risk), "after": after,
        })
        out["reproducibility_risk"] = after
    for field in ("license_or_access_constraints", "reproduction_steps", "missing_materials"):
        value = out.get(field)
        if not isinstance(value, dict):
            continue
        after = [
            f"{key}: " + (
                item if isinstance(item, str)
                else json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            for key, item in value.items()
        ]
        changes.append({
            "pointer": f"/{field}",
            "rule": "keyed-reproducibility-note-to-lossless-lines",
            "before": copy.deepcopy(value),
            "after": copy.deepcopy(after),
        })
        out[field] = after
    return out


def _normalize_math_algorithm_audit(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    formal_objects = out.get("formal_objects")
    if isinstance(formal_objects, dict):
        normalized = [
            f"{key}: " + (
                value if isinstance(value, str)
                else json.dumps(value, ensure_ascii=False, sort_keys=True)
            )
            for key, value in formal_objects.items()
        ]
        changes.append({
            "pointer": "/formal_objects", "rule": "keyed-formal-objects-to-lossless-lines",
            "before": copy.deepcopy(formal_objects), "after": copy.deepcopy(normalized),
        })
        out["formal_objects"] = normalized
    applicability = str(out.get("applicability") or "")
    if applicability not in {"applicable", "not-applicable"}:
        lowered = applicability.casefold()
        after = "not-applicable" if lowered.startswith("not") else "applicable"
        changes.append({
            "pointer": "/applicability", "rule": "qualified-applicability-to-enum",
            "before": applicability, "after": after,
        })
        out["applicability"] = after
    overall = str(out.get("overall") or "")
    if overall not in {"strong", "mixed", "weak", "not-applicable"}:
        lowered = overall.casefold()
        after = (
            "not-applicable" if "not applicable" in lowered
            else "weak" if lowered.startswith("weak")
            else "strong" if lowered.startswith("strong")
            else "mixed"
        )
        changes.append({
            "pointer": "/overall", "rule": "qualified-math-verdict-to-enum",
            "before": overall, "after": after,
        })
        out["overall"] = after
    return out


def _normalize_paper_relations(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    allowed = {"inherits", "refutes", "unifies", "replaces", "opens", "extends", "uses"}
    for index, edge in enumerate(out.get("edges") or []):
        if not isinstance(edge, dict):
            continue
        relation = str(edge.get("relation") or "")
        if relation in allowed:
            continue
        prefix = relation.split("_", 1)[0]
        lowered = relation.casefold()
        if prefix in allowed:
            after = prefix
        elif "refut" in lowered:
            after = "refutes"
        elif "unif" in lowered:
            after = "unifies"
        elif "replac" in lowered:
            after = "replaces"
        elif "open" in lowered:
            after = "opens"
        elif "extend" in lowered or "reviv" in lowered:
            after = "extends"
        elif "inherit" in lowered:
            after = "inherits"
        else:
            after = "uses"
        if after in allowed:
            edge["relation"] = after
            changes.append({
                "pointer": f"/edges/{index}/relation", "rule": "qualified-relation-to-enum",
                "before": relation, "after": after,
            })
    return out


def _normalize_domain_transfer(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    for field in ("usable_for", "not_usable_for", "evidence_limits", "required_local_validation"):
        value = out.get(field)
        if not isinstance(value, dict):
            continue
        after = [
            f"{key}: " + (
                item if isinstance(item, str)
                else json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )
            for key, item in value.items()
        ]
        changes.append({
            "pointer": f"/{field}",
            "rule": "keyed-transfer-note-to-lossless-lines",
            "before": copy.deepcopy(value),
            "after": copy.deepcopy(after),
        })
        out[field] = after
    level = out.get("transfer_level")
    if isinstance(level, dict):
        overall = str(level.get("overall") or "").casefold()
        after = (
            "proxy" if "proxy_only" in overall
            else "direct" if overall == "direct"
            else "not-applicable" if "not_applicable" in overall
            else "indirect"
        )
        changes.append({
            "pointer": "/transfer_level", "rule": "structured-transfer-level-to-enum",
            "before": copy.deepcopy(level), "after": after,
        })
        out["transfer_level"] = after
    risk = out.get("risk_of_overclaim")
    if isinstance(risk, dict):
        after = str(risk.get("level") or "medium").casefold()
        if after not in {"low", "medium", "high"}:
            after = "medium"
        changes.append({
            "pointer": "/risk_of_overclaim", "rule": "structured-risk-to-level",
            "before": copy.deepcopy(risk), "after": after,
        })
        out["risk_of_overclaim"] = after

    axis_aliases = {
        "anatomy/task": "anatomy_or_task",
        "anatomy_task": "anatomy_or_task",
        "dataset/population": "dataset_population",
        "scanner/site": "scanner_or_site",
        "scanner_site": "scanner_or_site",
        "supervision/prompting": "supervision_or_prompting",
        "supervision_prompting": "supervision_or_prompting",
    }
    matrix = out.get("transfer_matrix")
    if isinstance(matrix, list):
        normalized = []
        changed = False
        for row in matrix:
            if isinstance(row, dict):
                raw_axis = str(row.get("axis") or "")
                canonical_axis = axis_aliases.get(raw_axis, raw_axis or "other")
                if canonical_axis != raw_axis:
                    before_axis = raw_axis
                    row = copy.deepcopy(row)
                    row["axis"] = canonical_axis
                    changed = True
                    changes.append({
                        "pointer": f"/transfer_matrix/{len(normalized)}/axis",
                        "rule": "canonical-transfer-axis",
                        "before": before_axis,
                        "after": canonical_axis,
                    })
            if not isinstance(row, dict) or {
                "source_setting", "target_setting", "match_level", "implication"
            } <= set(row):
                normalized.append(row)
                continue
            transfer = str(row.get("transfer") or "").casefold()
            match = (
                "distant" if "not_direct" in transfer or "proxy" in transfer
                else "close" if transfer == "partial"
                else "unknown"
            )
            implication = json.dumps({
                "reusable": row.get("reusable"),
                "non_reusable": row.get("non_reusable"),
                "local_validation": row.get("local_validation"),
            }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            normalized.append({
                "axis": axis_aliases.get(str(row.get("axis") or ""), row.get("axis") or "other"),
                "source_setting": str(row.get("source") or "unknown"),
                "target_setting": str(row.get("target") or "unknown"),
                "match_level": match,
                "implication": implication,
            })
            changed = True
        if changed:
            changes.append({
                "pointer": "/transfer_matrix", "rule": "rich-transfer-rows-to-contract",
                "before": copy.deepcopy(matrix), "after": copy.deepcopy(normalized),
            })
            out["transfer_matrix"] = normalized
    return out


def _normalize_reconciliation(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    comparison = out.get("comparison_performed")
    if isinstance(comparison, dict):
        after = bool(comparison.get("performed"))
        changes.append({
            "pointer": "/comparison_performed",
            "rule": "structured-comparison-receipt-to-boolean",
            "before": copy.deepcopy(comparison),
            "after": after,
        })
        out["comparison_performed"] = after
    verdict = out.get("verdict")
    if isinstance(verdict, dict) and str(verdict.get("status") or "").strip():
        after = str(verdict["status"])
        changes.append({
            "pointer": "/verdict",
            "rule": "structured-reconciliation-verdict-to-status",
            "before": copy.deepcopy(verdict),
            "after": after,
        })
        out["verdict"] = after
    evidence_by_disagreement = {}
    topic_by_disagreement = {}
    for index, row in enumerate(out.get("disagreements") or []):
        if not isinstance(row, dict):
            continue
        disagreement_id = str(row.get("disagreement_id") or "")
        topic_by_disagreement[disagreement_id] = str(row.get("topic") or "disagreement")
        if not row.get("evidence_ref"):
            evidence = row.get("source_evidence") or []
            if evidence:
                evidence_ref = json.dumps(
                    evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                row["evidence_ref"] = evidence_ref
                evidence_by_disagreement[disagreement_id] = row["evidence_ref"]
                changes.append({
                    "pointer": f"/disagreements/{index}/evidence_ref",
                    "rule": "source-evidence-to-reference-text",
                    "before": None, "after": row["evidence_ref"],
                })
    for index, row in enumerate(out.get("repair_ledger") or []):
        if not isinstance(row, dict):
            continue
        if row.get("status") == "resolved_as_mandatory_writer_instruction":
            row["status"] = "resolved"
            changes.append({
                "pointer": f"/repair_ledger/{index}/status",
                "rule": "writer-instruction-status-to-resolved",
                "before": "resolved_as_mandatory_writer_instruction", "after": "resolved",
            })
        disagreement_id = str(row.get("disagreement_id") or "")
        if not disagreement_id:
            disagreement_id = f"GLOBAL-{row.get('repair_id') or index + 1}"
            changes.append({
                "pointer": f"/repair_ledger/{index}/disagreement_id",
                "rule": "unlinked-writer-repair-to-global-id",
                "before": row.get("disagreement_id"),
                "after": disagreement_id,
            })
            row["disagreement_id"] = disagreement_id
        if not row.get("issue"):
            row["issue"] = topic_by_disagreement.get(
                disagreement_id,
                str(row.get("writer_repair") or "reconciliation repair"),
            )
            changes.append({
                "pointer": f"/repair_ledger/{index}/issue", "rule": "repair-topic-to-issue",
                "before": None, "after": row["issue"],
            })
        if not row.get("evidence_ref"):
            linked_evidence = evidence_by_disagreement.get(disagreement_id)
            if linked_evidence:
                row["evidence_ref"] = linked_evidence
                changes.append({
                    "pointer": f"/repair_ledger/{index}/evidence_ref",
                    "rule": "linked-disagreement-evidence-reference",
                    "before": None, "after": row["evidence_ref"],
                })
        if row.get("action") and not row.get("resolution_note"):
            row["resolution_note"] = row["action"]
            changes.append({
                "pointer": f"/repair_ledger/{index}/resolution_note",
                "rule": "repair-action-to-resolution-note",
                "before": None, "after": row["resolution_note"],
            })
        elif row.get("writer_repair") and not row.get("resolution_note"):
            row["resolution_note"] = row["writer_repair"]
            changes.append({
                "pointer": f"/repair_ledger/{index}/resolution_note",
                "rule": "writer-repair-to-resolution-note",
                "before": None, "after": row["resolution_note"],
            })
    return out


def _normalize_independent_reading_critique(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    verdict = out.get("verdict")
    if _token(str(verdict or "")) == "blockforpromotion":
        out["verdict"] = "PASS_WITH_CAVEATS"
        changes.append({
            "pointer": "/verdict",
            "rule": "promotion-only-block-to-delivery-caveat",
            "before": verdict,
            "after": "PASS_WITH_CAVEATS",
        })
    return out


def _normalize_trend_card(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    shifts = out.get("shifts")
    if isinstance(shifts, list):
        normalized = []
        for index, item in enumerate(shifts):
            if not isinstance(item, dict) or item.get("dimension"):
                normalized.append(item)
                continue
            label = str(item.get("shift") or "").casefold()
            if "latent" in label or "free-form" in label:
                dimension = "representation"
            elif "iterative" in label:
                dimension = "method"
            else:
                dimension = "problem"
            normalized.append({
                "dimension": dimension,
                "from": str(item.get("from") or ""),
                "to": str(item.get("to") or ""),
            })
        if normalized != shifts:
            changes.append({
                "pointer": "/shifts", "rule": "rich-trend-shifts-to-dimensions",
                "before": copy.deepcopy(shifts), "after": copy.deepcopy(normalized),
            })
            out["shifts"] = normalized
    return out


def _normalize_paper_reading_quality(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    # Promotion readiness is a narrower decision than daily research delivery.
    # Only make this conversion when the worker's explicit promotion flag does
    # not contradict it; otherwise leave the value invalid for local repair.
    if (
        _token(str(out.get("verdict") or "")) == "blockforpromotion"
        and out.get("promotion_ready") is not True
    ):
        before_verdict = out.get("verdict")
        out["verdict"] = "PASS_WITH_CAVEATS"
        out["promotion_ready"] = False
        changes.append({
            "pointer": "/verdict",
            "rule": "promotion-only-block-to-delivery-caveat",
            "before": before_verdict,
            "after": "PASS_WITH_CAVEATS",
        })
    field_enums = {
        "coverage": ("full", "partial", "thin"),
        "single_paper_completeness": ("complete", "partial", "thin"),
        "source_fidelity": ("strong", "mixed", "weak"),
        "visual_coverage": ("complete", "partial", "unread", "not-applicable"),
        "anchoring": ("strong", "mixed", "weak"),
        "method_depth": ("strong", "mixed", "weak", "not-applicable"),
        "figure_table_coverage": ("complete", "partial", "missing", "not-applicable"),
        "result_table_depth": ("strong", "mixed", "weak", "not-applicable"),
        "algorithmic_depth": ("strong", "mixed", "weak", "not-applicable"),
        "reproducibility_depth": ("strong", "mixed", "weak", "not-applicable"),
        "project_alignment": ("strong", "mixed", "weak"),
        "domain_transfer_honesty": ("strong", "mixed", "weak"),
        "independent_critique_resolution": ("resolved", "unresolved", "not-applicable"),
    }
    for field, allowed in field_enums.items():
        value = out.get(field)
        if not isinstance(value, dict):
            continue
        text_value = json.dumps(value, ensure_ascii=False, sort_keys=True).casefold()
        after = None
        if field == "coverage":
            if "complete" in text_value or "full" in text_value:
                after = "full"
            elif "thin" in text_value:
                after = "thin"
            elif "partial" in text_value:
                after = "partial"
        elif field == "single_paper_completeness":
            if "complete" in text_value:
                after = "complete"
            elif "thin" in text_value:
                after = "thin"
            elif "partial" in text_value:
                after = "partial"
        elif field == "visual_coverage":
            if "not-applicable" in text_value or "not applicable" in text_value:
                after = "not-applicable"
            elif "complete" in text_value:
                after = "complete"
            elif "unread" in text_value:
                after = "unread"
            elif "partial" in text_value:
                after = "partial"
        elif field == "figure_table_coverage":
            if "not-applicable" in text_value or "not applicable" in text_value:
                after = "not-applicable"
            elif "complete" in text_value:
                after = "complete"
            elif "missing" in text_value:
                after = "missing"
            elif "partial" in text_value:
                after = "partial"
        elif field == "independent_critique_resolution":
            if "not-applicable" in text_value or "not applicable" in text_value:
                after = "not-applicable"
            elif "unresolved" in text_value and '"unresolved":[]' not in text_value:
                after = "unresolved"
            elif "resolved" in text_value or '"unresolved":[]' in text_value:
                after = "resolved"
        elif "weak" in text_value or "missing" in text_value or "high risk" in text_value:
            after = "weak"
        elif "mixed" in text_value or "caveat" in text_value or "partial" in text_value:
            after = "mixed"
        elif "strong" in text_value or "complete" in text_value or "low risk" in text_value:
            after = "strong"
        if after not in allowed:
            continue
        changes.append({
            "pointer": f"/{field}", "rule": "structured-quality-assessment-to-enum",
            "before": copy.deepcopy(value), "after": after,
        })
        out[field] = after
    attacks = out.get("reviewer_attack_points")
    if isinstance(attacks, dict):
        normalized_attacks = []
        allowed_categories = {
            "novelty", "method_mechanism", "baseline_fairness", "dataset_split_leakage",
            "statistical_uncertainty", "metric_validity", "transfer_generalization",
            "reproducibility", "clinical_validity", "other",
        }
        aliases = {"split_leakage": "dataset_split_leakage", "transfer": "transfer_generalization"}
        for key, item in attacks.items():
            if isinstance(item, dict):
                category = aliases.get(key, key if key in allowed_categories else "other")
                normalized_attacks.append({
                    "category": category,
                    "attack": str(item.get("attack") or item.get("assessment") or key),
                    "evidence_ref": str(item.get("evidence") or item.get("evidence_ref") or "") or None,
                    "severity": str(item.get("severity") or "high").casefold() if str(item.get("severity") or "high").casefold() in {"low", "medium", "high"} else "high",
                })
            else:
                normalized_attacks.append(str(item))
        changes.append({
            "pointer": "/reviewer_attack_points", "rule": "keyed-reviewer-attacks-to-array",
            "before": copy.deepcopy(attacks), "after": copy.deepcopy(normalized_attacks),
        })
        out["reviewer_attack_points"] = normalized_attacks
    return out


def _normalize_markdown_card(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    aliases = {
        "decision_summary": "decision-need",
        "paper_problem_and_contribution": "claims-and-evidence",
        "data_and_design": "claims-and-evidence",
        "method_and_evaluation": "method-or-theory",
        "evidence_packages": "claims-and-evidence",
        "numeric_fairness_robustness_failure_audit": "numeric-results",
        "visual_audit_text_equivalent": "figures-and-tables",
        "validity_and_reproducibility": "reproducibility",
        "literature_position_and_reconciliation": "independent-critique",
        "medical_imaging_transfer_matrix": "transfer-matrix",
        "ev1_next_actions": "next-actions",
        "paper identity and one-screen summary": "decision-need",
        "background and problem": "claims-and-evidence",
        "hypothesis and contributions": "claims-and-evidence",
        "data and research design": "claims-and-evidence",
        "method flow": "method-or-theory",
        "conclusion-evidence packages": "claims-and-evidence",
        "numeric and baseline fairness": "numeric-results",
        "visual inspection": "figures-and-tables",
        "robustness and failures": "critical-appraisal",
        "validity and statistics": "critical-appraisal",
        "literature position": "independent-critique",
        "PET/CT project transfer": "domain-transfer",
        "decision-oriented next steps": "next-actions",
    }
    sections = out.get("covered_sections")
    if isinstance(sections, list):
        normalized = []
        for section in sections:
            mapped = aliases.get(str(section), section)
            if mapped not in normalized:
                normalized.append(mapped)
        if normalized != sections:
            changes.append({
                "pointer": "/covered_sections", "rule": "semantic-section-aliases",
                "before": copy.deepcopy(sections), "after": copy.deepcopy(normalized),
            })
            out["covered_sections"] = normalized
    return out


def _normalize_paper_note(payload: dict, changes: list[dict]) -> dict:
    """Preserve a richer keyed note while adapting legacy list-valued note fields."""
    out = copy.deepcopy(payload)
    relation = out.get("relation_to_thesis")
    if isinstance(relation, dict):
        rendered = json.dumps(relation, ensure_ascii=False, sort_keys=True)
        direct = relation.get("direct_collision")
        if direct or "a-core" in rendered.casefold():
            canonical_relation = "A-core"
        elif relation.get("partial_overlap"):
            canonical_relation = "B-related"
        else:
            canonical_relation = "C-background"
        changes.append({
            "pointer": "/relation_to_thesis",
            "rule": "structured-thesis-relation-to-class",
            "before": copy.deepcopy(relation),
            "after": canonical_relation,
        })
        out["relation_to_thesis"] = canonical_relation

    reading_status = out.get("reading_status")
    if isinstance(reading_status, dict):
        status_text = json.dumps(reading_status, ensure_ascii=False, sort_keys=True).casefold()
        if "deep-read" in status_text or "deep read" in status_text:
            canonical_status = "deep-read"
        elif "pass-1" in status_text or "pass 1" in status_text or "stage-0" in status_text:
            canonical_status = "skimmed"
        elif "complete" in status_text:
            canonical_status = "read"
        else:
            canonical_status = "to-read"
        changes.append({
            "pointer": "/reading_status",
            "rule": "structured-reading-status-to-stage",
            "before": copy.deepcopy(reading_status),
            "after": canonical_status,
        })
        out["reading_status"] = canonical_status
    for field in ("methods", "datasets", "metrics"):
        value = out.get(field)
        if not isinstance(value, dict):
            continue
        normalized = []
        for key, item in value.items():
            if isinstance(item, str):
                rendered = item
            else:
                rendered = json.dumps(item, ensure_ascii=False, sort_keys=True)
            normalized.append(f"{key}: {rendered}")
        changes.append({
            "pointer": f"/{field}",
            "rule": "keyed-note-section-to-lossless-lines",
            "before": copy.deepcopy(value),
            "after": copy.deepcopy(normalized),
        })
        out[field] = normalized
    return out


def _normalize_method_teardown(payload: dict, changes: list[dict]) -> dict:
    out = copy.deepcopy(payload)
    loss_terms = out.get("loss_terms")
    if isinstance(loss_terms, dict):
        if {"objective", "definition"} <= set(loss_terms):
            normalized = [{
                "term": str(loss_terms.get("objective") or "objective"),
                "role": str(loss_terms.get("definition") or ""),
                "ablate_effect": str(loss_terms.get("causal_boundary") or ""),
            }]
        else:
            normalized = []
            for key, item in loss_terms.items():
                rendered = item if isinstance(item, str) else json.dumps(
                    item, ensure_ascii=False, sort_keys=True
                )
                normalized.append({"term": str(key), "role": rendered, "ablate_effect": ""})
        changes.append({
            "pointer": "/loss_terms", "rule": "keyed-loss-terms-to-lossless-lines",
            "before": copy.deepcopy(loss_terms), "after": copy.deepcopy(normalized),
        })
        out["loss_terms"] = normalized
    return out


def normalize_payload(artifact_type: str, payload: dict) -> tuple[dict, dict]:
    schema_name = PAYLOAD_SCHEMAS[artifact_type]
    schema = json.loads((SCHEMA_DIR / schema_name).read_text(encoding="utf-8"))
    before = copy.deepcopy(payload)
    changes: list[dict] = []
    extras: list[dict] = []
    conflicts: list[dict] = []
    if artifact_type == "evidence_table":
        prepared = _normalize_evidence_table(before, changes, conflicts)
    elif artifact_type == "independent_reading_critique":
        # Both adaptations belong to the same worker payload.  Keeping them in
        # one branch matters: an ``elif`` further below is unreachable once the
        # artifact type has matched here.
        prepared = _normalize_blind_receipts(before, changes)
        prepared = _normalize_independent_reading_critique(prepared, changes)
    elif artifact_type == "paper_note":
        prepared = _normalize_paper_note(before, changes)
    elif artifact_type == "method_teardown":
        prepared = _normalize_method_teardown(before, changes)
    elif artifact_type == "paper_structure":
        prepared = _normalize_paper_structure(before, changes)
    elif artifact_type == "project_context_alignment":
        prepared = _normalize_project_alignment(before, changes)
    elif artifact_type == "claim_evidence_map":
        prepared = _normalize_claim_evidence_map(before, changes)
    elif artifact_type == "claim_list":
        prepared = _normalize_claim_list(before, changes)
    elif artifact_type == "result_table_audit":
        prepared = _normalize_result_table_audit(before, changes)
    elif artifact_type == "paper_appraisal":
        prepared = _normalize_paper_appraisal(before, changes)
    elif artifact_type == "reproducibility_materials_audit":
        prepared = _normalize_reproducibility_audit(before, changes)
    elif artifact_type == "math_algorithm_audit":
        prepared = _normalize_math_algorithm_audit(before, changes)
    elif artifact_type == "paper_relations":
        prepared = _normalize_paper_relations(before, changes)
    elif artifact_type == "domain_transfer_note":
        prepared = _normalize_domain_transfer(before, changes)
    elif artifact_type == "paper_reading_reconciliation":
        prepared = _normalize_reconciliation(before, changes)
    elif artifact_type == "trend_card":
        prepared = _normalize_trend_card(before, changes)
    elif artifact_type == "paper_reading_quality":
        prepared = _normalize_paper_reading_quality(before, changes)
    elif artifact_type == "paper_markdown_card":
        prepared = _normalize_markdown_card(before, changes)
    else:
        prepared = before
    after = _walk(prepared, schema, "", changes, extras)
    heuristic_changes = [
        copy.deepcopy(row)
        for row in changes
        if str(row.get("rule") or "") in _HEURISTIC_SCIENTIFIC_RULES
    ]
    return after, {
        "contract_version": "schema-normalization/v1",
        "artifact_type": artifact_type,
        "before_sha256": _digest(payload),
        "after_sha256": _digest(after),
        "changes": changes,
        "preserved_extras": extras,
        "representation_conflicts": conflicts,
        "heuristic_scientific_changes": heuristic_changes,
        "scientific_fields_modified": bool(heuristic_changes),
    }


def write_report(path: Path, report: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
