"""Deterministic, run-local scheduling for operated multi-worker panels.

Modes describe the whole panel.  This module exposes only the next legal wave,
after predecessor outputs and declared input scopes have been checked.  It does
not claim an OS-level read sandbox: every dispatched worker receives a frozen
input manifest, while hard filesystem isolation remains a runner capability.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
from copy import deepcopy
from pathlib import Path
from typing import Iterable, Optional

import yaml

from ..tools._latex_sandbox import LatexSandboxViolation, atomic_write_bytes
from ..tools.budget_tracker import BudgetExceeded, assert_within
from ..tools.manuscript_security import ManuscriptPathViolation, validate_run_owned_path
from .bounded_repair import load_state
from .output_versions import (
    finalize_output,
    physical_output,
    prepare_plan,
    resolve_effective_output,
)
from ..tools.validate_artifact import validate_payload


CONTRACT_VERSION = "panel-dispatch/v1"

# Compatibility is resolved at the dispatch boundary so old inline mode code
# cannot leak an ambiguous role into receipts or connectivity checks.
CANONICAL_AGENT_LABELS = {
    "discover-worker": "direction-grounding-scout",
}

# Deterministic non-worker barriers currently emitted by operated modes.  A
# mode may name one of these in ``depends_on``; the receipt itself must exist
# before the downstream worker can be released.
EXTERNAL_DEPENDENCY_REFS = {
    "freeze-venue-precommit": ("inbox/VERIFY.precommit.receipt.json",),
    "freeze-blind-review-panel": ("inbox/VERIFY.reviews.receipt.json",),
}

# Stateful modes may return ``None`` only after their own staged builders see
# all outputs. Require the corresponding scheduler receipts before treating
# that state as complete; otherwise prewritten files could bypass dispatch.
REQUIRED_STAGE_WORKERS = {
    ("venue_readiness", "VERIFY"): {
        "venue-selector",
        "venue-review-configurator",
        "venue-reviewer-methodology",
        "venue-reviewer-domain",
        "venue-reviewer-adversarial",
        "area-chair-synthesizer",
    },
}

_ROOT = Path(__file__).resolve().parents[1]
_ROSTER = _ROOT / "orchestrator" / "roster.yaml"
_GRAPH = _ROOT / "orchestrator" / "graph.yaml"
_MODES = _ROOT / "orchestrator" / "mode_registry.yaml"


class PanelContractError(ValueError):
    """A panel cannot be scheduled without weakening its declared contract."""


def canonical_agent_label(label: str) -> str:
    raw = str(label or "").strip()
    return CANONICAL_AGENT_LABELS.get(raw, raw)


def _load_yaml(path: Path) -> dict:
    value = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(value, dict):
        raise PanelContractError(f"scheduler registry is not an object: {path}")
    return value


def worker_labels(spec: Optional[dict]) -> list[str]:
    if not spec:
        return []
    workers = spec.get("workers") if isinstance(spec, dict) else None
    rows = workers if isinstance(workers, list) else [spec]
    return [canonical_agent_label(row.get("label")) for row in rows if isinstance(row, dict)]


def validate_worker_spec_connectivity(mode: str, stage: str, spec: Optional[dict]) -> list[str]:
    """Validate actual ``llm_step`` labels against roster, graph, mode, and specs."""
    labels = worker_labels(spec)
    if not labels:
        return []
    roster_doc = _load_yaml(_ROSTER).get("agents") or {}
    roster = {
        str(agent)
        for group in roster_doc.values()
        for agent in (group or [])
    }
    graph = _load_yaml(_GRAPH).get("stages") or {}
    stage_agents = set((graph.get(stage) or {}).get("allowed_agents") or [])
    modes = _load_yaml(_MODES).get("modes") or {}
    mode_agents = set((modes.get(mode) or {}).get("agent_subset") or [])
    errors: list[str] = []
    for label in labels:
        if not label:
            errors.append(f"{mode}/{stage}: worker has an empty label")
            continue
        if label not in roster:
            errors.append(f"{mode}/{stage}: actual worker {label!r} is absent from roster")
        if label not in stage_agents:
            errors.append(f"{mode}/{stage}: actual worker {label!r} is absent from graph stage")
        if label not in mode_agents:
            errors.append(f"{mode}/{stage}: actual worker {label!r} is absent from mode agent_subset")
        if not (_ROOT / "agents" / f"{label}.md").is_file():
            errors.append(f"{mode}/{stage}: actual worker {label!r} has no agent spec")
    return errors


def _task_payload(run_dir: Path) -> dict:
    path = run_dir / "task_frame.artifact.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PanelContractError(f"cannot read scheduler task frame at {path}: {exc}") from exc
    payload = value.get("payload") if isinstance(value, dict) else None
    if not isinstance(payload, dict):
        raise PanelContractError(f"scheduler task frame has no payload object: {path}")
    return payload


def _output_path(run_dir: Path, raw: object) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise PanelContractError("every scheduled worker needs a non-empty output path")
    path = Path(raw)
    if not path.is_absolute():
        # Mode builders sometimes emit a cwd-relative path which already
        # contains the run root. Resolve that spelling once before treating a
        # genuinely run-relative path (for example inbox/x.json) as local.
        cwd_candidate = path.resolve(strict=False)
        try:
            cwd_candidate.relative_to(run_dir.resolve())
            path = cwd_candidate
        except ValueError:
            path = run_dir / path
    resolved = path.resolve(strict=False)
    try:
        resolved.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise PanelContractError(f"worker output escapes the run directory: {resolved}") from exc
    return resolved


def _rel(run_dir: Path, path: Path) -> str:
    return path.resolve(strict=False).relative_to(run_dir.resolve()).as_posix()


def _normal_pattern(run_dir: Path, raw: object) -> str:
    text = str(raw or "").strip().replace("\\", "/")
    if not text:
        return text
    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve(strict=False).relative_to(run_dir.resolve()).as_posix()
        except ValueError:
            return path.resolve(strict=False).as_posix()
    return text.lstrip("./")


def _matches(path: str, pattern: str) -> bool:
    p = path.replace("\\", "/")
    q = pattern.replace("\\", "/")
    return p == q or fnmatch.fnmatchcase(p, q) or Path(p).match(q)


def _patterns_overlap(left: str, right: str) -> bool:
    return left == right or _matches(left, right) or _matches(right, left)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _claim_evidence_contract_error(path: Path, reason: str) -> PanelContractError:
    """Return the non-migrating failure for a current evidence_deep linker bundle."""
    return PanelContractError(
        "evidence_deep claim-evidence-linker output contract BLOCK at "
        f"{path}: expected claim_evidence_map with attribution_contract_version='claim-span/v1' "
        f"and mappings[].loci[]; {reason}. Citation-coverage-auditor and downstream workers "
        "are not released. Re-run claim-evidence-linker with the current worker contract because "
        "the legacy claims/evidence shape cannot provide strict machine-verifiable exact-span "
        "provenance. If only an old bundle is available, start a new evidence_deep run; automatic "
        "migration is intentionally disabled."
    )


def _validate_current_worker_output_contract(mode: str, stage: str, node: dict, path: Path) -> None:
    """Validate load-bearing current-run output before a dependent worker can be released.

    The generic scheduler normally only needs an output file to exist.  For
    evidence_deep, citation auditing is meaningful only when the linker emitted
    the current strict claim-span contract.  Validate that producer at the
    scheduler boundary rather than allowing a legacy ``claims/evidence`` shape
    to unlock the citation auditor and fail much later.
    """
    if (mode, stage, node.get("label")) != ("evidence_deep", "DISCOVER", "claim-evidence-linker"):
        return
    try:
        bundle = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise _claim_evidence_contract_error(path, f"bundle is unreadable JSON ({exc})") from exc
    claim_map = bundle.get("claim_evidence_map") if isinstance(bundle, dict) else None
    if not isinstance(claim_map, dict):
        raise _claim_evidence_contract_error(path, "bundle has no object-valued claim_evidence_map")
    if claim_map.get("attribution_contract_version") != "claim-span/v1":
        legacy_hint = "legacy claims/evidence fields detected" if "claims" in claim_map else (
            "missing or unsupported attribution_contract_version"
        )
        raise _claim_evidence_contract_error(path, legacy_hint)
    errors = validate_payload("claim_evidence_map", claim_map)
    if errors:
        detail = "; ".join(str(row) for row in errors[:5])
        if len(errors) > 5:
            detail += f"; plus {len(errors) - 5} more schema error(s)"
        raise _claim_evidence_contract_error(path, f"current claim-span schema validation failed: {detail}")


def _repair_cycle(run_dir: Path, stage: str) -> dict:
    try:
        state = load_state(run_dir)
    except (OSError, ValueError) as exc:
        raise PanelContractError(f"invalid repair state: {exc}") from exc
    attempts = [row for row in state["attempts"] if row.get("stage") == stage]
    if not attempts:
        return {"cycle": 0, "attempt": None, "targets": set()}
    latest = attempts[-1]
    targets = {
        canonical_agent_label(agent)
        for agent in (latest.get("target_agents") or []) + (latest.get("refresh_agents") or [])
        if str(agent).strip()
    }
    return {"cycle": len(attempts), "attempt": latest, "targets": targets}


def _infer_plain_repair_targets(nodes: list[dict], attempt: Optional[dict]) -> set[str]:
    """Infer an owner from the named bundle/artifact before using a legacy fallback.

    Plain historical GateBlocks do not carry ``target_agents``. Matching the
    failure text to a worker's logical output prevents an unrelated terminal
    worker from being repeatedly asked to repair another seat's bundle.
    """
    reason = "".join(ch for ch in str((attempt or {}).get("reason") or "").lower() if ch.isalnum())
    if not reason:
        return set()
    labels = set()
    # Some validation failures name a typed collection rather than the worker
    # output filename.  Keep this narrow, explicit mapping before the legacy
    # terminal-worker fallback so a leaf payload never gets "repaired" by a
    # downstream synthesizer that cannot alter it.
    collection_owners = {
        "stalenessreports": "staleness-auditor",
        "sourcequality": "source-quality-ranker",
        "datasetcards": "dataset-card-builder",
        "invalidationproposals": "contradiction-miner",
        "claimevidencemap": "claim-evidence-linker",
    }
    known_labels = {str(node.get("label") or "") for node in nodes}
    for marker, owner in collection_owners.items():
        if marker in reason and owner in known_labels:
            labels.add(owner)
    for node in nodes:
        output_name = Path(str(node.get("output_rel") or "")).name.split(".", 1)[0]
        candidates = (str(node.get("label") or ""), output_name)
        for candidate in candidates:
            token = "".join(ch for ch in candidate.lower() if ch.isalnum())
            if len(token) >= 5 and token in reason:
                labels.add(str(node["label"]))
                break
    return labels


def _feedback_for_agent(context: dict, agent: str) -> Optional[str]:
    attempt = context.get("attempt")
    if not attempt:
        return None
    if context.get("targets") and agent not in context["targets"]:
        return None
    rows = []
    for defect in attempt.get("defects") or []:
        affected = set(defect.get("target_agents") or []) | set(defect.get("refresh_agents") or [])
        if not affected or agent in affected:
            rows.append(defect)
    if rows:
        details = "\n".join(
            f"- {row.get('defect_id', 'DEFECT')}: {row.get('location', 'unspecified')}: "
            f"{row.get('summary') or row.get('reason') or 'supplement required'}"
            for row in rows
        )
    else:
        details = str(attempt.get("reason") or "targeted supplement required")[:12000]
    return (
        f"TARGETED REPAIR {context['cycle']} for {agent}. Preserve every unaffected finding.\n"
        f"{details}\nWrite one complete corrected version to the scheduler-provided supplement path."
    )


def _receipt_path(run_dir: Path, stage: str) -> Path:
    safe = "".join(ch for ch in stage if ch.isalnum() or ch in "-_")
    if not safe:
        raise PanelContractError(f"invalid stage name for scheduler receipt: {stage!r}")
    return run_dir / "inbox" / "panel-scheduler" / f"{safe}.json"


def _load_receipt(path: Path, stage: str) -> dict:
    if not path.is_file():
        return {
            "contract_version": CONTRACT_VERSION,
            "stage": stage,
            "authorizations": [],
            "waves": [],
        }
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PanelContractError(f"invalid scheduler receipt at {path}: {exc}") from exc
    if value.get("contract_version") != CONTRACT_VERSION or value.get("stage") != stage:
        raise PanelContractError(f"scheduler receipt contract mismatch at {path}")
    if not isinstance(value.get("authorizations"), list) or not isinstance(value.get("waves"), list):
        raise PanelContractError(f"scheduler receipt lists are malformed at {path}")
    return value


def _save_receipt(run_dir: Path, path: Path, receipt: dict) -> None:
    """Publish a receipt only into the scheduler-owned run directory."""
    root = Path(run_dir).absolute()
    target = Path(path).absolute()
    receipt_root = root / "inbox" / "panel-scheduler"
    if target.parent != receipt_root:
        raise PanelContractError("unsafe scheduler receipt path: unexpected receipt location")
    try:
        validate_run_owned_path(
            target,
            run_root=root,
            purpose="write",
            owned_output_roots=(receipt_root,),
        )
        atomic_write_bytes(
            target,
            (json.dumps(receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
        )
    except (ManuscriptPathViolation, LatexSandboxViolation) as exc:
        raise PanelContractError(f"unsafe scheduler receipt path: {exc}") from exc


def _finalized_noop_supplement(run_dir: Path, row: dict) -> bool:
    output = str(row.get("output") or "").replace("\\", "/")
    if "/supplements/" not in f"/{output}":
        return False
    path = run_dir / output
    repair_dir = path.parent.parent if path.parent.name == "corrected" else None
    plan_path = repair_dir / "repair-plan.json" if repair_dir else None
    if not plan_path or not plan_path.is_file():
        return False
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    logical = str(row.get("logical_output") or "").replace("\\", "/")
    for item in plan.get("outputs") or []:
        if str(item.get("logical_output") or "").replace("\\", "/") != logical:
            continue
        return bool(
            item.get("completed_at")
            and item.get("output_sha256")
            and item.get("output_sha256") == item.get("supersedes_sha256")
            and not (item.get("changed_paths") or [])
        )
    return False


def _authorization_counts(run_dir: Path) -> dict[str, int]:
    counts = {"initial": 0, "supplement": 0}
    root = run_dir / "inbox" / "panel-scheduler"
    for path in root.glob("*.json") if root.is_dir() else []:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise PanelContractError(f"invalid scheduler receipt at {path}: {exc}") from exc
        # The scheduler directory is reserved, but tolerate older ad-hoc
        # validation reports by ignoring files that are plainly not receipts.
        if "authorizations" not in value or "waves" not in value or "stage" not in value:
            continue
        if value.get("contract_version") != CONTRACT_VERSION:
            raise PanelContractError(f"scheduler receipt contract mismatch at {path}")
        for row in value.get("authorizations") or []:
            kind = row.get("authorization_kind")
            if kind not in counts:
                kind = "supplement" if "/supplements/" in str(row.get("output") or "").replace("\\", "/") else "initial"
            if kind == "supplement" and _finalized_noop_supplement(run_dir, row):
                continue
            counts[kind] += 1
    return counts


def _all_authorization_count(run_dir: Path) -> int:
    counts = _authorization_counts(run_dir)
    return counts["initial"] + counts["supplement"]


def _authorization_report(run_dir: Path) -> dict[str, int]:
    counts = _authorization_counts(run_dir)
    return {
        "authorized_agent_hops": counts["initial"] + counts["supplement"],
        "authorized_initial_hops": counts["initial"],
        "authorized_supplement_hops": counts["supplement"],
    }


def _supplement_limit(budget: dict, nodes: list[dict]) -> int:
    """The repair-wave seat ceiling for THIS mode — never a shared constant.

    Director lock (2026-08-04): *"agents 预算上限不需要共享，独立按 modes 算."*  The initial-dispatch
    ceiling (`max_agent_hops`) was already per-mode, mandatory (`orchestrator/graph_spec.py`) and blind
    to any upstream run, so chaining runs never pooled it.  The repair ceiling was not: a single
    hardcoded 12 that 25 of the 26 modes silently inherited, which let a 2-seat mode carry a 13-seat
    mode's headroom.

    Resolution order, both per-mode:
      1. an explicit `max_supplement_agent_hops` in the mode's OWN registry budget — its own contract;
      2. otherwise derived from the mode's OWN panel: one re-dispatch per seat it may schedule.

    Derived, not tabulated, so it cannot rot when a mode's roster changes.
    """
    declared = budget.get("max_supplement_agent_hops")
    if isinstance(declared, int) and declared > 0:
        return declared
    return max(1, len(nodes))


def _apply_director_supplement_extension(run_dir: Path, budget: dict) -> dict:
    path = run_dir / "inbox" / "director-supplement-budget-extension.json"
    if not path.is_file():
        return budget
    try:
        extension = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise PanelContractError(f"invalid director supplement extension: {exc}") from exc
    base = budget.get("max_supplement_agent_hops")
    if (
        extension.get("contract_version") != "director-supplement-extension/v1"
        or extension.get("authorized_by") != "director"
        or extension.get("dimension") != "max_supplement_agent_hops"
        or extension.get("base_limit") != base
        or not isinstance(extension.get("extended_limit"), int)
        or extension["extended_limit"] <= int(base or 0)
        or not str(extension.get("reason") or "").strip()
    ):
        raise PanelContractError(
            "director supplement extension must bind the current base limit, a larger integer "
            "limit, director authority, and a non-empty reason"
        )
    effective = dict(budget)
    effective["max_supplement_agent_hops"] = extension["extended_limit"]
    return effective


def _normalize_nodes(run_dir: Path, spec: dict) -> tuple[list[dict], list[list[dict]]]:
    raw_workers = spec.get("workers")
    workers = raw_workers if isinstance(raw_workers, list) else [spec]
    if not workers or any(not isinstance(worker, dict) for worker in workers):
        raise PanelContractError("panel workers must be a non-empty list of objects")

    nodes = []
    outputs = set()
    for index, raw_worker in enumerate(workers):
        worker = deepcopy(raw_worker)
        source_label = str(worker.get("label") or "").strip()
        label = canonical_agent_label(source_label)
        if not label:
            raise PanelContractError(f"worker #{index + 1} has an empty label")
        output_path = _output_path(run_dir, worker.get("output"))
        output_rel = _rel(run_dir, output_path)
        if output_rel in outputs:
            raise PanelContractError(f"two workers declare the same output: {output_rel}")
        outputs.add(output_rel)
        worker["label"] = label
        if source_label != label:
            worker["source_label"] = source_label
        nodes.append({
            "index": index,
            "id": f"{index}:{label}:{output_rel}",
            "source_label": source_label,
            "label": label,
            "worker": worker,
            "output_path": output_path,
            "output_rel": output_rel,
            "barrier_deps": set(),
            "data_deps": set(),
            "external_deps": set(),
        })

    by_label: dict[str, list[dict]] = {}
    for node in nodes:
        by_label.setdefault(node["label"], []).append(node)

    raw_order = spec.get("worker_order")
    if raw_order is None:
        ordered = list(nodes)
    else:
        if not isinstance(raw_order, list):
            raise PanelContractError("worker_order must be a list")
        available = {label: list(rows) for label, rows in by_label.items()}
        ordered = []
        for raw_label in raw_order:
            label = canonical_agent_label(raw_label)
            candidates = available.get(label) or []
            if not candidates:
                raise PanelContractError(f"worker_order names unknown or duplicate worker {raw_label!r}")
            ordered.append(candidates.pop(0))
        leftovers = [node for rows in available.values() for node in rows]
        if leftovers:
            raise PanelContractError(
                "worker_order omits workers: " + ", ".join(node["label"] for node in leftovers)
            )

    raw_groups = spec.get("parallel_groups")
    if raw_groups is None:
        # A panel that declares real dependencies is already a DAG. Keep every
        # node in one scheduling pool and let ``depends_on`` release the widest
        # legal wave dynamically. Legacy panels with no dependency declarations
        # retain their historical serial behavior, because order may be their
        # only (implicit) scientific contract.
        has_declared_dependencies = any(
            list(node["worker"].get("depends_on") or [])
            or list((node["worker"].get("input_contract") or {}).get(
                "allowed_bundle_agents"
            ) or [])
            for node in ordered
        )
        groups = [list(ordered)] if has_declared_dependencies else [[node] for node in ordered]
    else:
        if not isinstance(raw_groups, list) or any(not isinstance(group, list) for group in raw_groups):
            raise PanelContractError("parallel_groups must be a list of worker-label lists")
        available = {label: list(rows) for label, rows in by_label.items()}
        groups = []
        for raw_group in raw_groups:
            group = []
            for raw_label in raw_group:
                label = canonical_agent_label(raw_label)
                candidates = available.get(label) or []
                if not candidates:
                    raise PanelContractError(
                        f"parallel_groups names unknown or duplicate worker {raw_label!r}"
                    )
                group.append(candidates.pop(0))
            if not group:
                raise PanelContractError("parallel_groups cannot contain an empty wave")
            groups.append(group)
        leftovers = [node for rows in available.values() for node in rows]
        if leftovers:
            raise PanelContractError(
                "parallel_groups omits workers: " + ", ".join(node["label"] for node in leftovers)
            )

    prior: list[dict] = []
    group_barriers = bool(spec.get("group_barriers", True))
    for group_index, group in enumerate(groups):
        for node in group:
            node["group"] = group_index
            if group_barriers:
                node["barrier_deps"].update(dep["id"] for dep in prior)
        prior.extend(group)

    for node in nodes:
        worker = node["worker"]
        explicit = list(worker.get("depends_on") or [])
        contract = worker.get("input_contract") or {}
        explicit.extend(contract.get("allowed_bundle_agents") or [])
        for raw_dep in explicit:
            dep_label = canonical_agent_label(raw_dep)
            matches = [candidate for candidate in by_label.get(dep_label, []) if candidate is not node]
            if matches:
                node["barrier_deps"].update(dep["id"] for dep in matches)
                node["data_deps"].update(dep["id"] for dep in matches)
            elif str(raw_dep) in EXTERNAL_DEPENDENCY_REFS:
                node["external_deps"].add(str(raw_dep))
            else:
                raise PanelContractError(
                    f"{node['label']} has unknown predecessor {raw_dep!r}"
                )
        if node["id"] in node["barrier_deps"]:
            raise PanelContractError(f"{node['label']} depends on itself")
    return nodes, groups


def _validate_input_contract(run_dir: Path, node: dict, by_id: dict[str, dict]) -> None:
    worker = node["worker"]
    contract = worker.get("input_contract") or {}
    allowed_raw = contract.get("allowed_inputs")
    if allowed_raw is None:
        allowed_raw = worker.get("read_scope")
    forbidden_raw = list(contract.get("forbidden_inputs") or [])
    forbidden_raw.extend(worker.get("forbidden_read_scope") or [])
    allowed = [_normal_pattern(run_dir, item) for item in (allowed_raw or [])]
    forbidden = [_normal_pattern(run_dir, item) for item in forbidden_raw]
    allowed = [item for item in allowed if item]
    forbidden = [item for item in forbidden if item]
    for left in allowed:
        for right in forbidden:
            if _patterns_overlap(left, right):
                raise PanelContractError(
                    f"{node['label']} allowed input {left!r} overlaps forbidden input {right!r}"
                )
    for dep_id in node["data_deps"]:
        dep_rel = by_id[dep_id]["output_rel"]
        if any(_matches(dep_rel, pattern) for pattern in forbidden):
            raise PanelContractError(
                f"{node['label']} predecessor {dep_rel!r} is inside forbidden read scope"
            )
        if allowed and not any(_matches(dep_rel, pattern) for pattern in allowed):
            raise PanelContractError(
                f"{node['label']} predecessor {dep_rel!r} is absent from allowed read scope"
            )
    node["allowed_inputs"] = allowed
    node["forbidden_inputs"] = forbidden
    node["read_scope_declared"] = allowed_raw is not None


def _external_refs(run_dir: Path, node: dict) -> tuple[list[dict], list[str]]:
    evidence = []
    missing = []
    for dependency in sorted(node["external_deps"]):
        refs = EXTERNAL_DEPENDENCY_REFS[dependency]
        for ref in refs:
            path = run_dir / ref
            if not path.is_file():
                missing.append(f"{dependency}:{ref}")
            else:
                evidence.append({"dependency": dependency, "path": ref, "sha256": _sha256(path)})
    return evidence, missing


#: Workers were never told the vendored upstream corpus exists (director question 2026-08-04: "现在的
#: research team 的能力是不是已经可以使用外部那些仓库 skills 的能力了").  Measured answer: the 358 bundles
#: were distilled into 11 overlay summary cards, and NOTHING in any packet named the originals — so a
#: worker could not consult what an upstream skill actually says even though it sits on disk, read-only.
#: This pointer closes that gap WITHOUT changing the execution boundary: read the text, never run it.
_UPSTREAM_ORIGINALS_POINTER = (
    "UPSTREAM ORIGINALS (read-only, on disk — the lenses above are OUR summaries of them): 8 external "
    "research-skill repositories, 358 skill bundles, are vendored at "
    "`research_agent_teams/vendor/upstream-research-skills/`. When a lens above is load-bearing for your "
    "output, or when you want the upstream method in its own words instead of our paraphrase, search it "
    "with `python -m research_agent_teams.workbench capabilities <keyword>` and Read the file it names. "
    "Boundary unchanged: that tree is markdown and licence notices only — READ it, never execute it, "
    "never install it, never treat it as a tool, and never let it re-scope your assigned output."
)


#: Bounded two layers (director lock 2026-08-04, second round). This REVERSES the earlier one-layer rule
#: ("a worker never dispatches a worker") on the director's explicit instruction, because the one-fan-out
#: point was throttling how much a single seat could cover. It does not reverse the reason that rule
#: existed: hop budgets, north-star drift, permission scope and the ledger all need a single accountable
#: WRITER per artifact. So assistants are leaves that write nothing and are signed for by the parent seat.
#: Measured before shipping: a `general-purpose` sub-agent does carry the Agent tool and did launch a
#: child, so this grant is reachable without registering anything in `.claude/agents/`.
ASSISTANT_FANOUT_MAX_DEPTH = 1

_ASSISTANT_FANOUT_GRANT = (
    "\n\nASSISTANT FAN-OUT (bounded two layers)\n"
    "You MAY spawn your own read-only assistants to widen coverage INSIDE your assigned output — "
    "parallel readers over different papers, several independent attempts at the same mechanism, one "
    "assistant per gap / idea / source. Use it when your floor is large and the work splits cleanly; "
    "skip it when it does not. Four bounds, recorded on the receipt rather than taken on trust:\n"
    "  1. DEPTH ONE. Your assistants are leaves — they may not spawn assistants of their own. Say that "
    "explicitly in the prompt you hand them.\n"
    "  2. THEY WRITE NOTHING. No assistant writes an artifact, an inbox file, a ledger entry, or any "
    "file under the run store. They return text to you; you are the single writer for this seat.\n"
    "  3. YOU SIGN. Whatever an assistant produces is folded into YOUR artifact under YOUR name and you "
    "stay accountable for every claim in it, grounding included. An assistant's unverified finding is "
    "YOUR unverified finding — check it or label it UNVERIFIED.\n"
    "  4. YOU COUNT THEM. State how many assistants you used in your one-line return, so the run "
    "receipt records the real fan-out instead of guessing it.\n"
    "Their read scope IS your read scope: scheduler_contract.allowed_inputs and nothing outside it, no "
    "sibling output, no future-wave output. Fan-out buys breadth, never a wider permission."
)


#: Director lock 2026-08-04 (second round): "真正要控制只有后面 report writer 给我的时候和写入更新相关
#: 文件的时候需要控制格式" -- mid-stage shape is deliberately loose, content is what matters. The middle of
#: the pipeline was ALREADY tolerant (schema_normalizer accepts richer JSON than the contract and keeps a
#: hash-bound sidecar of anything it moves), but a worker that does not know that self-censors down to the
#: minimum schema, which is the same "输出太少" failure by another route. One caveat had to be measured
#: rather than assumed: an invented top-level key is STRIPPED from the artifact and survives only in the
#: sidecar, which downstream stages do not read. So the honest instruction is "be long inside the contract
#: fields", not "add whatever keys you like".
_OUTPUT_SHAPE_FENCE = (
    "\n\nSHAPE IS LOOSE, CONTENT IS THE POINT\n"
    "Mid-pipeline formatting is not graded. Do not trim, summarise, merge or drop scientific content to "
    "look tidy, hit a shape, or keep an output short -- length is free and depth is wanted. Canonical "
    "enum spelling, schema defaults and representation differences are normalized for you.\n"
    "One mechanical caveat, measured rather than assumed: put your volume INSIDE the contract's own "
    "fields -- its arrays have no upper bound and its text fields have no length limit. A top-level key "
    "you invent is moved into a normalization sidecar that the NEXT STAGE DOES NOT READ, so content "
    "parked there is content thrown away. Need to say more? Say it in the notes / rationale / summary "
    "field that already exists, or add another array entry.\n"
    "Format is enforced at exactly two places, and neither is here: the report handed to the director, "
    "and the moment something is written into a durable file or the knowledge base. Grounding is NOT "
    "part of this relaxation -- real sources, resolvable [[slug]] refs and no fabrication stay hard."
)

#: Measured 2026-08-04: the harness `WebSearch` tool returned HTTP 400 for a whole session
#: ("output_config.effort 'max' is not supported when thinking is disabled") and the retrieval seats
#: fell back to vault-only WITHOUT SAYING SO — the run looked grounded and was not. The machine's own
#: deterministic clients (arXiv / OpenAlex / Crossref / Semantic Scholar via tools/paper_search.py) were
#: never affected, so the failure was survivable; being silent about it was not.
_RETRIEVAL_HONESTY_FENCE = (
    "\n\nRETRIEVAL DEGRADATION IS REPORTED, NEVER SILENT\n"
    "If a retrieval channel you were counting on fails, errors, times out, or returns nothing — a web "
    "search tool erroring, an API refusing, the frozen bundle being absent or empty, the vault being "
    "unreachable — you must NAME the channel, NAME the failure, and state what coverage you believe was "
    "lost, inside your artifact and in your one-line return. Then continue on the channels that do work: "
    "the frozen retrieval bundle and the deterministic scholarly clients are primary, harness web tools "
    "are a supplement. A narrower search is an acceptable outcome; a narrower search PRESENTED AS A FULL "
    "ONE is not. When a claim could not be checked against live literature, mark it UNVERIFIED rather "
    "than asserting either that it holds or that nobody has done it."
)


#: The fourth standing fence (2026-08-07). The bounded repair loop hands a worker a repair instruction
#: and re-dispatches it; nothing in that loop ever told the worker it was allowed to DISAGREE. A seat
#: that treats every repair instruction as authoritative concedes findings under pressure rather than
#: evidence, and two rounds of that produce a clean-looking artifact with its real objections deleted.
#: This is a scoring rubric, not a licence to stonewall: a 5/5 rebuttal still withdraws the finding.
_REBUTTAL_DISCIPLINE_FENCE = (
    "\n\nREBUTTAL DISCIPLINE (you may push back on a gate)\n"
    "If a repair instruction or an upstream rebuttal asks you to withdraw a finding, score the rebuttal "
    "1-5 before you comply, and record the score with a one-line reason:\n"
    "  5 — it addresses the core of your finding with new evidence or airtight logic → withdraw the "
    "finding.\n"
    "  4 — it substantially weakens the finding, small gaps remain → withdraw, naming the residual "
    "gap.\n"
    "  3 — partially relevant, but it deflects from the core point → HOLD. Restate the finding and say "
    "precisely what was not addressed.\n"
    "  2 — tangential; it answers a related but different point → HOLD and re-engage on the original "
    "issue.\n"
    "  1 — assertion, appeal to authority, or restatement → HOLD and strengthen the finding.\n"
    "Pressure is not evidence. Never withdraw a finding merely because it was pushed back on, and never "
    "withdraw two findings in a row without a 5/5 rebuttal for the second. If you have withdrawn more "
    "than half your findings in one pass, stop and say so explicitly rather than continuing to concede. "
    "After three rounds on the same point, ask yourself once whether there is a premise under this whole "
    "exchange that neither side has questioned — if there is, raise it as a NEW finding."
)


def assistant_fanout_contract(node: dict) -> dict:
    """The machine-readable half of the fan-out grant, pinned into scheduler_contract."""
    return {
        "granted": True,
        "max_depth": ASSISTANT_FANOUT_MAX_DEPTH,
        "assistants_may_spawn": False,
        "assistants_may_write": False,
        "single_writer": node["label"],
        "attribution": "parent_seat_folds_in_and_signs",
        "read_scope": "inherits_parent_allowed_inputs",
        "count_must_be_reported": True,
    }


def capability_overlay_block(run_dir: Path, stage: str) -> tuple[str, Optional[dict]]:
    """Render the stage-relevant, internally curated quality guidance.

    The task-frame plan is advisory and metadata-only.  It never adds workers, tools, reads,
    network access, or output permissions; it only helps an already-authorized worker apply the
    right research-quality lenses without requiring the director to remember separate skills.
    Legacy task frames intentionally return no block.
    """
    payload = _task_payload(run_dir)
    plan = payload.get("capability_overlay_plan")
    if not isinstance(plan, dict):
        return "", None
    selected = [
        item for item in (plan.get("overlays") or [])
        if isinstance(item, dict) and stage in (item.get("target_stages") or [])
    ]
    lines = [
        "\n\nRESEARCH CAPABILITY OVERLAYS (advisory quality lenses; not extra tasks or tools)",
        "Apply only what is scientifically relevant to your assigned output. Do not copy or run "
        "third-party skills, do not expand scope, and do not change the scheduler input/output contract.",
        _UPSTREAM_ORIGINALS_POINTER,
    ]
    for item in selected:
        lines.append(f"- {item['title']}: {item['guidance']}")
        non_goals = ", ".join(item.get("non_goals") or [])
        if non_goals:
            lines.append(f"  non_goals: {non_goals}")
    contract = {
        "contract_version": plan.get("contract_version"),
        "stage": stage,
        "overlay_ids": [item["overlay_id"] for item in selected],
        "advisory_only": True,
        "external_skill_execution": False,
        "network_access": False,
    }
    return "\n".join(lines) + "\n", contract


def _worker_for_dispatch(
    run_dir: Path,
    stage: str,
    node: dict,
    by_id: dict[str, dict],
    *,
    cycle: int,
    feedback: Optional[str],
    authorized: bool,
    repair_plan: Optional[dict] = None,
) -> dict:
    worker = deepcopy(node["worker"])
    predecessors = []
    for dep_id in sorted(node["barrier_deps"]):
        dep = by_id[dep_id]
        path = resolve_effective_output(run_dir, stage, dep["output_path"])
        predecessors.append({
            "worker_id": dep_id,
            "agent": dep["label"],
            "path": _rel(run_dir, path),
            "sha256": _sha256(path),
            "readable": dep_id in node["data_deps"],
        })
    external, _missing = _external_refs(run_dir, node)
    if repair_plan is not None:
        supplement = physical_output(run_dir, repair_plan, node["id"])
        if supplement is not None:
            worker["output"] = str(supplement)
    worker["scheduler_contract"] = {
        "contract_version": CONTRACT_VERSION,
        "stage": stage,
        "worker_id": node["id"],
        "canonical_label": node["label"],
        "repair_cycle": cycle,
        "logical_output": node["output_rel"],
        "physical_output": _rel(run_dir, Path(worker["output"])),
        "dispatch_authorized": authorized,
        "predecessor_outputs": predecessors,
        "external_predecessors": external,
        "allowed_inputs": node["allowed_inputs"],
        "forbidden_inputs": node["forbidden_inputs"],
        "read_scope_declared": node["read_scope_declared"],
        "os_read_sandbox_enforced": False,
        "assistant_fanout": assistant_fanout_contract(node),
        "scope_note": (
            "The scheduler verifies declared paths, ordering, hashes, and scope conflicts. "
            "OS-level read isolation must be supplied by the worker runner."
        ),
    }
    fence = (
        "\n\nSCHEDULER INPUT CONTRACT\n"
        "Use only inputs declared in scheduler_contract. Do not inspect sibling or future-wave "
        "outputs. The receipt records predecessor hashes and your declared read boundary.\n"
    )
    if feedback:
        fence += "\n" + feedback + "\n"
    overlay_block, overlay_contract = capability_overlay_block(run_dir, stage)
    if overlay_contract is not None:
        worker["capability_overlay_contract"] = overlay_contract
    worker["prompt"] = (
        str(worker.get("prompt") or "")
        + overlay_block
        + _OUTPUT_SHAPE_FENCE
        + _ASSISTANT_FANOUT_GRANT
        + _RETRIEVAL_HONESTY_FENCE
        + _REBUTTAL_DISCIPLINE_FENCE
        + fence
    )
    return worker


def _dispatch_wrapper(spec: dict, workers: list[dict]) -> Optional[dict]:
    if not workers:
        return None
    if not isinstance(spec.get("workers"), list):
        return workers[0]
    return {
        "label": str(spec.get("label") or "scheduled-panel-wave"),
        "workers": workers,
        "worker_order": [worker["label"] for worker in workers],
        "parallel_groups": [[worker["label"] for worker in workers]],
        "panel_note": (
            "Scheduler-authorized current wave only. Future-wave prompts are withheld until "
            "all predecessor outputs exist and their declared input contracts validate."
        ),
        "scheduler_contract_version": CONTRACT_VERSION,
    }


def schedule_next_wave(
    run_dir: str | Path,
    stage: str,
    spec: Optional[dict],
    *,
    ts: str,
    authorize: bool = True,
) -> dict:
    """Return only the next legal worker wave and persist its authorization.

    Repeated calls are idempotent: an authorized wave with missing outputs is
    returned again without consuming more hops.  A bounded-repair attempt opens
    a new cycle and requires freshly rewritten outputs.
    """
    root = Path(run_dir).resolve()
    payload = _task_payload(root)
    mode = str(payload.get("mode") or "")
    if not spec:
        required = REQUIRED_STAGE_WORKERS.get((mode, stage), set())
        repair = _repair_cycle(root, stage)
        cycle = repair["cycle"]
        receipt_path = _receipt_path(root, stage)
        receipt = _load_receipt(receipt_path, stage)
        authorized = {
            row.get("agent") for row in receipt["authorizations"]
            if row.get("cycle") == cycle
        }
        # De-governance (director, 2026-08-07): a produced output with no in-run authorization
        # receipt no longer HALTS the stage. `unreceipted_agents` stays as a read-only diagnostic
        # the report can show ("these outputs carry no authorization receipt from this run"); it
        # never decides `status`. `_authorization_report` / `_authorization_counts` are untouched —
        # they are pure counters feeding the hop budget and the director packet.
        return {
            "status": "complete",
            "stage": stage,
            "workers": [],
            "dispatch": None,
            "unreceipted_agents": sorted(required - authorized),
            **_authorization_report(root),
            "scheduler_receipt": None,
        }

    connectivity = validate_worker_spec_connectivity(mode, stage, spec)
    pinned_agents = set(payload.get("agent_subset") or [])
    for label in worker_labels(spec):
        if label not in pinned_agents:
            connectivity.append(
                f"{mode}/{stage}: actual worker {label!r} is absent from pinned task_frame agent_subset"
            )
    if connectivity:
        raise PanelContractError("; ".join(connectivity))

    nodes, groups = _normalize_nodes(root, spec)
    by_id = {node["id"]: node for node in nodes}
    for node in nodes:
        _validate_input_contract(root, node, by_id)

    repair = _repair_cycle(root, stage)
    cycle = repair["cycle"]
    targets = set(repair["targets"])
    if cycle and not targets:
        targets = _infer_plain_repair_targets(nodes, repair.get("attempt"))
    if cycle and not targets:
        # Legacy/plain GateBlock: supplement one responsible terminal worker,
        # never replay the whole panel. This fallback remains only for old
        # failures that name neither a bundle nor an owner.
        terminal = max(nodes, key=lambda node: (node["group"], node["index"]))
        targets = {terminal["label"]}
    unknown_targets = targets - {node["label"] for node in nodes}
    if unknown_targets:
        raise PanelContractError(f"repair targets unknown panel agents: {sorted(unknown_targets)}")
    repair_plan = (
        prepare_plan(root, stage, cycle, nodes, targets, repair["attempt"])
        if cycle else None
    )
    receipt_path = _receipt_path(root, stage)
    receipt = _load_receipt(receipt_path, stage)
    current_auth = {
        row["worker_id"]: row
        for row in receipt["authorizations"]
        if row.get("cycle") == cycle
    }
    any_auth = {row["worker_id"]: row for row in receipt["authorizations"]}

    def fresh(node: dict) -> bool:
        if cycle and node["label"] in targets:
            path = physical_output(root, repair_plan, node["id"])
            if path and path.is_file():
                _validate_current_worker_output_contract(mode, stage, node, path)
                finalize_output(root, stage, cycle, node["id"], ts)
                return True
            return False
        try:
            path = resolve_effective_output(root, stage, node["output_path"])
        except ValueError as exc:
            raise PanelContractError(str(exc)) from exc
        if not path.is_file():
            return False
        _validate_current_worker_output_contract(mode, stage, node, path)
        return True

    def authorized(node: dict) -> bool:
        return node["id"] in (current_auth if cycle and node["label"] in targets else any_auth)

    pending_authorized = [
        node for node in nodes if node["id"] in current_auth and not fresh(node)
    ]
    if pending_authorized:
        wave_no = min(int(current_auth[node["id"]]["wave"]) for node in pending_authorized)
        pending_authorized = [
            node for node in pending_authorized
            if int(current_auth[node["id"]]["wave"]) == wave_no
        ]
        for node in pending_authorized:
            missing = [by_id[dep]["output_rel"] for dep in node["barrier_deps"] if not fresh(by_id[dep])]
            _external, missing_external = _external_refs(root, node)
            if missing or missing_external:
                raise PanelContractError(
                    f"authorized worker {node['label']} lost predecessor evidence: "
                    f"{missing + missing_external}"
                )
        workers = [
            _worker_for_dispatch(
                root, stage, node, by_id, cycle=cycle,
                feedback=_feedback_for_agent(repair, node["label"]), authorized=True,
                repair_plan=repair_plan,
            )
            for node in pending_authorized
        ]
        return {
            "status": "waiting_for_outputs",
            "stage": stage,
            "cycle": cycle,
            "wave": wave_no,
            "workers": workers,
            "dispatch": _dispatch_wrapper(spec, workers),
            **_authorization_report(root),
            "scheduler_receipt": str(receipt_path),
        }

    remaining = [node for node in nodes if not fresh(node)]
    if not remaining:
        # De-governance (director, 2026-08-07): see the no-spec branch above. Every node has a fresh
        # output, so the stage IS complete; an output whose authorization receipt is missing is now
        # reported, not halted on.
        return {
            "status": "complete",
            "stage": stage,
            "cycle": cycle,
            "workers": [],
            "dispatch": None,
            "unreceipted_agents": [node["label"] for node in nodes if not authorized(node)],
            **_authorization_report(root),
            "scheduler_receipt": str(receipt_path) if receipt_path.exists() else None,
        }

    ready = []
    blocked: dict[str, list[str]] = {}
    for node in remaining:
        missing = [
            by_id[dep]["output_rel"]
            for dep in node["barrier_deps"]
            if not fresh(by_id[dep])
        ]
        _external, missing_external = _external_refs(root, node)
        missing.extend(missing_external)
        if missing:
            blocked[node["label"]] = missing
        else:
            ready.append(node)
    if not ready:
        return {
            "status": "blocked_missing_predecessor",
            "stage": stage,
            "cycle": cycle,
            "workers": [],
            "dispatch": None,
            "missing_predecessors": blocked,
            **_authorization_report(root),
            "scheduler_receipt": str(receipt_path) if receipt_path.exists() else None,
        }

    group_index = min(node["group"] for node in ready)
    wave_nodes = [node for node in ready if node["group"] == group_index]
    if authorize:
        counts = _authorization_counts(root)
        budget = dict(payload.get("budget") or {})
        is_supplement = bool(
            cycle and repair_plan is not None
            and any(physical_output(root, repair_plan, node["id"]) is not None for node in wave_nodes)
        )
        if is_supplement:
            # Per-mode, never a shared pool — see `_supplement_limit`.
            budget["max_supplement_agent_hops"] = _supplement_limit(budget, nodes)
            budget = _apply_director_supplement_extension(root, budget)
            usage_key = "supplement_agent_hops"
            used = counts["supplement"]
        else:
            usage_key = "agent_hops"
            used = counts["initial"]
        # Authorize atomically.  The budget helper treats used == limit as the
        # point where the *next* hop is refused, so check each proposed seat.
        for offset in range(len(wave_nodes)):
            assert_within(budget, {usage_key: used + offset})
        wave_no = len(receipt["waves"]) + 1
        receipt["waves"].append({
            "wave": wave_no,
            "cycle": cycle,
            "authorized_at": ts,
            "worker_ids": [node["id"] for node in wave_nodes],
            "agents": [node["label"] for node in wave_nodes],
        })
        for node in wave_nodes:
            scheduled_output = (
                physical_output(root, repair_plan, node["id"])
                if repair_plan is not None else None
            ) or node["output_path"]
            receipt["authorizations"].append({
                "worker_id": node["id"],
                "agent": node["label"],
                "source_label": node["source_label"],
                "output": _rel(root, scheduled_output),
                "logical_output": node["output_rel"],
                "cycle": cycle,
                "wave": wave_no,
                "authorized_at": ts,
                "authorization_kind": "supplement" if is_supplement else "initial",
            })
        _save_receipt(root, receipt_path, receipt)
    else:
        wave_no = len(receipt["waves"]) + 1

    workers = [
        _worker_for_dispatch(
            root, stage, node, by_id, cycle=cycle,
            feedback=_feedback_for_agent(repair, node["label"]), authorized=authorize,
            repair_plan=repair_plan,
        )
        for node in wave_nodes
    ]
    return {
        "status": "wave_ready",
        "stage": stage,
        "cycle": cycle,
        "wave": wave_no,
        "workers": workers,
        "dispatch": _dispatch_wrapper(spec, workers),
        **_authorization_report(root),
        "scheduler_receipt": str(receipt_path) if authorize else None,
    }
