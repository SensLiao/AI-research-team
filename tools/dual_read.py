"""Extraction-reliability harness: deterministic dual-read sample + agreement report.

Closes failure-catalog items C1 and C2 (2026-08-20 team upgrade):

  C1 — single reader, no reproducibility number. An external review scored a
       one-reader extraction 2.5/10; the run-local dual-reader study
       (runs/ref-free-seg-qa/deep_research-20260819T055022Z/tools/dual_reader.py)
       produced the number and exposed one field whose vocabulary did not
       reproduce. This module promotes that harness: a fixed-seed sample any
       reader can re-derive, and a field-by-field agreement comparison between
       two independent extraction passes.

  C2 — vocabulary drift inside the schema. "not-assessable" vs "not_assessable"
       counted as disagreement until normalization was pinned. Here hyphen and
       underscore are ONE separator, case is folded, and declared aliases are
       applied BEFORE comparison — and a pair that still disagrees while being
       identical under separator-blind projection is surfaced as an
       undeclared-alias finding: our own schema's spelling drift must never be
       reported as a finding about the sources.

Honesty invariant carried by the report object itself: both readers are machine
readers, so agreement bounds the REPRODUCIBILITY of the extraction procedure,
not its correctness — two readers can agree and both be wrong, and a shared
prior makes that more likely, not less. The ``caveat`` field states this, and
the overall figure is never separable from the per-field table (the report
always carries both; a field that does not reproduce must stay visible).

Domain-general by construction: fields are caller-supplied dotted paths;
no vocabulary lives here. Stdlib only. This module never writes files.
"""
from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

CAVEAT = (
    "Both readers are machine readers. Agreement bounds the reproducibility of the "
    "extraction procedure, not its correctness against the source; it is not "
    "inter-rater reliability between independent humans, and a shared prior makes "
    "agreeing-while-wrong more likely, not less."
)

_MISSING = object()
_NON_ALNUM = re.compile(r"[^a-z0-9]")

VERDICT_AGREE = "agree"
VERDICT_DISAGREE = "disagree"
VERDICT_NOT_ATTEMPTED = "not_attempted"


@dataclass
class AgreementReport:
    """Per-field agreement + overall, inseparable by construction.

    ``overall_agreement_pct`` is never emitted without ``by_field`` because both
    live on the same object; renderers must print the table, not just the scalar.
    """

    n_units_compared: int
    n_units_primary_only: int
    n_units_secondary_only: int
    fields: List[str]
    by_field: Dict[str, Dict[str, Any]]
    overall_agreement_pct: Optional[float]
    n_field_comparisons: int
    rows: List[Dict[str, Any]]
    undeclared_alias_findings: List[Dict[str, Any]]
    aliases_applied: Dict[str, str]
    caveat: str = CAVEAT

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)


# ------------------------------------------------------------------ sampling
def draw_sample(
    unit_ids: Sequence[str], *, seed: int, fraction: float, minimum: int
) -> List[str]:
    """Deterministic sample of unit ids: reproducible from (ids, seed, fraction, minimum).

    The pool is de-duplicated and sorted before sampling, so the draw is
    independent of the caller's iteration order; the result is sorted so two
    honest re-derivations are byte-identical. Sample size is
    ``max(minimum, round(len(pool) * fraction))`` capped at the pool size.
    """
    if not 0.0 <= float(fraction) <= 1.0:
        raise ValueError(f"fraction must be within [0, 1], got {fraction}")
    if minimum < 0:
        raise ValueError(f"minimum must be >= 0, got {minimum}")
    pool = sorted(set(unit_ids))
    k = min(len(pool), max(int(minimum), round(len(pool) * float(fraction))))
    rng = random.Random(seed)
    return sorted(rng.sample(pool, k))


# ------------------------------------------------------------------ normalization
def _norm_scalar(value: Any, aliases: Dict[str, str]) -> str:
    """Pin case + hyphen/underscore, then apply declared aliases (C2).

    Hyphen and underscore are the same separator: one vocabulary with two
    spellings is not a disagreement about the source, and counting it as one
    would understate agreement exactly where the schema is already weakest."""
    s = str(value).strip().lower().replace("-", "_")
    return aliases.get(s, s)


def _norm_value(value: Any, aliases: Dict[str, str]) -> Any:
    if isinstance(value, list):
        return tuple(sorted(_norm_scalar(x, aliases) for x in value))
    if isinstance(value, bool) or value is None:
        return value
    return _norm_scalar(value, aliases)


def _separator_blind(value: Any) -> str:
    """Alphanumeric-only projection — the tripwire for undeclared aliases."""
    return _NON_ALNUM.sub("", str(value).lower())


def _dig(record: Dict[str, Any], dotted: str) -> Any:
    """Fetch a dotted path; supports flat ``a__b`` keys and literal keys as fallbacks
    (the second reader in the reference run stored flat double-underscore keys)."""
    cur: Any = record
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            cur = _MISSING
            break
        cur = cur[part]
    if cur is not _MISSING:
        return cur
    for flat in (dotted.replace(".", "__"), dotted):
        if isinstance(record, dict) and flat in record:
            return record[flat]
    return _MISSING


def _jaccard(a: Any, b: Any, aliases: Dict[str, str]) -> float:
    """Partial credit for set-valued fields: strict equality hides that
    {x, y} against {x} agrees about something. Scalars count as singletons."""
    def as_set(v: Any) -> set:
        if v is None:
            return set()
        items = v if isinstance(v, (list, tuple, set)) else [v]
        return {_norm_scalar(x, aliases) for x in items}

    set_a, set_b = as_set(a), as_set(b)
    if not set_a and not set_b:
        return 1.0
    union = set_a | set_b
    return len(set_a & set_b) / len(union) if union else 1.0


# ------------------------------------------------------------------ comparison
def compare(
    primary: Dict[str, Dict[str, Any]],
    secondary: Dict[str, Dict[str, Any]],
    fields: List[str],
    *,
    aliases: "Dict[str, str] | None" = None,
) -> AgreementReport:
    """Field-by-field agreement between two independent extraction passes.

    ``primary`` / ``secondary`` map unit id -> extraction record (nested dicts;
    ``fields`` are dotted paths). ``aliases`` maps a normalized spelling to its
    canonical form and is applied to BOTH sides before comparing. A pair that
    disagrees after pinning but is identical under separator-blind projection is
    counted as a disagreement AND reported in ``undeclared_alias_findings`` —
    the alias was needed and not declared, which is a schema defect, not a
    source finding. Units present on only one side are counted, never dropped.
    """
    alias_map = {str(k).strip().lower().replace("-", "_"): str(v).strip().lower().replace("-", "_")
                 for k, v in (aliases or {}).items()}
    shared_units = sorted(set(primary) & set(secondary))
    primary_only = sorted(set(primary) - set(secondary))
    secondary_only = sorted(set(secondary) - set(primary))

    rows: List[Dict[str, Any]] = []
    undeclared: List[Dict[str, Any]] = []
    counts: Dict[str, Dict[str, int]] = {
        f: {VERDICT_AGREE: 0, VERDICT_DISAGREE: 0, VERDICT_NOT_ATTEMPTED: 0} for f in fields
    }
    set_valued: Dict[str, List[float]] = {}

    for unit in shared_units:
        for path in fields:
            raw_a = _dig(primary[unit], path)
            raw_b = _dig(secondary[unit], path)
            if raw_a is _MISSING or raw_b is _MISSING:
                verdict = VERDICT_NOT_ATTEMPTED
                missing_side = ("primary" if raw_a is _MISSING else "secondary")
                rows.append(
                    {
                        "unit": unit,
                        "field": path,
                        "primary": None if raw_a is _MISSING else raw_a,
                        "secondary": None if raw_b is _MISSING else raw_b,
                        "verdict": verdict,
                        "missing_side": missing_side,
                    }
                )
                counts[path][verdict] += 1
                continue
            norm_a = _norm_value(raw_a, alias_map)
            norm_b = _norm_value(raw_b, alias_map)
            verdict = VERDICT_AGREE if norm_a == norm_b else VERDICT_DISAGREE
            counts[path][verdict] += 1
            rows.append(
                {"unit": unit, "field": path, "primary": raw_a, "secondary": raw_b, "verdict": verdict}
            )
            if isinstance(raw_a, list) or isinstance(raw_b, list):
                set_valued.setdefault(path, []).append(_jaccard(raw_a, raw_b, alias_map))
            if (
                verdict == VERDICT_DISAGREE
                and not isinstance(norm_a, tuple)
                and not isinstance(norm_b, tuple)
                and _separator_blind(norm_a)
                and _separator_blind(norm_a) == _separator_blind(norm_b)
            ):
                undeclared.append(
                    {
                        "unit": unit,
                        "field": path,
                        "values": [raw_a, raw_b],
                        "hint": (
                            "values differ only by separator/punctuation — declare an alias "
                            "or pin the vocabulary; counted as disagreement until declared"
                        ),
                    }
                )

    by_field: Dict[str, Dict[str, Any]] = {}
    for path in fields:
        c = counts[path]
        n = c[VERDICT_AGREE] + c[VERDICT_DISAGREE]
        entry: Dict[str, Any] = {
            "n_compared": n,
            "agree": c[VERDICT_AGREE],
            "disagree": c[VERDICT_DISAGREE],
            "not_attempted": c[VERDICT_NOT_ATTEMPTED],
            "agreement_pct": round(100.0 * c[VERDICT_AGREE] / n, 1) if n else None,
        }
        if path in set_valued:
            values = set_valued[path]
            entry["mean_jaccard"] = round(sum(values) / len(values), 3)
        by_field[path] = entry

    total_agree = sum(v["agree"] for v in by_field.values())
    total_n = sum(v["n_compared"] for v in by_field.values())
    return AgreementReport(
        n_units_compared=len(shared_units),
        n_units_primary_only=len(primary_only),
        n_units_secondary_only=len(secondary_only),
        fields=list(fields),
        by_field=by_field,
        overall_agreement_pct=round(100.0 * total_agree / total_n, 1) if total_n else None,
        n_field_comparisons=total_n,
        rows=rows,
        undeclared_alias_findings=undeclared,
        aliases_applied=alias_map,
    )
