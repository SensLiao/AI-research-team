"""Second-round director locks (2026-08-04): wider method channel, deeper fan-out, looser mid-stage shape.

The asks, in the director's words: *"为什么不介入外部能力作为额外补充… 把产物内容输出扩大，下限往上抬，
subagents 也可以去 spawn subagents… 真正要控制只有后面 report writer 给我的时候和写入更新相关文件的时候
需要控制格式."*

What was measured before changing anything (each is why the corresponding test exists):

* the external-method channel was capped at FIVE lenses per run by four agreeing locks -- the catalog
  policy `selection_max`, an equality check on that literal inside `load_overlay_catalog`, `maxItems: 5`
  on `task_frame /capability_overlay_plan/overlays`, and a literal `<= 5` in two tests. Growing the
  catalog therefore could not reach a worker;
* a `general-purpose` sub-agent DOES carry the `Agent` tool and DID launch a child, so bounded nesting
  needed no `.claude/agents/` registration -- the one-layer rule was instruction-layer only;
* an invented top-level key is STRIPPED from the artifact into a normalization sidecar the next stage
  does not read, so "write more" had to become "write more inside the contract fields".
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.operate import panel_scheduler
from research_agent_teams.tools import research_capability_router as router

ROOT = Path(__file__).resolve().parents[2] / "research_agent_teams"
CATALOG = json.loads(router.DEFAULT_OVERLAY_CATALOG.read_text(encoding="utf-8"))

#: The four families the director named. Each must be reachable as real guidance, not a summary line.
FAMILY_CARDS = {
    "科研创新": ("iterative_idea_refinement", "multi_round_novelty_search", "research_question_card"),
    "数据挖掘": ("atomic_concept_decomposition", "number_provenance_chain",
                 "unit_of_analysis_before_any_winner"),
    "实验设计": ("progressive_experiment_stages", "statistical_reporting_contract"),
    "汇报": ("claim_strength_wording_ladder", "figure_must_change_a_decision"),
}


# --------------------------------------------------------------- the cap that made the corpus unreachable

def test_external_method_channel_is_not_recapped():
    """The window must stay a window. A literal 5 anywhere here re-closes the channel."""
    policy = CATALOG["policy"]
    assert policy["selection_max"] > 5, "the five-lens cap is back in the catalog policy"
    assert policy["selection_min"] >= 2

    schema = json.loads((ROOT / "schemas" / "task_frame.schema.json").read_text(encoding="utf-8"))
    overlays = schema["properties"]["capability_overlay_plan"]["properties"]["overlays"]
    assert overlays["maxItems"] >= policy["selection_max"], (
        "the schema would reject a legal selection -- schema and policy disagree")

    # and the loader must validate the window as a range, not pin it to a constant
    assert "selection_min" not in router._REQUIRED_SAFETY_POLICY
    assert "selection_max" not in router._REQUIRED_SAFETY_POLICY


def test_the_safety_half_of_the_policy_is_still_pinned_by_equality():
    """Widening volume must not have loosened the read-never-execute boundary."""
    assert router._REQUIRED_SAFETY_POLICY == {
        "network_default": "DENY",
        "external_execution": False,
        "copy_third_party_code": False,
        "copy_third_party_long_text": False,
    }
    for key, expected in router._REQUIRED_SAFETY_POLICY.items():
        assert CATALOG["policy"][key] == expected


def test_the_window_validator_would_reject_a_nonsense_window():
    """A guard that cannot fail is not a guard."""
    with pytest.raises(router.ResearchCapabilityRouterError):
        router._check_selection_window({"selection_min": 0, "selection_max": 4})
    with pytest.raises(router.ResearchCapabilityRouterError):
        router._check_selection_window({"selection_min": 6, "selection_max": 4})
    with pytest.raises(router.ResearchCapabilityRouterError):
        router._check_selection_window({"selection_min": 2, "selection_max": 10_000})
    router._check_selection_window(dict(CATALOG["policy"]))                     # the live one


def test_the_window_ceiling_agrees_in_all_three_places():
    """The window is one number written in three files; a disagreement is silently lost breadth.

    Widened 24 -> 28 on 2026-08-07 for the four innovation/rigor cards. The ceiling in the router,
    the catalog's `selection_max`, and the schema's `maxItems` must stay consistent: a router ceiling
    below the catalog rejects the catalog outright, and a schema `maxItems` below the catalog rejects
    a legal selection at validate time — which reads as "the overlay never applied", not as an error.
    """
    schema = json.loads((ROOT / "schemas" / "task_frame.schema.json").read_text(encoding="utf-8"))
    schema_max = schema["properties"]["capability_overlay_plan"]["properties"]["overlays"]["maxItems"]
    assert CATALOG["policy"]["selection_max"] <= router._SELECTION_WINDOW_CEILING
    assert CATALOG["policy"]["selection_max"] <= schema_max
    assert router._SELECTION_WINDOW_CEILING == schema_max == 28, (
        "router ceiling / schema maxItems / catalog selection_max drifted apart — "
        f"router={router._SELECTION_WINDOW_CEILING}, schema={schema_max}, "
        f"catalog={CATALOG['policy']['selection_max']}")


# ------------------------------------------------------------------- the four absorbed method families

@pytest.mark.parametrize("family", sorted(FAMILY_CARDS))
def test_each_named_capability_family_has_real_cards(family):
    by_id = {o["overlay_id"]: o for o in CATALOG["overlays"]}
    for overlay_id in FAMILY_CARDS[family]:
        card = by_id.get(overlay_id)
        assert card, f"{family}: overlay {overlay_id} is missing"
        # A card is guidance, not a label: it must say something a worker can act on.
        assert len(card["summary"]) >= 200, f"{overlay_id} summary is too thin to be guidance"
        assert card["stages"] and card["modes"] and card["provenance_refs"]
        assert card["non_goals"], f"{overlay_id} states no non_goals"


def test_every_declared_provenance_receipt_matches_the_real_vendored_bytes():
    """Provenance has to be checkable, or a sha256 is just decoration.

    Nothing verified these hashes against the tree before: `load_overlay_catalog` only checked the
    64-hex SHAPE, and the fetch-time receipts were never re-derived. This recomputes them.
    """
    vendor_root = ROOT / "vendor" / "upstream-research-skills"
    if not vendor_root.is_dir():                      # public/sanitized checkout: nothing to verify
        pytest.skip("vendored upstream text is not present in this checkout")
    checked, unvendored = 0, []
    for source in CATALOG["sources"]:
        snapshot = source.get("snapshot_dir")
        if not snapshot or not (vendor_root / snapshot).is_dir():
            continue                                  # excluded-on-safety source, e.g. the CDP one
        for artifact in source["source_artifacts"]:
            path = vendor_root / snapshot / artifact["path"]
            if not path.is_file():
                # A declared receipt whose file was never copied locally. That is CORRECT for anything
                # the vendoring allowlist refuses: the lock audits upstream bytes (including scripts),
                # while vendoring copies only markdown inside skill bundles plus top-level licence
                # files. Measured: the 8 absent receipts are .py / .js / .json scripts and one repo-root
                # README -- i.e. the vendor-not-install boundary holding, not a provenance hole.
                # Recorded and asserted below, never silently skipped.
                unvendored.append((source["source_id"], snapshot, artifact["path"]))
                continue
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual == artifact["sha256"], (
                f"{source['source_id']}/{artifact['path']}: declared receipt does not match the "
                f"vendored bytes (declared {artifact['sha256'][:12]}…, actual {actual[:12]}…)")
            checked += 1
    assert checked >= 42, f"only {checked} receipts were locally verifiable"

    # The vendoring policy has TWO halves and a receipt is legitimately absent when EITHER refuses it:
    # the suffix/name allowlist (markdown + licence files) and the scope rule (skill bundles only, i.e.
    # a directory holding SKILL.md, plus top-level licence/notice files). A repo-root README.md passes
    # the first and fails the second, which is why `is_allowed` alone is not the policy.
    from research_agent_teams.tools import vendor_upstream_skills as vendor

    def _inside_a_bundle(snapshot: str, rel: str) -> bool:
        parent = (vendor_root / snapshot / rel).parent
        stop = vendor_root / snapshot
        while parent != stop and stop in parent.parents:
            if (parent / "SKILL.md").is_file():
                return True
            parent = parent.parent
        return False

    for source_id, snapshot, rel in unvendored:
        refused_by_suffix = not vendor.is_allowed(Path(rel))
        refused_by_scope = not _inside_a_bundle(snapshot, rel)
        assert refused_by_suffix or refused_by_scope, (
            f"{source_id}/{rel} is bundle markdown the policy WOULD copy, yet it is missing -- that is "
            "a real provenance hole, not the executable-content boundary")


def test_a_widened_catalog_still_loads_and_routes():
    catalog = router.load_overlay_catalog()
    assert len(catalog["overlays"]) >= 21
    route = router.route_research_capabilities("设计这个实验并做统计功效分析")
    ids = {o["overlay_id"] for o in route["capability_overlays"]}
    assert len(ids) > 5, "the widened channel still delivers five or fewer lenses"
    assert {"statistical_reporting_contract", "progressive_experiment_stages"} & ids
    assert route["safety"]["external_execution"] is False
    assert route["safety"]["network_default"] == "DENY"


# --------------------------------------------------------------------------- bounded assistant fan-out

def test_the_fanout_grant_is_bounded_on_all_four_axes():
    contract = panel_scheduler.assistant_fanout_contract({"label": "gap-hunter-1"})
    assert contract["granted"] is True
    assert contract["max_depth"] == 1
    assert contract["assistants_may_spawn"] is False
    assert contract["assistants_may_write"] is False
    assert contract["single_writer"] == "gap-hunter-1"
    assert contract["count_must_be_reported"] is True


def test_the_fanout_prompt_states_every_bound_it_claims():
    grant = panel_scheduler._ASSISTANT_FANOUT_GRANT
    lowered = grant.lower()
    assert "depth one" in lowered, "a worker told it may fan out must be told the depth limit"
    assert "write nothing" in lowered or "they write nothing" in lowered
    assert "you sign" in lowered, "attribution must be stated, not implied"
    assert "you count them" in lowered, "the receipt needs the real assistant count"
    assert "your read scope" in lowered, "fan-out must not read as a permission upgrade"


def test_mid_stage_shape_is_loosened_without_loosening_grounding():
    fence = panel_scheduler._OUTPUT_SHAPE_FENCE
    lowered = fence.lower()
    assert "not graded" in lowered or "shape is loose" in lowered
    # The measured caveat has to travel with the invitation, or volume lands in a dead sidecar.
    assert "sidecar" in lowered and "next stage does not read" in lowered
    # The two chokepoints the director named.
    assert "report handed to the director" in lowered
    assert "written into a durable file" in lowered
    # The safety floor is explicitly excluded from the relaxation.
    assert "grounding is not part of this relaxation" in lowered


def test_retrieval_degradation_must_be_reported():
    fence = panel_scheduler._RETRIEVAL_HONESTY_FENCE
    lowered = fence.lower()
    assert "never silent" in lowered
    assert "name the channel" in lowered
    assert "unverified" in lowered, "an unverifiable claim must have somewhere honest to go"


@pytest.mark.parametrize("attr", ["_OUTPUT_SHAPE_FENCE", "_ASSISTANT_FANOUT_GRANT",
                                  "_RETRIEVAL_HONESTY_FENCE"])
def test_each_new_fence_actually_reaches_a_dispatched_packet(tmp_path, attr):
    """Wired, not merely defined -- the failure mode this whole round was about."""
    run_dir = tmp_path / "run"
    (run_dir).mkdir()
    (run_dir / "task_frame.artifact.json").write_text(
        json.dumps({"payload": {"mode": "new_direction"}}), encoding="utf-8")
    node = {"id": "w1", "label": "lit-scout",
            "worker": {"prompt": "BASE PROMPT", "output": str(run_dir / "x.json")},
            "output_rel": "x.json", "barrier_deps": set(), "data_deps": set(),
            "external_deps": set(), "allowed_inputs": [], "forbidden_inputs": [],
            "read_scope_declared": False}
    worker = panel_scheduler._worker_for_dispatch(
        run_dir, "DISCOVER", node, {"w1": node}, cycle=0, feedback=None, authorized=True)
    marker = getattr(panel_scheduler, attr).strip().splitlines()[0]
    assert marker in worker["prompt"], f"{attr} never reaches the worker"
    assert worker["scheduler_contract"]["assistant_fanout"]["max_depth"] == 1
