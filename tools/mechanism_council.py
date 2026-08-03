"""Optional cross-disciplinary mechanism council with a strict compilation boundary.

The council is an advisory adapter around the existing research orchestrator.  It does not add a
second operational entry point, execute an external skill, contact a server, or create results.  Its
job is to decide when a multi-perspective panel is useful and to reject a synthesis that does not
close the chain ``hypothesis -> implementable mechanism -> falsifiable experiment``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from research_agent_teams.tools.path_boundaries import assert_not_vault_path
from research_agent_teams.tools.validate_artifact import validate_against


_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONTRACT = _ROOT / "orchestrator" / "mechanism_council.json"
CONTRIBUTION_SCHEMA = "mechanism_council_contribution.schema.json"
BUNDLE_SCHEMA = "mechanism_council_bundle.schema.json"


class MechanismCouncilError(ValueError):
    """Raised when a council plan or bundle would weaken the contract."""


def _json_sha256(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def load_contract(path: str | Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    candidate = Path(path)
    try:
        value = json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MechanismCouncilError(f"cannot read UTF-8 mechanism council contract: {candidate}") from exc
    if value.get("contract_version") != "mechanism-council/v1":
        raise MechanismCouncilError("unsupported mechanism council contract_version")
    rows = value.get("roles")
    if not isinstance(rows, list) or not rows:
        raise MechanismCouncilError("mechanism council requires roles")
    role_ids = [str(row.get("role") or "") for row in rows if isinstance(row, dict)]
    if len(role_ids) != len(rows) or len(role_ids) != len(set(role_ids)) or any(not role for role in role_ids):
        raise MechanismCouncilError("mechanism council roles must be unique and non-empty")
    known = set(role_ids)
    for row in rows:
        spec = _ROOT / str(row.get("agent_spec") or "")
        if not spec.is_file():
            raise MechanismCouncilError(f"missing agent spec for {row.get('role')}: {spec}")
        dependencies = row.get("depends_on")
        if not isinstance(dependencies, list) or any(dep not in known for dep in dependencies):
            raise MechanismCouncilError(f"invalid role dependency for {row.get('role')}")
        if row.get("role") in dependencies:
            raise MechanismCouncilError(f"role cannot depend on itself: {row.get('role')}")
    return value


def _dependency_closure(selected: Iterable[str], by_role: Mapping[str, Mapping[str, Any]]) -> set[str]:
    closure = set(selected)
    pending = list(closure)
    while pending:
        role = pending.pop()
        for dependency in by_role[role].get("depends_on") or []:
            if dependency not in closure:
                closure.add(dependency)
                pending.append(dependency)
    return closure


def _waves(selected: set[str], rows: list[Mapping[str, Any]]) -> list[list[str]]:
    remaining = {str(row["role"]): set(row.get("depends_on") or []) & selected for row in rows if row["role"] in selected}
    emitted: set[str] = set()
    waves: list[list[str]] = []
    while remaining:
        wave = [str(row["role"]) for row in rows if row["role"] in remaining and remaining[row["role"]] <= emitted]
        if not wave:
            raise MechanismCouncilError("mechanism council role graph contains a cycle")
        waves.append(wave)
        emitted.update(wave)
        for role in wave:
            remaining.pop(role)
    return waves


def plan_council(
    request_text: str,
    *,
    manual_roles: Optional[Iterable[str]] = None,
    force: Optional[bool] = None,
    contract: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Return a deterministic advisory team plan.

    ``manual_roles`` is the manual override. Dependencies are added explicitly and reported. ``force``
    can opt the full council in or out. Without either override, at least two independent signal groups
    must match, which prevents routine research requests from paying the council cost.
    """
    request = str(request_text or "").strip()
    if not request:
        raise MechanismCouncilError("request_text must be non-empty")
    cfg = dict(contract) if contract is not None else load_contract()
    rows = list(cfg["roles"])
    by_role = {str(row["role"]): row for row in rows}
    text = request.casefold()
    signal_hits: dict[str, list[str]] = {}
    for group, phrases in cfg["activation"]["signal_groups"].items():
        hits = [str(phrase) for phrase in phrases if str(phrase).casefold() in text]
        if hits:
            signal_hits[str(group)] = hits

    requested = None if manual_roles is None else [str(role).strip() for role in manual_roles]
    if requested is not None:
        if not requested or any(role not in by_role for role in requested):
            raise MechanismCouncilError(
                f"manual_roles must name one or more known roles: {sorted(by_role)}"
            )
        selected = _dependency_closure(requested, by_role)
        enabled = True
        source = "manual_override"
        auto_added = [role for role in by_role if role in selected and role not in requested]
    elif force is not None:
        enabled = bool(force)
        selected = set(by_role) if enabled else set()
        source = "manual_force_on" if enabled else "manual_force_off"
        auto_added = []
    else:
        minimum = int(cfg["activation"]["automatic_min_signal_groups"])
        enabled = len(signal_hits) >= minimum
        selected = set(by_role) if enabled else set()
        source = "automatic_signal_groups"
        auto_added = []

    return {
        "contract_version": cfg["contract_version"],
        "enabled": enabled,
        "selection_source": source,
        "signal_hits": signal_hits,
        "selected_roles": [role for role in by_role if role in selected],
        "auto_added_dependencies": auto_added,
        "waves": _waves(selected, rows) if selected else [],
        "truth_boundary": dict(cfg["truth_boundary"]),
    }


def _validate_contributions(
    contributions: Iterable[Mapping[str, Any]],
    *,
    expected_input_sha256: str,
    contract: Mapping[str, Any],
) -> list[dict[str, str]]:
    required = [
        str(row["role"])
        for row in contract["roles"]
        if row["role"] != "hypothesis_compiler"
    ]
    rows = [dict(row) for row in contributions]
    errors: list[str] = []
    for index, row in enumerate(rows):
        errors.extend(f"contribution[{index}] {error}" for error in validate_against(CONTRIBUTION_SCHEMA, row))
    roles = [str(row.get("role") or "") for row in rows]
    if sorted(roles) != sorted(required):
        errors.append(f"contributions must cover exactly {required}; got {roles}")
    if len(roles) != len(set(roles)):
        errors.append("contribution roles must be unique")
    for row in rows:
        if row.get("input_sha256") != expected_input_sha256:
            errors.append(f"{row.get('role')} input_sha256 differs from frozen work order")
        if row.get("status") != "COMPLETE":
            errors.append(f"{row.get('role')} is not COMPLETE")
    if errors:
        raise MechanismCouncilError("; ".join(errors))
    by_role = {str(row["role"]): row for row in rows}
    return [{"role": role, "sha256": _json_sha256(by_role[role])} for role in required]


def compile_bundle(
    *,
    work_order: Mapping[str, Any],
    contributions: Iterable[Mapping[str, Any]],
    compiled_chain: Mapping[str, Any],
    conflicts: Iterable[Mapping[str, Any]],
    compiler_agent_id: str,
    contract: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Bind six independent contributions to one design-only compiled chain."""
    cfg = dict(contract) if contract is not None else load_contract()
    order = dict(work_order)
    if set(order) != {"request_id", "north_star", "input_sha256"}:
        raise MechanismCouncilError("work_order requires only request_id, north_star, input_sha256")
    if not str(compiler_agent_id or "").strip():
        raise MechanismCouncilError("compiler_agent_id must be non-empty")
    receipts = _validate_contributions(
        contributions,
        expected_input_sha256=str(order.get("input_sha256") or ""),
        contract=cfg,
    )
    bundle = {
        "contract_version": "mechanism-council-bundle/v1",
        "work_order": order,
        "contribution_receipts": receipts,
        "compiled_chain": dict(compiled_chain),
        "conflicts": [dict(row) for row in conflicts],
        "truth_boundary": {
            "execution_status": "DESIGN_ONLY",
            "result_claims_allowed": False,
            "novelty_claim_allowed": False,
            "compiler_agent_id": str(compiler_agent_id),
        },
    }
    errors = validate_against(BUNDLE_SCHEMA, bundle)
    if errors:
        raise MechanismCouncilError("; ".join(errors))
    return bundle


def render_anonymous_candidate(bundle: Mapping[str, Any]) -> str:
    """Render a schema-valid bundle without producer identities or receipts.

    This representation is suitable for a blind content review.  It omits
    contribution receipts and ``compiler_agent_id`` while preserving every
    scientific statement, conflict, and truth boundary.
    """
    value = dict(bundle)
    errors = validate_against(BUNDLE_SCHEMA, value)
    if errors:
        raise MechanismCouncilError("; ".join(errors))
    chain = value["compiled_chain"]
    hypothesis = chain["hypothesis"]
    mechanism = chain["mechanism"]
    experiment = chain["falsifiable_experiment"]

    lines = [
        "# Anonymous design candidate",
        "",
        "> Status: `DESIGN_ONLY / NON_CITABLE / NO RESULTS`. This candidate may not claim novelty, effectiveness, execution, or publication readiness.",
        "",
        "## Hypothesis",
        "",
        hypothesis["statement"],
        "",
        "### Strongest alternative",
        "",
        hypothesis["alternative"],
        "",
        "### Observable prediction",
        "",
        hypothesis["observable_prediction"],
        "",
        "## Implementable mechanism",
        "",
        "### Inputs",
        "",
    ]
    lines.extend(f"- {item}" for item in mechanism["inputs"])
    lines.extend([
        "",
        "### Representation",
        "",
        mechanism["representation"],
        "",
        "### Transformation",
        "",
        mechanism["transformation"],
        "",
        "### Output",
        "",
        mechanism["output"],
        "",
        "### Distinguishing signal",
        "",
        mechanism["distinguishing_signal"],
        "",
        "### Failure modes",
        "",
    ])
    lines.extend(f"- {item}" for item in mechanism["failure_modes"])
    lines.extend([
        "",
        "## Falsifiable experiment",
        "",
        "### Intervention",
        "",
        experiment["intervention"],
        "",
        "### Comparator",
        "",
        experiment["comparator"],
        "",
        "### Held constant",
        "",
    ])
    lines.extend(f"- {item}" for item in experiment["held_constant"])
    lines.extend([
        "",
        "### Independent analysis unit",
        "",
        experiment["analysis_unit"],
        "",
        "### Primary outcome",
        "",
        experiment["primary_outcome"],
        "",
        "### Leakage checks",
        "",
    ])
    lines.extend(f"- {item}" for item in experiment["leakage_checks"])
    lines.extend([
        "",
        "### Falsifier",
        "",
        experiment["falsifier"],
        "",
        "### Stop condition",
        "",
        experiment["stop_condition"],
        "",
        "## Open and resolved conflicts",
        "",
    ])
    if value["conflicts"]:
        for conflict in value["conflicts"]:
            lines.extend([
                f"### {conflict['conflict_id']} — {conflict['resolution_status']}",
                "",
                conflict["summary"],
                "",
            ])
            if conflict.get("resolution"):
                lines.extend(["Resolution: " + conflict["resolution"], ""])
    else:
        lines.extend(["No typed conflict was recorded.", ""])
    lines.extend([
        "## Truth boundary",
        "",
        "- Execution status: `DESIGN_ONLY`",
        "- Result claims allowed: `false`",
        "- Novelty claims allowed: `false`",
        "- Producer identities and internal receipts are intentionally omitted from this blind-review rendering.",
        "",
    ])
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Plan or validate the optional mechanism council.")
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("request")
    plan.add_argument("--role", action="append", dest="roles")
    plan.add_argument("--force", choices=("on", "off"))
    plan.add_argument("--out")
    args = parser.parse_args(argv)

    forced = None if args.force is None else args.force == "on"
    result = plan_council(args.request, manual_roles=args.roles, force=forced)
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        target = Path(args.out)
        assert_not_vault_path(target)
        target.write_text(rendered, encoding="utf-8", newline="\n")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
