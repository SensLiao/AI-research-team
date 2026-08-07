"""Research-plan composer — the COMBINATION layer (director lock 2026-06-19).

Before this, the operate layer ran exactly ONE mode per run. The director's requirement: a request
must be able to invoke a COMBINATION of modes (a "tier"), the orchestrator must RECOMMEND tiers
(fastest/cheapest 1-mode core -> mainline -> deepest/widest full), the director picks one, then
answers each mode's drill-down questions (one round per mode), and the chain runs link-by-link.

This module is the deterministic brain behind that:
  - load the human-authored catalog (orchestrator/plan_catalog.yaml — the SSOT for intents/tiers).
  - match a request to an INTENT and PROPOSE its tiers, each annotated with cost (from
    mode_registry.yaml budgets), the human gates it passes through, and a validation verdict.
  - validate a chain: an unknown mode is a violation; a spec-only (not one-button) mode is FLAGGED
    honestly (never pretended push-button); a chain that runs backwards through the research phases
    (venue before ideate, design before evidence) is a violation.
  - thread one link's output into the next: write `inbox/upstream-grounding.json` into the downstream
    run and append a "PRIOR CHAIN CONTEXT" block to its worker prompt(s) so link N builds ON link N-1.

It is pure (no import of the operate layer — the CLI calls IN to here, never the reverse, so there is
no circular import). The model proposes; the DIRECTOR picks the tier and every human gate. The chain
is a bounded composition over a frozen, human-authored menu — not a free-form dynamic workflow.
"""
from __future__ import annotations

import copy
import copy
import hashlib
import json
import os
import shutil
import stat
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml

from research_agent_teams.tools.ledger import last_of_type, read_events, verify_chain

_PKG = Path(__file__).resolve().parents[1]                       # research_agent_teams/
_CATALOG_PATH = _PKG / "orchestrator" / "plan_catalog.yaml"
_REGISTRY_PATH = _PKG / "orchestrator" / "mode_registry.yaml"

UPSTREAM_GROUNDING_FILE = "upstream-grounding.json"              # under <run>/inbox/
HANDOFF_CONTRACT_VERSION = "mode-handoff/v2"
UPSTREAM_CITATION_HANDOFF_VERSION = "upstream-citation-snapshot/v1"
UPSTREAM_CITATION_HANDOFF_ROOT_REL = Path("inbox/upstream-citation-handoff")
UPSTREAM_CITATION_HANDOFF_MANIFEST_REL = UPSTREAM_CITATION_HANDOFF_ROOT_REL / "manifest.json"

# Cost bands (sum of the chain's modes' max_agent_hops) — drives the "fastest/cheapest" labelling.
_BAND_LIGHT_MAX = 6
_BAND_MEDIUM_MAX = 16


# --------------------------------------------------------------------------- catalog / registry I/O

#: path -> (raw_text, parsed). The two catalogs are 58 KB and 14 KB of YAML, read on nearly
#: every control-plane call: parsing one costs ~84 ms, deep-copying the parsed tree ~0.8 ms. Rendering
#: the outcome menu did it a few hundred times and took 11.6 s of the director's time. The cache key
#: is the file's TEXT, not its (mtime, size) stamp: a same-size rewrite inside one filesystem
#: timestamp tick (Windows granularity) left the old stamp intact and served a stale parse, while
#: re-reading the text costs ~1 ms — it is the parse we are avoiding, not the read.
_YAML_CACHE: dict[str, tuple[str, dict]] = {}


def _load_yaml_cached(path: Path) -> dict:
    """Parse once per distinct file content, then hand every caller its own independent copy.

    The contract callers already had is preserved exactly — a fresh mutable dict — so a caller that
    edits the result (`tests/test_graph_spec.py` does) still cannot affect anyone else, and an edit
    to the yaml on disk still takes effect with no restart because the text changes.
    """
    text = path.read_text(encoding="utf-8")
    cached = _YAML_CACHE.get(str(path))
    if cached is None or cached[0] != text:
        cached = (text, yaml.safe_load(text) or {})
        _YAML_CACHE[str(path)] = cached
    return copy.deepcopy(cached[1])


def load_catalog(path: Optional[str] = None) -> dict:
    """The plan catalog (an on-disk edit takes effect with no restart — see :func:`_load_yaml_cached`)."""
    p = Path(path) if path else _CATALOG_PATH
    return _load_yaml_cached(p)


def load_mode_registry(path: Optional[str] = None) -> dict:
    p = Path(path) if path else _REGISTRY_PATH
    return _load_yaml_cached(p)


def all_modes() -> set:
    """Every mode the registry knows (wired + spec-only)."""
    return set((load_mode_registry().get("modes") or {}).keys())


def wired_modes() -> set:
    """The one-button modes (operated:true in mode_registry.yaml — the wiring test enforces the mirror).

    Only these belong in a default tier; validate_chain flags anything else."""
    modes = load_mode_registry().get("modes") or {}
    return {m for m, spec in modes.items() if isinstance(spec, dict) and spec.get("operated")}


def all_intents() -> List[str]:
    return list((load_catalog().get("intents") or {}).keys())


# --------------------------------------------------------------------------- intent matching

def match_intents(request: str) -> List[Tuple[str, int]]:
    """(intent_id, score) for every intent, ranked by how many of its aliases appear in the request.

    Ties keep catalog order. A request that matches nothing returns every intent with score 0 (the
    caller then asks the director which arc — never a silent guess)."""
    cat = load_catalog()
    intents = cat.get("intents") or {}
    req = (request or "").lower()
    order = list(intents)
    scored: List[Tuple[str, int]] = []
    for iid in order:
        spec = intents[iid] or {}
        # aliases (full phrases) + keywords (short high-signal tokens, robust to natural phrasing
        # where a full alias is broken up, e.g. 找/个/研究/方向).
        terms = list(spec.get("aliases") or []) + list(spec.get("keywords") or [])
        score = sum(1 for t in terms if str(t).strip() and str(t).strip().lower() in req)
        scored.append((iid, score))
    scored.sort(key=lambda x: (-x[1], order.index(x[0])))
    return scored


def best_intents(request: str) -> Tuple[List[str], bool]:
    """(intent_ids, matched). Matched intents (score>0) if any, else ALL intents (ask the director)."""
    ranked = match_intents(request)
    hits = [iid for iid, s in ranked if s > 0]
    if hits:
        return hits, True
    return [iid for iid, _ in ranked], False


# --------------------------------------------------------------------------- cost / gates / validation

def estimate_cost(modes: List[str]) -> dict:
    """A chain's rough cost = sum of its modes' max_agent_hops (from mode_registry budgets)."""
    reg = load_mode_registry().get("modes") or {}
    hops = 0
    for m in modes:
        budget = (reg.get(m) or {}).get("budget") or {}
        hops += int(budget.get("max_agent_hops") or 0)
    if hops <= _BAND_LIGHT_MAX:
        band = "light"
    elif hops <= _BAND_MEDIUM_MAX:
        band = "medium"
    else:
        band = "heavy"
    return {"n_modes": len(modes), "agent_hops": hops, "band": band}


def gates_in_chain(modes: List[str]) -> List[dict]:
    """The human gates a chain PAUSES at, in order ({after: mode, gate: '/idea-bet'} ...)."""
    mg = load_catalog().get("mode_gates") or {}
    out: List[dict] = []
    for m in modes:
        for g in (mg.get(m) or []):
            out.append({"after": m, "gate": g})
    return out


def validate_chain(modes: List[str]) -> dict:
    """Verdict for an ordered mode chain.

    - unknown mode (not in the registry) -> violation.
    - spec-only mode (in the registry but not operated) -> FLAGGED (warning + spec_only list); honest
      that this link is hand-driven, not push-button — never silently treated as one-button.
    - phase order: a chain must be NON-DECREASING in phase_rank (discovery -> ideate -> design ->
      venue); a strictly-decreasing step is a violation. Within a rank the order is free."""
    cat = load_catalog()
    rank = cat.get("phase_rank") or {}
    known = all_modes()
    wired = wired_modes()
    violations: List[str] = []
    warnings: List[str] = []
    spec_only: List[str] = []

    for m in modes:
        if m not in known:
            violations.append(f"unknown mode {m!r} — not in mode_registry.yaml")
    for m in modes:
        if m in known and m not in wired:
            spec_only.append(m)
            warnings.append(
                f"{m!r} is spec-only (not one-button yet) — this link must be hand-driven per §3, "
                "not presented as push-button")

    ranked = [(m, rank.get(m)) for m in modes if rank.get(m) is not None]
    for (a_m, a_r), (b_m, b_r) in zip(ranked, ranked[1:]):
        if b_r < a_r:
            violations.append(
                f"phase order: {b_m!r} (rank {b_r}) cannot run after {a_m!r} (rank {a_r}) — a chain "
                "runs discovery -> ideate -> design -> venue")

    return {"ok": not violations, "violations": violations, "warnings": warnings,
            "spec_only": spec_only}


def mode_questions(mode: str) -> List[dict]:
    """The per-mode drill-down questions to ask AFTER this mode is included in the picked tier."""
    return list((load_catalog().get("mode_questions") or {}).get(mode) or [])


# --------------------------------------------------------------------------- propose tiers

def _tier_view(tier: dict) -> dict:
    modes = list(tier.get("modes") or [])
    return {"id": tier.get("id"), "label": tier.get("label", ""),
            "recommended": bool(tier.get("recommended")),
            "modes": modes, "why": tier.get("why", ""),
            "cost": estimate_cost(modes), "gates": gates_in_chain(modes),
            "validation": validate_chain(modes)}


def propose(intent_id: str) -> dict:
    """An intent's full tier menu (each tier annotated with cost / gates / validation)."""
    intents = load_catalog().get("intents") or {}
    if intent_id not in intents:
        raise KeyError(f"unknown intent {intent_id!r}; known: {sorted(intents)}")
    spec = intents[intent_id] or {}
    return {"intent": intent_id, "description": spec.get("description", ""),
            "tiers": [_tier_view(t) for t in (spec.get("tiers") or [])]}


def recommended_tier(tiers: List[dict]) -> Optional[dict]:
    """The tier marked recommended (else the middle one, else None)."""
    for t in tiers:
        if t.get("recommended"):
            return t
    return tiers[len(tiers) // 2] if tiers else None


def propose_for_request(request: str, intent: Optional[str] = None) -> dict:
    """The full proposal the CLI/orchestrator needs to render the tier AskUserQuestion + the
    per-mode drill-down rounds. When `intent` is given it is used verbatim; otherwise the request is
    matched (and if nothing matches, EVERY intent is returned so the director chooses the arc)."""
    if intent:
        intent_ids, matched = [intent], True
    else:
        intent_ids, matched = best_intents(request)
    return {"request": request, "matched": matched,
            "intents": [propose(i) for i in intent_ids],
            "mode_questions": load_catalog().get("mode_questions") or {},
            "note": "Render the recommended intent's tiers as the FIRST AskUserQuestion (tier pick, "
                    "with cost + the gates it pauses at). THEN ask each chosen mode's drill-down "
                    "(mode_questions) — one round per mode. THEN run the chain link-by-link with "
                    "`operate begin --mode <m> --upstream-run <prev>`, pausing at each gate."}


# --------------------------------------------------------------------------- chain threading

def _read_json(path: Path) -> Optional[dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _read_yaml(path: Path) -> Optional[dict]:
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, yaml.YAMLError):
        return None
    return value if isinstance(value, dict) else None


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _sha256_hex(path: Path) -> str:
    return _sha256_file(path).removeprefix("sha256:").lower()


def _normalise_sha256(value: object) -> str:
    return str(value or "").removeprefix("sha256:").strip().lower()


def _is_reparse_point(path: Path) -> bool:
    """True for a symlink or Windows reparse point (including directory junctions)."""
    try:
        if path.is_symlink():
            return True
        if os.name == "nt":
            attributes = getattr(os.lstat(path), "st_file_attributes", 0)
            return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))
    except OSError:
        return False
    return False


def _path_inside(root: Path, ref: str, *, label: str) -> Path:
    """Resolve a relative handoff path without admitting escapes, symlinks, or junction hops."""
    raw = Path(ref)
    if raw.is_absolute() or any(part == ".." for part in raw.parts):
        raise ValueError(f"{label} must be a relative path inside its run: {ref!r}")
    base = root.resolve()
    candidate = base / raw
    current = base
    for part in raw.parts:
        if part in {"", "."}:
            continue
        current = current / part
        if current.exists() and _is_reparse_point(current):
            raise ValueError(f"{label} must not traverse a symlink or junction: {ref!r}")
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(base)
    except (OSError, ValueError) as exc:
        raise ValueError(f"{label} escapes its run: {ref!r}") from exc
    return resolved


def _ensure_directory_inside(root: Path, ref: str, *, label: str) -> Path:
    """Create a directory path one component at a time without following reparse points."""
    raw = Path(ref)
    if raw.is_absolute() or any(part == ".." for part in raw.parts):
        raise ValueError(f"{label} must be a relative path inside its run: {ref!r}")
    base = root.resolve()
    if not base.is_dir():
        raise ValueError(f"{label} root is not a directory: {base}")
    current = base
    for part in raw.parts:
        if part in {"", "."}:
            continue
        current = current / part
        if _is_reparse_point(current):
            raise ValueError(f"{label} must not traverse a symlink or junction: {ref!r}")
        if not current.exists():
            try:
                current.mkdir()
            except FileExistsError:
                pass
            if _is_reparse_point(current):
                raise ValueError(f"{label} must not traverse a symlink or junction: {ref!r}")
        if not current.is_dir():
            raise ValueError(f"{label} component is not a directory: {current}")
        try:
            current.resolve(strict=False).relative_to(base)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{label} escapes its run: {ref!r}") from exc
    return _path_inside(base, ref, label=label)


def _write_bytes_atomic(root: Path, ref: str, value: bytes, *, label: str) -> Path:
    """Atomically write a new file only through non-reparse path components under ``root``."""
    target = _path_inside(root, ref, label=label)
    parent_ref = Path(ref).parent.as_posix()
    parent = _ensure_directory_inside(
        root, parent_ref if parent_ref != "." else "", label=label + " parent")
    # Re-check after creation: an attacker cannot swap an unchecked parent for a junction.
    target = _path_inside(root, ref, label=label)
    if target.exists() and _is_reparse_point(target):
        raise ValueError(f"refusing to replace symlinked or junctioned {label}: {target}")
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=str(parent))
    temp = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        if _is_reparse_point(temp):
            raise ValueError(f"refusing to use reparse-point temporary {label}: {temp}")
        # Re-check the final parent and leaf immediately before the replacement.
        _ensure_directory_inside(root, parent_ref if parent_ref != "." else "", label=label + " parent")
        target = _path_inside(root, ref, label=label)
        if target.exists() and _is_reparse_point(target):
            raise ValueError(f"refusing to replace symlinked or junctioned {label}: {target}")
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    return target


def _write_json_atomic(root: Path, ref: str, value: dict, *, label: str) -> Path:
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    return _write_bytes_atomic(root, ref, raw, label=label)


def _strict_claim_map_payload(raw: dict) -> dict | None:
    payload = raw.get("payload") if isinstance(raw, dict) else None
    if not isinstance(payload, dict):
        return None
    if payload.get("attribution_contract_version") != "claim-span/v1":
        return None
    return payload


def materialize_upstream_citation_snapshots(new_run_dir: str | Path, grounding: dict) -> dict:
    """Copy only hash-verified upstream claim snapshots into a downstream run.

    The copied files make previously verified sources reopenable by the existing
    current-run-only citation resolver.  The source claim map is itself already
    hash-pinned in ``upstream-grounding.json``; this function verifies both that
    map and each referenced snapshot before writing any downstream evidence.
    """
    root = Path(new_run_dir).resolve()
    final_root = _path_inside(root, UPSTREAM_CITATION_HANDOFF_ROOT_REL.as_posix(),
                              label="citation snapshot handoff destination")
    if final_root.exists():
        raise ValueError("citation snapshot handoff destination already exists")
    pending_snapshots: dict[str, bytes] = {}
    snapshot_rows: list[dict] = []
    pending_views: list[tuple[str, dict, dict]] = []

    for upstream in grounding.get("upstream_runs") or []:
        upstream_root = Path(str(upstream.get("run_dir") or "")).resolve()
        run_id = str(upstream.get("run_id") or upstream_root.name)
        for item in upstream.get("artifact_manifest") or []:
            if item.get("artifact_type") != "claim_evidence_map":
                continue
            if str(item.get("status") or "").lower() not in {"approved", "frozen"}:
                continue
            map_ref = str(item.get("run_relative_path") or "")
            try:
                map_path = _path_inside(upstream_root, map_ref,
                                        label=f"{run_id} upstream claim-evidence map")
            except ValueError as exc:
                raise ValueError(f"{run_id}: claim-evidence map is outside the declared upstream run") from exc
            stated_path = Path(str(item.get("path") or ""))
            try:
                if stated_path.resolve() != map_path:
                    raise ValueError(f"{run_id}: claim-evidence map is outside the declared upstream run")
            except OSError as exc:
                raise ValueError(f"{run_id}: claim-evidence map path cannot be resolved") from exc
            if not map_path.is_file():
                raise ValueError(f"{run_id}: declared claim-evidence map is unavailable")
            expected_map_hash = str(item.get("sha256") or "")
            try:
                map_bytes = map_path.read_bytes()
            except OSError as exc:
                raise ValueError(f"{run_id}: declared claim-evidence map cannot be read") from exc
            actual_map_hash = "sha256:" + hashlib.sha256(map_bytes).hexdigest()
            if actual_map_hash != expected_map_hash:
                raise ValueError(f"{run_id}: claim-evidence map hash changed before handoff")
            try:
                raw_map = json.loads(map_bytes.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(f"{run_id}: declared claim-evidence map is invalid JSON") from exc
            payload = _strict_claim_map_payload(raw_map)
            if payload is None:
                continue

            rebased = copy.deepcopy(raw_map)
            rebased_payload = rebased["payload"]
            rewrites = 0
            for mapping in rebased_payload.get("mappings") or []:
                if not isinstance(mapping, dict):
                    continue
                for locus in mapping.get("loci") or []:
                    if not isinstance(locus, dict):
                        continue
                    snapshot_ref = str(locus.get("snapshot_ref") or "")
                    document_hash = _normalise_sha256(locus.get("document_hash"))
                    if not snapshot_ref and not document_hash:
                        continue
                    if not snapshot_ref or len(document_hash) != 64 or any(
                        char not in "0123456789abcdef" for char in document_hash
                    ):
                        raise ValueError(
                            f"{run_id}: strict citation locus has incomplete snapshot provenance"
                        )
                    source = _path_inside(
                        upstream_root, snapshot_ref, label=f"{run_id} upstream snapshot_ref"
                    )
                    if not source.is_file():
                        raise ValueError(f"{run_id}: upstream citation snapshot is unavailable: {snapshot_ref}")
                    raw_bytes = source.read_bytes()
                    actual_hash = hashlib.sha256(raw_bytes).hexdigest()
                    if actual_hash != document_hash:
                        raise ValueError(
                            f"{run_id}: upstream citation snapshot hash mismatch for {snapshot_ref}"
                        )
                    local_ref = (UPSTREAM_CITATION_HANDOFF_ROOT_REL / "snapshots" /
                                 f"{document_hash}.snapshot").as_posix()
                    pending_snapshots.setdefault(document_hash, raw_bytes)
                    locus["snapshot_ref"] = local_ref
                    rewrites += 1
                    snapshot_rows.append({
                        "upstream_run_id": run_id,
                        "upstream_claim_map_ref": str(item.get("run_relative_path") or ""),
                        "upstream_claim_map_sha256": expected_map_hash,
                        "upstream_snapshot_ref": snapshot_ref,
                        "document_hash": document_hash,
                        "local_snapshot_ref": local_ref,
                        "local_snapshot_sha256": f"sha256:{document_hash}",
                    })

            if not rewrites:
                continue
            map_hash = _normalise_sha256(expected_map_hash)
            view_ref = (UPSTREAM_CITATION_HANDOFF_ROOT_REL / "rebased" / f"{map_hash}.json").as_posix()
            pending_views.append((view_ref, rebased, {
                "upstream_run_id": run_id,
                "upstream_claim_map_ref": map_ref,
                "upstream_claim_map_sha256": expected_map_hash,
            }))

    # Build an entirely private staging directory.  If any source check or write
    # fails, no effective handoff path is created under the final destination.
    inbox = _ensure_directory_inside(root, "inbox", label="citation snapshot handoff inbox")
    staging: Path | None = None
    try:
        staging = Path(tempfile.mkdtemp(prefix=".upstream-citation-handoff-", dir=str(inbox)))
        try:
            staging_ref = staging.resolve().relative_to(root).as_posix()
        except (OSError, ValueError) as exc:
            raise ValueError("citation snapshot handoff staging directory escapes its run") from exc
        staging = _path_inside(root, staging_ref, label="citation snapshot handoff staging directory")
        if _is_reparse_point(staging):
            raise ValueError("citation snapshot handoff staging directory is a reparse point")

        rebased_rows: list[dict] = []
        for document_hash, raw_bytes in pending_snapshots.items():
            stage_ref = (Path("snapshots") / f"{document_hash}.snapshot").as_posix()
            _write_bytes_atomic(staging, stage_ref, raw_bytes, label="materialized citation snapshot")

        for view_ref, view, provenance in pending_views:
            stage_ref = (Path("rebased") / Path(view_ref).name).as_posix()
            view_path = _write_json_atomic(staging, stage_ref, view,
                                           label="rebased upstream claim-evidence map")
            rebased_rows.append({
                **provenance,
                "local_claim_map_ref": view_ref,
                "local_claim_map_sha256": _sha256_file(view_path),
            })

        manifest = {
            "contract_version": UPSTREAM_CITATION_HANDOFF_VERSION,
            "snapshots": snapshot_rows,
            "rebased_claim_maps": rebased_rows,
        }
        staged_manifest = _write_json_atomic(staging, "manifest.json", manifest,
                                              label="citation snapshot handoff manifest")
        manifest_hash = _sha256_file(staged_manifest)
        # Re-check the final parent immediately before the atomic directory move.
        _ensure_directory_inside(root, "inbox", label="citation snapshot handoff inbox")
        final_root = _path_inside(root, UPSTREAM_CITATION_HANDOFF_ROOT_REL.as_posix(),
                                  label="citation snapshot handoff destination")
        if final_root.exists():
            raise ValueError("citation snapshot handoff destination appeared during materialization")
        os.replace(staging, final_root)
        staging = None
        return {
            "contract_version": UPSTREAM_CITATION_HANDOFF_VERSION,
            "manifest_ref": UPSTREAM_CITATION_HANDOFF_MANIFEST_REL.as_posix(),
            "manifest_sha256": manifest_hash,
            "n_snapshots": len(pending_snapshots),
            "n_rebased_claim_maps": len(rebased_rows),
        }
    finally:
        if staging is not None and staging.exists() and not _is_reparse_point(staging):
            shutil.rmtree(staging, ignore_errors=True)


def validate_materialized_citation_snapshots(run_dir: str | Path, grounding: dict) -> list[str]:
    """Verify the downstream local copies that an upstream handoff pinned."""
    bridge = grounding.get("citation_snapshot_handoff") or {}
    if not bridge:
        return []
    errors: list[str] = []
    root = Path(run_dir).resolve()
    if bridge.get("contract_version") != UPSTREAM_CITATION_HANDOFF_VERSION:
        return ["unsupported upstream citation snapshot handoff contract"]
    try:
        manifest_path = _path_inside(root, str(bridge.get("manifest_ref") or ""),
                                     label="citation snapshot handoff manifest")
    except ValueError as exc:
        return [str(exc)]
    if not manifest_path.is_file():
        return ["materialized citation snapshot manifest is unavailable"]
    if _sha256_file(manifest_path) != str(bridge.get("manifest_sha256") or ""):
        return ["materialized citation snapshot manifest hash mismatch"]
    manifest = _read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get("contract_version") != UPSTREAM_CITATION_HANDOFF_VERSION:
        return ["materialized citation snapshot manifest is invalid"]
    snapshots = manifest.get("snapshots") or []
    if int(bridge.get("n_snapshots") or 0) != len({row.get("document_hash") for row in snapshots if isinstance(row, dict)}):
        errors.append("materialized citation snapshot count mismatch")

    upstream = {str(row.get("run_id") or ""): row for row in grounding.get("upstream_runs") or []}
    for row in snapshots:
        if not isinstance(row, dict):
            errors.append("materialized citation snapshot row is invalid")
            continue
        run = upstream.get(str(row.get("upstream_run_id") or ""))
        if run is None:
            errors.append("materialized citation snapshot names an unknown upstream run")
            continue
        matching_map = any(
            item.get("artifact_type") == "claim_evidence_map"
            and item.get("run_relative_path") == row.get("upstream_claim_map_ref")
            and item.get("sha256") == row.get("upstream_claim_map_sha256")
            for item in run.get("artifact_manifest") or []
        )
        if not matching_map:
            errors.append("materialized citation snapshot lost its pinned upstream claim-map provenance")
        try:
            local = _path_inside(root, str(row.get("local_snapshot_ref") or ""),
                                 label="materialized citation snapshot")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        expected = _normalise_sha256(row.get("document_hash"))
        if not local.is_file() or _sha256_hex(local) != expected:
            errors.append(f"materialized citation snapshot hash mismatch: {row.get('local_snapshot_ref')}")
        if str(row.get("local_snapshot_sha256") or "") != f"sha256:{expected}":
            errors.append("materialized citation snapshot manifest carries an inconsistent local hash")

    for row in manifest.get("rebased_claim_maps") or []:
        if not isinstance(row, dict):
            errors.append("rebased claim-map row is invalid")
            continue
        try:
            local = _path_inside(root, str(row.get("local_claim_map_ref") or ""),
                                 label="rebased upstream claim-evidence map")
        except ValueError as exc:
            errors.append(str(exc))
            continue
        if not local.is_file() or _sha256_file(local) != str(row.get("local_claim_map_sha256") or ""):
            errors.append("rebased upstream claim-evidence map hash mismatch")
    return errors


def _mode_handoff(mode: str) -> dict:
    spec = ((load_mode_registry().get("modes") or {}).get(mode) or {}).get("handoff") or {}
    return dict(spec) if isinstance(spec, dict) else {}


def _normalise_contract(raw: dict, *, pinned: bool) -> dict:
    return {
        "contract_version": str(raw.get("contract_version") or HANDOFF_CONTRACT_VERSION),
        "product_version": str(raw.get("product_version") or "unversioned"),
        "primary_markdown": str(raw.get("primary_markdown") or ""),
        "reusable_artifacts": [str(x) for x in (raw.get("reusable_artifacts") or [])],
        "accepts": [str(x) for x in (raw.get("accepts") or [])],
        "accepts_delivery_statuses": [
            str(x) for x in (raw.get("accepts_delivery_statuses") or ["USABLE"])
        ],
        "contract_pinned": pinned,
        "contract_source": "task_frame" if pinned else "registry_fallback_for_legacy_run",
    }


def _contract_for_run(payload: dict, mode: str) -> dict:
    pinned = payload.get("product_contract") or {}
    if isinstance(pinned, dict) and pinned.get("product_version"):
        return _normalise_contract(pinned, pinned=True)
    return _normalise_contract(_mode_handoff(mode), pinned=False)


def _declared_files(run_dir: Path, contract: dict) -> tuple[list[Path], list[str]]:
    """Resolve the product contract to actual files without guessing a stage path."""
    found: list[Path] = []
    missing: list[str] = []
    primary = str(contract.get("primary_markdown") or "")
    if primary:
        matches = sorted(p for p in run_dir.glob(primary.replace("<paper>", "*")) if p.is_file())
        if matches:
            found.extend(matches)
        else:
            missing.append(primary)
    for name in contract.get("reusable_artifacts") or []:
        matches = sorted(p for p in (run_dir / "evidence").glob(f"**/{name}") if p.is_file())
        if matches:
            found.extend(matches)
        else:
            missing.append(name)
    return found, missing


def _manifest_item(path: Path, run_dir: Path) -> dict:
    raw = _read_json(path) or {}
    try:
        relative = path.resolve().relative_to(run_dir.resolve()).as_posix()
    except ValueError:
        relative = path.name
    return {
        "path": str(path.resolve()),
        "run_relative_path": relative,
        "sha256": _sha256_file(path),
        "artifact_type": str(raw.get("artifact_type") or "retrieval_bundle"),
        "schema_version": str(raw.get("schema_version") or "unversioned"),
        "status": str(raw.get("status") or "available"),
    }


def _upstream_completion_errors(run: dict, run_root: Path, run_id: str) -> list[str]:
    """Require a completed, ledger-anchored REPORT before a run becomes handoff input."""
    errors: list[str] = []
    if not run_root.is_dir():
        return [f"{run_id}: upstream run directory is unavailable"]
    manifest = _read_yaml(run_root / "manifest.yaml")
    if not manifest:
        return [f"{run_id}: upstream manifest is unavailable"]
    actual_status = str(manifest.get("status") or "unknown")
    if actual_status != "done":
        errors.append(f"{run_id}: upstream run is not complete")
    if str(run.get("run_status") or "unknown") != actual_status:
        errors.append(f"{run_id}: upstream run status no longer matches its manifest")

    try:
        ledger_path = _path_inside(run_root, "ledger.jsonl", label=f"{run_id} upstream ledger")
    except ValueError as exc:
        return errors + [str(exc)]
    if not ledger_path.is_file():
        return errors + [f"{run_id}: upstream ledger is missing"]
    try:
        events = read_events(ledger_path)
    except (OSError, ValueError) as exc:
        return errors + [f"{run_id}: upstream ledger cannot be read: {exc}"]
    ledger_errors = verify_chain(events)
    if ledger_errors:
        errors.append(f"{run_id}: upstream ledger chain is invalid: {'; '.join(ledger_errors)}")
        return errors
    boundaries = [event for event in events if event.get("event_type") == "boundary"]
    if not boundaries or str((boundaries[-1].get("payload") or {}).get("completed_stage") or "") != "REPORT":
        errors.append(f"{run_id}: upstream REPORT completion boundary is missing")
    elif str(manifest.get("last_boundary_hash") or "") != str(boundaries[-1].get("hash") or ""):
        errors.append(f"{run_id}: upstream manifest does not anchor its REPORT completion boundary")

    try:
        report_path = _path_inside(
            run_root, "evidence/REPORT/report-note.artifact.json", label=f"{run_id} upstream REPORT")
    except ValueError as exc:
        return errors + [str(exc)]
    report = _read_json(report_path) if report_path.is_file() else None
    if not isinstance(report, dict):
        errors.append(f"{run_id}: upstream REPORT artifact is unavailable")
        return errors
    expected_ref = report_path.relative_to(run_root.resolve()).as_posix()
    report_hash = _sha256_file(report_path)
    if not any(
        str(item.get("run_relative_path") or "") == expected_ref
        and str(item.get("sha256") or "") == report_hash
        for item in (run.get("artifact_manifest") or [])
        if isinstance(item, dict)
    ):
        errors.append(f"{run_id}: upstream REPORT artifact is not hash-pinned in the handoff manifest")
    return errors


def validate_upstream_grounding(grounding: dict) -> list[str]:
    """Verify only transport integrity and declared contract compatibility.

    This deliberately does not re-review upstream science. It prevents a
    downstream mode from silently consuming a replaced or missing file.
    """
    errors: list[str] = []
    if grounding.get("handoff_contract_version") != HANDOFF_CONTRACT_VERSION:
        errors.append(
            f"unsupported handoff contract {grounding.get('handoff_contract_version')!r}; "
            f"expected {HANDOFF_CONTRACT_VERSION!r}"
        )
    for run in grounding.get("upstream_runs") or []:
        run_id = str(run.get("run_id") or "?")
        try:
            run_root = Path(str(run.get("run_dir") or "")).resolve()
        except OSError:
            errors.append(f"{run_id}: upstream run directory cannot be resolved")
            continue
        errors.extend(_upstream_completion_errors(run, run_root, run_id))
        for item in run.get("artifact_manifest") or []:
            try:
                path = _path_inside(run_root, str(item.get("run_relative_path") or ""),
                                    label=f"{run_id} handoff artifact")
            except ValueError as exc:
                errors.append(str(exc))
                continue
            try:
                stated_path = Path(str(item.get("path") or "")).resolve()
                if stated_path != path:
                    errors.append(f"{run_id}: handoff artifact path is outside the declared upstream run")
                    continue
            except OSError:
                errors.append(f"{run_id}: handoff artifact path cannot be resolved")
                continue
            if not path.is_file():
                errors.append(f"{run_id}: missing handoff file {path}")
                continue
            expected = str(item.get("sha256") or "")
            actual = _sha256_file(path)
            if expected != actual:
                errors.append(
                    f"{run_id}: handoff hash mismatch for "
                    f"{item.get('run_relative_path') or path.name}"
                )
    downstream = grounding.get("downstream_contract") or {}
    accepted = {str(value) for value in downstream.get("accepts") or []}
    if grounding.get("downstream_mode") and downstream and not downstream.get("contract_pinned"):
        errors.append("downstream product contract is not pinned in the task frame")
    # Same rule as `_validate_downstream_compatibility`, and it must STAY the same rule: these two
    # used to disagree about an empty `accepts` — this one skipped the check, that one refused every
    # upstream — so whether a chain was legal depended on which validator happened to run.
    downstream_mode_name = str(grounding.get("downstream_mode") or "downstream")
    for run in grounding.get("upstream_runs") or []:
        product = str((run.get("product_contract") or {}).get("product_version") or "")
        if not product:
            continue
        if not accepted:
            if _declares_no_upstream_contract(downstream_mode_name):
                errors.append(
                    _entry_point_refusal(downstream_mode_name, str(run.get("run_id")), product))
        elif product not in accepted:
            errors.append(
                f"mode handoff mismatch: downstream accepts {sorted(accepted)}, "
                f"but upstream {run.get('run_id')!r} provides {product!r}"
            )
    if grounding.get("downstream_mode"):
        accepted_delivery = {
            str(value) for value in (downstream.get("accepts_delivery_statuses") or ["USABLE"])
        }
        for run in grounding.get("upstream_runs") or []:
            contract = run.get("product_contract") or {}
            run_id = str(run.get("run_id") or "?")
            if not contract.get("contract_pinned"):
                errors.append(f"{run_id}: upstream product contract is not pinned")
            if str(run.get("run_status") or "") != "done":
                errors.append(f"{run_id}: upstream run is not complete")
            missing = [str(item) for item in (run.get("missing_declared_artifacts") or [])]
            if missing:
                errors.append(f"{run_id}: missing declared handoff artifact(s): {', '.join(missing)}")
            delivery = str(run.get("delivery_status") or "UNKNOWN")
            if delivery not in accepted_delivery:
                errors.append(
                    f"{run_id}: downstream does not accept upstream delivery status {delivery!r}"
                )
    return errors


def _declares_no_upstream_contract(downstream_mode: str) -> bool:
    """True only for a REGISTERED mode whose `handoff.accepts` is empty — i.e. a real entry point.

    A name the registry does not know (a synthetic fixture mode, a legacy run recorded before its
    mode existed) also yields an empty `accepts`, but it means "unknown", not "root". Refusing those
    would turn a missing registry entry into a chaining error, so they keep the older permissive
    behaviour: nothing is declared, so nothing is checked.
    """
    return downstream_mode in (load_mode_registry().get("modes") or {})


def _entry_point_refusal(downstream_mode: str, run_id: str, product: str) -> str:
    """The message an ENTRY-POINT mode gives when someone tries to chain a run into it.

    An empty `handoff.accepts` means "this mode consumes no upstream RUN" — `ingest_paper` takes a
    PDF, not another run's product. Saying `accepts []` made that look like a registry gap rather
    than a designed property, so the reader could not tell a root mode from an unfinished one.
    """
    return (f"{downstream_mode!r} is an entry-point mode: it declares no upstream contract "
            f"(handoff.accepts is empty) and consumes no prior run, so it cannot be chained. "
            f"Upstream {run_id!r} provides {product!r}. Start {downstream_mode!r} without "
            f"--upstream-run, or chain into a mode that accepts {product!r}.")


def _validate_downstream_compatibility(runs: list[dict], downstream_mode: Optional[str],
                                       downstream_contract: Optional[dict] = None) -> None:
    if not downstream_mode:
        return
    downstream = downstream_contract or _normalise_contract(_mode_handoff(downstream_mode), pinned=False)
    accepted = {str(value) for value in downstream.get("accepts") or []}
    for run in runs:
        product = str((run.get("product_contract") or {}).get("product_version") or "")
        if not product:
            continue
        if not accepted:
            if _declares_no_upstream_contract(downstream_mode):
                raise ValueError(
                    _entry_point_refusal(downstream_mode, str(run.get("run_id")), product))
            continue        # unregistered mode: nothing declared, so nothing to check
        if product not in accepted:
            raise ValueError(
                f"mode handoff mismatch: {downstream_mode!r} accepts {sorted(accepted)}, "
                f"but upstream {run.get('run_id')!r} provides {product!r}"
            )


def upstream_grounding(prev_run_dirs: List[str], downstream_mode: Optional[str] = None,
                       downstream_contract: Optional[dict] = None) -> dict:
    """Compact handoff extracted from each completed upstream link (mode + request + REPORT summary +
    any ranked idea backlog + the on-disk key artifacts to read by reference). Robust to missing
    files — a link with nothing readable contributes an empty-but-named entry, never an exception."""
    runs: List[dict] = []
    for rd in prev_run_dirs:
        d = Path(rd)
        entry: dict = {"run_id": d.name, "run_dir": str(d.resolve()), "mode": "",
                       "request": "", "summary": "", "top_ideas": [],
                       "key_artifacts": [], "reusable_inputs": [],
                       "artifact_manifest": [], "run_status": "unknown",
                       "delivery_status": "UNKNOWN", "project": "",
                       "product_contract": {}, "missing_declared_artifacts": []}
        payload: dict = {}
        tf = _read_json(d / "task_frame.artifact.json")
        if tf:
            payload = tf.get("payload") or {}
            entry["mode"] = payload.get("mode") or ""
            entry["request"] = payload.get("request_text") or ""
            entry["run_id"] = payload.get("task_id") or d.name
            entry["project"] = payload.get("project") or ""
        manifest = _read_yaml(d / "manifest.yaml") or {}
        entry["run_status"] = str(manifest.get("status") or "unknown")
        entry["product_contract"] = _contract_for_run(payload, str(entry["mode"]))
        report = d / "evidence" / "REPORT" / "report-note.artifact.json"
        rn = _read_json(report)
        if rn:
            report_payload = rn.get("payload") or {}
            entry["summary"] = report_payload.get("summary") or ""
            entry["delivery_status"] = str(
                report_payload.get("markdown_delivery_status")
                or report_payload.get("delivery_status")
                or ("USABLE" if entry["run_status"] == "done" else "UNKNOWN")
            )
            entry["delivery_caveats"] = [
                str(item) for item in (report_payload.get("delivery_caveats") or [])
                if str(item).strip()
            ]
            entry["key_artifacts"].append(str(report))
        backlog = d / "evidence" / "IDEATE" / "idea-backlog.artifact.json"
        bl = _read_json(backlog)
        if bl:
            ranked = ((bl.get("payload") or {}).get("ranked_ideas")) or []
            entry["top_ideas"] = [{"idea_id": i.get("idea_id"), "summary": i.get("summary")}
                                  for i in ranked[:5] if isinstance(i, dict)]
            entry["key_artifacts"].append(str(backlog))
        fallback_candidates = (
            d / "inbox" / "search-results.json",
            d / "evidence" / "DISCOVER" / "evidence-table.artifact.json",
            d / "evidence" / "DISCOVER" / "source-quality-report.artifact.json",
            d / "evidence" / "DISCOVER" / "claim-list.artifact.json",
            d / "evidence" / "DISCOVER" / "claim-evidence-map.artifact.json",
            d / "evidence" / "DISCOVER" / "citation-attribution-report.artifact.json",
            d / "evidence" / "DISCOVER" / "contradiction-report.artifact.json",
            d / "evidence" / "DISCOVER" / "landscape-map.artifact.json",
            d / "evidence" / "DISCOVER" / "gap-dossiers.artifact.json",
        )
        declared, missing = _declared_files(d, entry["product_contract"])
        entry["missing_declared_artifacts"] = missing
        primary = str(entry["product_contract"].get("primary_markdown") or "")
        for path in declared:
            if primary and path.match(primary.replace("<paper>", "*")):
                entry["key_artifacts"].append(str(path.resolve()))
        entry["reusable_inputs"] = [
            str(path.resolve()) for path in declared + list(fallback_candidates) if path.is_file()
        ]
        manifested_paths = []
        for raw_path in entry["key_artifacts"] + entry["reusable_inputs"]:
            path = Path(raw_path)
            if path.is_file() and path.resolve() not in manifested_paths:
                manifested_paths.append(path.resolve())
                entry["artifact_manifest"].append(_manifest_item(path, d))
        runs.append(entry)
    if downstream_mode and downstream_contract is None:
        downstream_contract = _normalise_contract(_mode_handoff(downstream_mode), pinned=False)
    _validate_downstream_compatibility(runs, downstream_mode, downstream_contract)
    return {
        "handoff_contract_version": HANDOFF_CONTRACT_VERSION,
        "downstream_mode": downstream_mode or "",
        "downstream_contract": downstream_contract or {},
        "upstream_runs": runs,
    }


def write_upstream_grounding(new_run_dir: str, prev_run_dirs: List[str],
                              downstream_mode: Optional[str] = None) -> str:
    """Write the downstream run's `inbox/upstream-grounding.json` from the upstream links. Returns
    the path. Called by `operate begin --upstream-run <prev>` before the first worker is built."""
    root = Path(new_run_dir).resolve()
    _ensure_directory_inside(root, "inbox", label="upstream grounding inbox")
    out = _path_inside(root, (Path("inbox") / UPSTREAM_GROUNDING_FILE).as_posix(),
                       label="upstream grounding manifest")
    task_frame = _read_json(root / "task_frame.artifact.json") or {}
    payload = task_frame.get("payload") or {}
    pinned_downstream = _contract_for_run(payload, str(payload.get("mode") or downstream_mode or ""))
    grounding = upstream_grounding(prev_run_dirs, downstream_mode, pinned_downstream)
    readiness_errors = validate_upstream_grounding(grounding)
    if readiness_errors:
        raise ValueError("upstream handoff readiness failed: " + "; ".join(readiness_errors))
    grounding["citation_snapshot_handoff"] = materialize_upstream_citation_snapshots(
        new_run_dir, grounding
    )
    _write_json_atomic(root,
                        (Path("inbox") / UPSTREAM_GROUNDING_FILE).as_posix(),
                        grounding, label="upstream grounding manifest")
    return str(out)


def _grounding_block(run_dir: str, grounding: dict) -> str:
    lines = [
        "",
        "",
        "--- PRIOR CHAIN CONTEXT (this run CONTINUES a director-approved research chain) ---",
        "This is NOT a fresh start: earlier links already produced grounded, gated results. The full "
        f"handoff is `{run_dir}/inbox/{UPSTREAM_GROUNDING_FILE}` — read it by reference. In brief:",
    ]
    for up in grounding.get("upstream_runs") or []:
        mode = up.get("mode") or "?"
        rid = up.get("run_id") or "?"
        summ = (up.get("summary") or "").strip() or "(no REPORT summary on disk)"
        lines.append(f"  • [{mode} · {rid}] {summ}")
        arts = up.get("key_artifacts") or []
        if arts:
            lines.append(f"      key artifacts (read by reference, do NOT redo): {', '.join(arts)}")
        reusable = up.get("reusable_inputs") or []
        if reusable:
            lines.append(
                "      frozen reusable evidence (reuse before new retrieval): "
                + ", ".join(reusable)
            )
        if str(up.get("delivery_status") or "") == "USABLE_WITH_CAVEATS":
            caveats = [str(item) for item in (up.get("delivery_caveats") or []) if str(item).strip()]
            suffix = "; ".join(caveats) if caveats else "upstream evidence is usable only with caveats"
            lines.append(
                "      CAUTION: carry this upstream limitation forward; do not turn it into a novelty "
                f"or method-effect claim: {suffix}"
            )
        ideas = up.get("top_ideas") or []
        if ideas:
            ids = ", ".join(str(i.get("idea_id")) for i in ideas if i.get("idea_id"))
            if ids:
                lines.append(f"      candidate ideas carried in: {ids}")
    citation_handoff = grounding.get("citation_snapshot_handoff") or {}
    if int(citation_handoff.get("n_snapshots") or 0):
        lines.append(
            "  • hash-verified upstream citation snapshots are materialized locally at "
            f"`{citation_handoff.get('manifest_ref')}`; use its rebased claim maps rather than "
            "external snapshot paths."
        )
    lines.append(
        "Build the NEXT step ON this established ground; do not repeat upstream work. If the upstream "
        "output conflicts with your inputs, SAY SO rather than silently diverging — you never re-scope.")
    return "\n".join(lines)


def _grounding_pointer_block(run_dir: str) -> str:
    return (
        "\n\n--- PRIOR CHAIN CONTEXT (pointer only) ---\n"
        f"The root worker already receives the full upstream handoff. Read `{run_dir}/inbox/"
        f"{UPSTREAM_GROUNDING_FILE}` only if a direct scientific dependency is absent from your "
        "predecessor bundle; do not repeat upstream retrieval or synthesis."
    )


def augment_worker_with_upstream(worker: Optional[dict], run_dir: str) -> Optional[dict]:
    """Append the PRIOR CHAIN CONTEXT block to a worker spec's prompt(s) when this run has upstream
    grounding (a no-op otherwise, so single-mode runs are untouched). Handles both worker shapes: a
    single `{prompt: ...}` and a panel `{workers: [{prompt: ...}, ...]}`."""
    if not worker:
        return worker
    p = Path(run_dir) / "inbox" / UPSTREAM_GROUNDING_FILE
    grounding = _read_json(p)
    if not grounding or not (grounding.get("upstream_runs")):
        return worker
    integrity_errors = validate_upstream_grounding(grounding)
    integrity_errors.extend(validate_materialized_citation_snapshots(run_dir, grounding))
    ledger_path = Path(run_dir) / "ledger.jsonl"
    if not ledger_path.is_file():
        integrity_errors.append("upstream handoff ledger is missing")
    else:
        events = read_events(ledger_path)
        ledger_errors = verify_chain(events)
        if ledger_errors:
            integrity_errors.append("upstream handoff ledger chain is invalid: " + "; ".join(ledger_errors))
        else:
            pin = last_of_type(events, "upstream_handoff_pinned")
            if pin is None:
                integrity_errors.append("upstream handoff manifest is not pinned in the run ledger")
            elif str((pin.get("payload") or {}).get("grounding_sha256") or "") != _sha256_file(p):
                integrity_errors.append("upstream handoff manifest hash does not match its ledger pin")
    if integrity_errors:
        raise ValueError("upstream handoff integrity failed: " + "; ".join(integrity_errors))
    block = _grounding_block(run_dir, grounding)
    pointer = _grounding_pointer_block(run_dir)
    if "workers" in worker and isinstance(worker.get("workers"), list):
        for w in worker["workers"]:
            if isinstance(w, dict) and isinstance(w.get("prompt"), str):
                dependencies = list(w.get("depends_on") or [])
                w["prompt"] = w["prompt"] + (pointer if dependencies else block)
    elif isinstance(worker.get("prompt"), str):
        worker["prompt"] = worker["prompt"] + block
    return worker


def unchained_upstream_advisory(runs_dir: str, project: str, downstream_mode: str) -> Optional[dict]:
    """Name the chain the director could have made but did not — at `begin`, before any worker runs.

    `--upstream-run` has always worked; nothing ever pointed out that it was MISSING. A mode that
    declares `handoff.accepts` is saying, in the registry, that it is designed to consume a prior
    run's product; starting it bare is legal but is usually an oversight, and the cost only surfaces
    much later when the downstream product turns out to contradict a finding it never read.

    Returns ``None`` when there is nothing to say — an entry-point mode (empty `accepts`), or no
    completed run in this project whose product the mode accepts. Advisory only: it never blocks,
    because chaining is the director's call and a deliberate fresh start is legitimate.
    """
    accepts = {str(x) for x in (_mode_handoff(downstream_mode).get("accepts") or [])}
    if not accepts:
        return None
    project_root = Path(runs_dir) / project
    if not project_root.is_dir():
        return None
    candidates: list[dict] = []
    for run_dir in sorted(project_root.iterdir()):
        if not run_dir.is_dir():
            continue
        payload = (_read_json(run_dir / "task_frame.artifact.json") or {}).get("payload") or {}
        mode = str(payload.get("mode") or "")
        if not mode:
            continue
        product = str(_contract_for_run(payload, mode).get("product_version") or "")
        if product not in accepts:
            continue
        if str((_read_yaml(run_dir / "manifest.yaml") or {}).get("status") or "") != "done":
            continue        # an unfinished run is not a handoff; readiness validation would refuse it
        report = (_read_json(run_dir / "evidence" / "REPORT" / "report-note.artifact.json") or {})
        candidates.append({
            "run_id": str(payload.get("task_id") or run_dir.name),
            "mode": mode,
            "product_version": product,
            "summary": str((report.get("payload") or {}).get("summary") or "")[:240],
        })
    if not candidates:
        return None
    ids = ", ".join(c["run_id"] for c in candidates)
    return {
        "status": "NOT_CHAINED",
        "downstream_mode": downstream_mode,
        "accepts": sorted(accepts),
        "available_upstream_runs": candidates,
        "note": (f"{downstream_mode!r} declares it can consume {sorted(accepts)}, and this project "
                 f"has {len(candidates)} completed run(s) it would accept, but this run was started "
                 f"with no --upstream-run. It will NOT read them. If that is not what you meant, "
                 f"re-begin with: --upstream-run {ids}"),
    }
