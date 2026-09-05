"""The single corpus loader: one identity policy, one fold rule, one census (TU-8).

Closes failure-catalog item (``_design/2026-08-20-team-upgrade/00-inputs-failure-catalog.md``):
  B1 — "two count truths": duplicate-record folding lived only in the run's
       ``synthesize.load()`` while the task ledger quoted unfolded numbers (75 vs the true
       73) — counts fork wherever identity forks. This module is the ONE loader every
       count-quoting consumer shares. Any artifact quoting corpus counts must obtain them
       from a ``Census`` and cite its origin: ``{loader_version, census_sha256}``.

Design (audit ``02-pipeline-hardening.md`` Q4):
  - identity policy REUSED from ``systematic_review_corpus.canonical_report_identity``
    (``IDENTITY_POLICY_VERSION`` = "report-identity/doi-arxiv-pmid-title/v1") rather than
    invented — verified importable without side effects (module import only defines
    constants/functions; its jsonschema dependency is already a machine dependency).
    ``id_fields`` selects which identity fields participate (default DOI > title).
  - fold rule: richer record wins (longer canonical JSON — the shared rule of the run's
    ``synthesize.load`` and ``screen_v2``); ties keep the first record in deterministic
    file order.
  - decision conflicts between folded records are SURFACED, never silently resolved.
  - ``census_sha256`` = ``hash_artifact.hash_payload`` over the sorted unit identities —
    stable across input orderings, so two loads of the same corpus always agree.

Deterministic, stdlib + existing machine tools only; reads JSON files, writes nothing.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple, Union

from research_agent_teams.tools.hash_artifact import canonical_json, hash_payload
from research_agent_teams.tools.systematic_review_corpus import (
    IDENTITY_POLICY_VERSION,
    canonical_report_identity,
)

LOADER_VERSION = "corpus-loader/v1"

_IDENTITY_FIELD_ALIASES = {
    "doi": ("doi",),
    "arxiv": ("arxiv", "arxiv_id"),
    "arxiv_id": ("arxiv", "arxiv_id"),
    "pmid": ("pmid",),
    "title": ("title",),
}


@dataclass(frozen=True)
class Census:
    """The one count truth. Consumers quote counts FROM here and cite
    ``{loader_version, census_sha256}`` next to every quoted number."""

    loader_version: str
    identity_policy_version: str
    identity_fields: Tuple[str, ...]
    n_records: int
    n_units: int
    n_folded: int
    n_unidentified: int
    units: Tuple[dict, ...]
    folds: Tuple[str, ...]                 # "kept <- dropped (reason)" lines
    decision_conflicts: Tuple[dict, ...]   # surfaced, never silently resolved
    census_sha256: str

    def counts_from(self) -> dict:
        """The provenance stamp every count-quoting artifact must carry."""
        return {"loader_version": self.loader_version, "census_sha256": self.census_sha256}


def _iter_source_files(dir_or_dirs) -> List[Path]:
    if isinstance(dir_or_dirs, (str, Path)):
        sources: Sequence = [dir_or_dirs]
    else:
        sources = list(dir_or_dirs)
    files: List[Path] = []
    for src in sources:
        p = Path(src)
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(sorted(p.glob("*.json")))
        else:
            raise FileNotFoundError(f"corpus source does not exist: {p}")
    return files


def _load_records(files: Iterable[Path]) -> List[Tuple[str, dict]]:
    """-> [(label, record)] in deterministic file order. A corrupt file is LOUD — silently
    skipping it would fork counts, which is the exact B1 disease."""
    out: List[Tuple[str, dict]] = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
            raise ValueError(f"unparseable corpus file {f}: {type(e).__name__}: {e}") from e
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            raise ValueError(f"corpus file {f} is neither a record nor a record list")
        for i, rec in enumerate(data):
            if not isinstance(rec, dict):
                raise ValueError(f"corpus file {f} entry #{i} is not an object")
            out.append((f"{f.name}#{i}", rec))
    return out


def _field_value(record: dict, names: Tuple[str, ...]):
    """Top-level first, then the run-corpus 'bib' sub-record (deepread shape)."""
    for name in names:
        v = record.get(name)
        if v:
            return v
    bib = record.get("bib")
    if isinstance(bib, dict):
        for name in names:
            v = bib.get(name)
            if v:
                return v
    return None


def _identity(record: dict, id_fields: Tuple[str, ...]) -> Tuple[str, bool]:
    """-> (identity, identified). Falls back to a content hash — an unidentifiable record
    stays countable as its own unit rather than vanishing or crashing the census."""
    probe = {}
    for f in id_fields:
        names = _IDENTITY_FIELD_ALIASES.get(f)
        if names is None:
            raise ValueError(f"unknown id_field {f!r} (known: {sorted(_IDENTITY_FIELD_ALIASES)})")
        canonical_name = "arxiv" if f == "arxiv_id" else f
        probe[canonical_name] = _field_value(record, names)
    try:
        return canonical_report_identity(probe), True
    except ValueError:
        return f"unidentified:{hash_payload(record).removeprefix('sha256:')[:16]}", False


def _decision(record: dict, decision_field: Optional[str]):
    if not decision_field:
        return None
    cur: object = record
    for part in decision_field.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def load_units(dir_or_dirs: Union[str, Path, Sequence[Union[str, Path]]], *,
               id_fields: Tuple[str, ...] = ("doi", "title"),
               decision_field: Optional[str] = None) -> Census:
    """Load every ``*.json`` record under ``dir_or_dirs`` and fold duplicates into units.

    - identity: ``canonical_report_identity`` restricted to ``id_fields``
      (same DOI, or same normalized title, -> same unit);
    - fold: richer record wins (longer canonical JSON), ties keep the earlier record;
    - ``decision_field`` (dotted path, e.g. ``"eligibility.decision"``): when the kept and
      dropped records disagree, the conflict is surfaced in the fold line AND in
      ``decision_conflicts`` — never silently resolved.
    """
    id_fields = tuple(id_fields)
    labeled = _load_records(_iter_source_files(dir_or_dirs))

    kept: dict = {}          # identity -> (label, record)
    folded_from: dict = {}   # identity -> [dropped labels]
    folds: List[str] = []
    conflicts: List[dict] = []
    n_unidentified = 0

    for label, rec in labeled:
        identity, identified = _identity(rec, id_fields)
        if not identified:
            n_unidentified += 1
        prev = kept.get(identity)
        if prev is None:
            kept[identity] = (label, rec)
            continue
        prev_label, prev_rec = prev
        # richer record wins — canonical JSON length is key-order independent
        if len(canonical_json(rec)) > len(canonical_json(prev_rec)):
            win_label, win_rec, lose_label, lose_rec = label, rec, prev_label, prev_rec
        else:
            win_label, win_rec, lose_label, lose_rec = prev_label, prev_rec, label, rec
        reason = f"duplicate {identity}; richer record kept"
        win_dec, lose_dec = _decision(win_rec, decision_field), _decision(lose_rec, decision_field)
        if decision_field and win_dec != lose_dec:
            reason += f"; DECISION CONFLICT: kept {win_dec!r}, dropped {lose_dec!r}"
            conflicts.append({"identity": identity, "kept": win_label, "kept_decision": win_dec,
                              "dropped": lose_label, "dropped_decision": lose_dec,
                              "decision_field": decision_field})
        folds.append(f"{win_label} <- {lose_label} ({reason})")
        folded_from.setdefault(identity, []).append(lose_label)
        kept[identity] = (win_label, win_rec)

    identities = sorted(kept)
    units = tuple(
        {"identity": ident, "label": kept[ident][0], "record": kept[ident][1],
         "folded_from": tuple(folded_from.get(ident, ()))}
        for ident in identities
    )
    return Census(
        loader_version=LOADER_VERSION,
        identity_policy_version=IDENTITY_POLICY_VERSION,
        identity_fields=id_fields,
        n_records=len(labeled),
        n_units=len(units),
        n_folded=len(folds),
        n_unidentified=n_unidentified,
        units=units,
        folds=tuple(folds),
        decision_conflicts=tuple(conflicts),
        census_sha256=hash_payload(identities),
    )
