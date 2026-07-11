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
import os
from copy import deepcopy
from pathlib import Path
from typing import Iterable, Optional

import yaml

from ..tools.budget_tracker import BudgetExceeded, assert_within
from .bounded_repair import load_state
from .output_versions import (
    finalize_output,
    physical_output,
    prepare_plan,
    resolve_effective_output,
)


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


def _save_receipt(path: Path, receipt: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


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
    worker["prompt"] = str(worker.get("prompt") or "") + fence
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
        missing = sorted(required - authorized)
        if missing:
            return {
                "status": "unverified_unreceipted_outputs",
                "stage": stage,
                "cycle": cycle,
                "workers": [],
                "dispatch": None,
                "unreceipted_agents": missing,
                **_authorization_report(root),
                "scheduler_receipt": str(receipt_path) if receipt_path.exists() else None,
            }
        return {
            "status": "complete",
            "stage": stage,
            "workers": [],
            "dispatch": None,
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
                finalize_output(root, stage, cycle, node["id"], ts)
                return True
            return False
        try:
            return resolve_effective_output(root, stage, node["output_path"]).is_file()
        except ValueError as exc:
            raise PanelContractError(str(exc)) from exc

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
        unreceipted = [node["label"] for node in nodes if not authorized(node)]
        if unreceipted:
            return {
                "status": "unverified_unreceipted_outputs",
                "stage": stage,
                "cycle": cycle,
                "workers": [],
                "dispatch": None,
                "unreceipted_agents": unreceipted,
                **_authorization_report(root),
                "scheduler_receipt": str(receipt_path) if receipt_path.exists() else None,
            }
        return {
            "status": "complete",
            "stage": stage,
            "cycle": cycle,
            "workers": [],
            "dispatch": None,
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
            budget.setdefault("max_supplement_agent_hops", 12)
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
        _save_receipt(receipt_path, receipt)
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
