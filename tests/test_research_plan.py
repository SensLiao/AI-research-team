"""Tests for the COMBINATION layer (tools/research_plan.py + plan_catalog.yaml + the operate
`plan-propose` / `begin --upstream-run` wiring) — director lock 2026-06-19.

The contract under test: a request -> an intent -> TIERED mode-combinations (core <= mainline <= full
by cost), the chain is validated (unknown rejected, spec-only flagged, backwards-phase rejected), the
human gates a chain passes through are surfaced, and one link's output threads into the next.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from research_agent_teams.tools import research_plan as rp
from research_agent_teams.tools import runstore
from research_agent_teams.tools.citation_attribution import build_attribution_report


# --------------------------------------------------------------------------- catalog integrity

def test_catalog_loads_and_has_intents():
    cat = rp.load_catalog()
    assert cat.get("version") == 1
    assert cat.get("intents"), "catalog must define intents"


def test_every_default_tier_uses_only_wired_one_button_modes():
    """The honesty guarantee: a DEFAULT tier never silently contains a spec-only mode."""
    wired = rp.wired_modes()
    for intent in rp.all_intents():
        for tier in rp.propose(intent)["tiers"]:
            for m in tier["modes"]:
                assert m in wired, f"{intent}/{tier['id']} uses non-wired mode {m!r}"
            assert tier["validation"]["ok"], f"{intent}/{tier['id']} fails validation: {tier['validation']}"
            assert not tier["validation"]["spec_only"]


def test_every_wired_mode_declares_versioned_handoff_product():
    modes = rp.load_mode_registry()["modes"]
    for mode in rp.wired_modes():
        handoff = modes[mode].get("handoff") or {}
        assert handoff.get("contract_version") == rp.HANDOFF_CONTRACT_VERSION
        assert handoff.get("product_version")
        assert handoff.get("primary_markdown")
        assert isinstance(handoff.get("reusable_artifacts"), list)
        assert isinstance(handoff.get("accepts"), list)


def test_each_intent_has_exactly_one_recommended_tier():
    for intent in rp.all_intents():
        tiers = rp.propose(intent)["tiers"]
        n_rec = sum(1 for t in tiers if t["recommended"])
        assert n_rec == 1, f"{intent} has {n_rec} recommended tiers (must be exactly 1)"


def test_tiers_are_cost_monotonic_within_each_intent():
    """core <= mainline <= full by agent-hops — the 'fastest/cheapest -> deepest' promise."""
    for intent in rp.all_intents():
        hops = [t["cost"]["agent_hops"] for t in rp.propose(intent)["tiers"]]
        assert hops == sorted(hops), f"{intent} tier costs not monotonic: {hops}"
        assert hops[0] <= hops[-1]


def test_tier_mode_counts_grow():
    """The director's mental model: core ~1 mode, then more — n_modes is non-decreasing."""
    for intent in rp.all_intents():
        counts = [t["cost"]["n_modes"] for t in rp.propose(intent)["tiers"]]
        assert counts == sorted(counts), f"{intent} mode counts not non-decreasing: {counts}"
        assert counts[0] >= 1


# --------------------------------------------------------------------------- cost / gates

def test_estimate_cost_sums_registry_hops():
    one = rp.estimate_cost(["new_direction"])
    assert one["agent_hops"] == 10 and one["n_modes"] == 1 and one["band"] == "medium"
    two = rp.estimate_cost(["new_direction", "deep_research"])
    assert two["agent_hops"] == 22 and two["n_modes"] == 2 and two["band"] == "heavy"


def test_gates_in_chain_surfaces_human_gates():
    assert rp.gates_in_chain(["new_direction"]) == [{"after": "new_direction", "gate": "/idea-bet"}]
    vg = rp.gates_in_chain(["venue_readiness"])
    assert {g["gate"] for g in vg} == {"/venue-pick", "/venue-decide"}
    # a chain with no gated mode pauses nowhere automatically
    assert rp.gates_in_chain(["gap_breadth", "deep_research"]) == []


def test_chain_routes_through_idea_bet_in_the_middle():
    """validate_idea mainline: deep_research -> new_direction (/idea-bet) -> full_rigor_minimal."""
    gates = rp.gates_in_chain(["deep_research", "new_direction", "full_rigor_minimal"])
    assert gates == [{"after": "new_direction", "gate": "/idea-bet"}]


# --------------------------------------------------------------------------- validation

def test_validate_chain_accepts_a_good_chain():
    v = rp.validate_chain(["deep_research", "new_direction", "full_rigor_minimal"])
    assert v["ok"] and not v["violations"] and not v["spec_only"]


def test_validate_chain_rejects_unknown_mode():
    v = rp.validate_chain(["new_direction", "totally_fake_mode"])
    assert not v["ok"]
    assert any("unknown mode" in x for x in v["violations"])


def test_validate_chain_flags_spec_only_mode_without_hard_failing():
    """A spec-only mode is honestly FLAGGED (hand-driven), not pretended one-button — but not a hard error."""
    v = rp.validate_chain(["ideate_ring"])
    assert "ideate_ring" in v["spec_only"]
    assert v["warnings"]
    assert v["ok"], "spec-only is a flag (warning), not a violation"


def test_validate_chain_rejects_backwards_phase_order():
    v = rp.validate_chain(["venue_readiness", "new_direction"])
    assert not v["ok"]
    assert any("phase order" in x for x in v["violations"])
    # design before evidence is also backwards
    v2 = rp.validate_chain(["full_rigor_minimal", "deep_research"])
    assert not v2["ok"]


def test_within_phase_order_is_free():
    """Scanning a gap before OR after deep-reading evidence is both fine (same phase rank)."""
    assert rp.validate_chain(["gap_breadth", "deep_research"])["ok"]
    assert rp.validate_chain(["deep_research", "gap_breadth"])["ok"]


# --------------------------------------------------------------------------- intent matching

def test_match_intents_picks_validate_idea():
    ranked = rp.match_intents("我有个想法验证一下")
    assert ranked[0][0] == "validate_idea"
    assert ranked[0][1] > 0


def test_match_intents_english():
    ranked = rp.match_intents("help me find a direction for next quarter")
    assert ranked[0][0] == "find_direction"


def test_best_intents_falls_back_to_all_when_no_match():
    ids, matched = rp.best_intents("zzz completely unrelated gibberish 12345")
    assert matched is False
    assert set(ids) == set(rp.all_intents())


# --------------------------------------------------------------------------- mode questions

def test_mode_questions_map_to_known_targets():
    known_targets = {"pre_search", "budget", "north_star", "note"}
    cat = rp.load_catalog()
    for mode, qs in (cat.get("mode_questions") or {}).items():
        assert mode in rp.all_modes(), f"mode_questions references unknown mode {mode!r}"
        for q in qs:
            assert q["maps_to"] in known_targets, f"{mode}.{q['key']} maps_to unknown {q['maps_to']!r}"
            assert q.get("options"), f"{mode}.{q['key']} has no options"


def test_every_wired_mode_in_a_default_tier_has_a_drill_down_or_is_intentionally_bare():
    """Every wired mode that appears in a tier should have a question row (so a drill-down round exists)."""
    cat = rp.load_catalog()
    mq = cat.get("mode_questions") or {}
    used = {m for intent in rp.all_intents() for t in rp.propose(intent)["tiers"] for m in t["modes"]}
    for m in used:
        assert m in mq, f"wired tier mode {m!r} has no mode_questions drill-down row"


# --------------------------------------------------------------------------- propose_for_request

def test_propose_for_request_matched():
    out = rp.propose_for_request("我有个想法验证一下")
    assert out["matched"] is True
    assert out["intents"][0]["intent"] == "validate_idea"
    assert out["mode_questions"]
    rec = rp.recommended_tier(out["intents"][0]["tiers"])
    assert rec["id"] == "mainline"


def test_propose_for_request_forced_intent():
    out = rp.propose_for_request("anything", intent="prep_submission")
    assert [i["intent"] for i in out["intents"]] == ["prep_submission"]


# --------------------------------------------------------------------------- chain threading

def _write_completed_report_ledger(run_dir: Path, *, completed_stage: str = "REPORT") -> None:
    """Create a minimally valid, manifest-anchored completed-run ledger fixture."""
    ledger = run_dir / "ledger.jsonl"
    if ledger.exists():
        ledger.unlink()
    runstore.append_event(
        ledger, "run_started", {"mode": "deep_research", "entry_stage": "DISCOVER"},
        "2026-07-13T00:00:00Z",
    )
    runstore.append_event(
        ledger, "task_frame_pinned", {"task_frame_sha256": runstore.hash_file(
            run_dir / "task_frame.artifact.json")},
        "2026-07-13T00:00:01Z",
    )
    runstore.append_event(
        ledger, "step_done", {"stage": completed_stage, "artifacts": [], "idempotency_key": "fixture"},
        "2026-07-13T00:00:02Z",
    )
    boundary = runstore.append_event(
        ledger, "boundary", {"completed_stage": completed_stage, "next": None},
        "2026-07-13T00:00:03Z",
    )
    (run_dir / "manifest.yaml").write_text(
        f"status: done\nlast_boundary_hash: {boundary['hash']}\n", encoding="utf-8")


def _fake_prev_run(tmp_path, run_id="dr-1", mode="deep_research", summary="found 12 strong sources",
                   with_backlog=False):
    rd = tmp_path / "runs" / "proj" / run_id
    (rd / "evidence" / "REPORT").mkdir(parents=True)
    contract = rp._mode_handoff(mode)
    (rd / "task_frame.artifact.json").write_text(json.dumps(
        {"payload": {"mode": mode, "request_text": "validate my idea X", "task_id": run_id,
                     "product_contract": contract}}),
        encoding="utf-8")
    (rd / "evidence" / "REPORT" / "report-note.artifact.json").write_text(json.dumps(
        {"payload": {"summary": summary}}), encoding="utf-8")
    primary = str(contract.get("primary_markdown") or "")
    if primary:
        primary_path = rd / primary.replace("<paper>", "fixture-paper")
        primary_path.parent.mkdir(parents=True, exist_ok=True)
        primary_path.write_text("# Fixture product\n", encoding="utf-8")
    for name in contract.get("reusable_artifacts") or []:
        artifact = rd / "evidence" / "DISCOVER" / str(name)
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text("{}", encoding="utf-8")
    if with_backlog:
        (rd / "evidence" / "IDEATE").mkdir(parents=True)
        (rd / "evidence" / "IDEATE" / "idea-backlog.artifact.json").write_text(json.dumps(
            {"payload": {"ranked_ideas": [
                {"idea_id": "IDEA-1", "summary": "the top idea"},
                {"idea_id": "IDEA-2", "summary": "the runner up"}]}}), encoding="utf-8")
    _write_completed_report_ledger(rd)
    return str(rd)


def test_upstream_grounding_extracts_summary_and_ideas(tmp_path):
    prev = _fake_prev_run(tmp_path, with_backlog=True)
    g = rp.upstream_grounding([prev])
    assert len(g["upstream_runs"]) == 1
    up = g["upstream_runs"][0]
    assert up["mode"] == "deep_research"
    assert up["summary"] == "found 12 strong sources"
    assert [i["idea_id"] for i in up["top_ideas"]] == ["IDEA-1", "IDEA-2"]
    assert any("report-note" in a for a in up["key_artifacts"])
    assert any("idea-backlog" in a for a in up["key_artifacts"])
    assert g["handoff_contract_version"] == rp.HANDOFF_CONTRACT_VERSION
    assert up["product_contract"]["product_version"] == "research-brief/v2"
    assert up["artifact_manifest"]
    assert all(row["sha256"].startswith("sha256:") for row in up["artifact_manifest"])
    assert all(not row["run_relative_path"].startswith(str(tmp_path))
               for row in up["artifact_manifest"])


def test_gap_breadth_handoff_declares_the_artifact_the_mode_actually_writes(tmp_path):
    """The gap scan must remain consumable by deep_ideation without a singular/plural mismatch."""
    contract = rp._mode_handoff("gap_breadth")
    assert "gap-dossiers.artifact.json" in contract["reusable_artifacts"]
    assert "gap-dossier.artifact.json" not in contract["reusable_artifacts"]

    prev = _fake_prev_run(tmp_path, mode="gap_breadth")
    upstream = rp.upstream_grounding(
        [prev], downstream_mode="deep_ideation"
    )["upstream_runs"][0]
    assert "gap-dossiers.artifact.json" not in upstream["missing_declared_artifacts"]
    assert any(
        row["run_relative_path"].endswith("gap-dossiers.artifact.json")
        for row in upstream["artifact_manifest"]
    )
    assert rp._mode_handoff("gap_breadth")["accepts_delivery_statuses"] == [
        "USABLE", "USABLE_WITH_CAVEATS"
    ]


def test_pinned_upstream_product_version_wins_over_current_registry(tmp_path):
    prev = Path(_fake_prev_run(tmp_path, mode="deep_research"))
    frame = json.loads((prev / "task_frame.artifact.json").read_text(encoding="utf-8"))
    frame["payload"]["product_contract"] = {
        "contract_version": rp.HANDOFF_CONTRACT_VERSION,
        "product_version": "research-brief/v1-historical",
        "primary_markdown": "director-review/research/research-brief.md",
        "reusable_artifacts": [],
        "accepts": [],
    }
    (prev / "task_frame.artifact.json").write_text(json.dumps(frame), encoding="utf-8")

    upstream = rp.upstream_grounding([str(prev)])["upstream_runs"][0]
    assert upstream["product_contract"]["product_version"] == "research-brief/v1-historical"
    assert upstream["product_contract"]["contract_pinned"] is True
    assert upstream["product_contract"]["contract_source"] == "task_frame"


def test_handoff_compatibility_accepts_declared_chain_and_rejects_mismatch(tmp_path):
    prev = _fake_prev_run(tmp_path, mode="deep_research")
    good = rp.upstream_grounding([prev], downstream_mode="deep_ideation")
    assert good["downstream_mode"] == "deep_ideation"
    with pytest.raises(ValueError, match="mode handoff mismatch"):
        rp.upstream_grounding([prev], downstream_mode="read_paper_deep")


def test_write_upstream_grounding_rejects_incomplete_upstream_for_downstream(tmp_path):
    """A downstream mode must not treat a running, empty run as established evidence."""
    prev = Path(_fake_prev_run(tmp_path, mode="deep_research"))
    frame_path = prev / "task_frame.artifact.json"
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    frame["payload"]["product_contract"] = rp._mode_handoff("deep_research")
    frame_path.write_text(json.dumps(frame), encoding="utf-8")
    (prev / "manifest.yaml").write_text("status: running\n", encoding="utf-8")
    downstream = tmp_path / "runs" / "proj" / "downstream"
    downstream.mkdir(parents=True)
    (downstream / "task_frame.artifact.json").write_text(json.dumps({"payload": {
        "mode": "deep_ideation", "product_contract": rp._mode_handoff("deep_ideation"),
    }}), encoding="utf-8")

    with pytest.raises(ValueError, match="not complete"):
        rp.write_upstream_grounding(
            str(downstream), [str(prev)], downstream_mode="deep_ideation")


def test_write_upstream_grounding_rejects_missing_upstream_ledger(tmp_path):
    """A done manifest alone is insufficient: the upstream ledger must be present and valid."""
    prev = Path(_fake_prev_run(tmp_path, mode="deep_research"))
    (prev / "ledger.jsonl").unlink()
    downstream = tmp_path / "runs" / "proj" / "downstream-no-ledger"
    downstream.mkdir(parents=True)
    (downstream / "task_frame.artifact.json").write_text(json.dumps({"payload": {
        "mode": "deep_ideation", "product_contract": rp._mode_handoff("deep_ideation"),
    }}), encoding="utf-8")

    with pytest.raises(ValueError, match="upstream ledger"):
        rp.write_upstream_grounding(
            str(downstream), [str(prev)], downstream_mode="deep_ideation")


def test_write_upstream_grounding_rejects_tampered_upstream_ledger_chain(tmp_path):
    """An upstream ledger with a modified event cannot be used merely because REPORT exists."""
    prev = Path(_fake_prev_run(tmp_path, mode="deep_research"))
    ledger_path = prev / "ledger.jsonl"
    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    events[0]["payload"]["mode"] = "tampered-mode"
    ledger_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")
    downstream = tmp_path / "runs" / "proj" / "downstream-tampered-ledger"
    downstream.mkdir(parents=True)
    (downstream / "task_frame.artifact.json").write_text(json.dumps({"payload": {
        "mode": "deep_ideation", "product_contract": rp._mode_handoff("deep_ideation"),
    }}), encoding="utf-8")

    with pytest.raises(ValueError, match="upstream ledger chain"):
        rp.write_upstream_grounding(
            str(downstream), [str(prev)], downstream_mode="deep_ideation")


def test_write_upstream_grounding_rejects_upstream_without_report_boundary(tmp_path):
    """A hash-valid upstream ledger still cannot hand off before its REPORT boundary."""
    prev = Path(_fake_prev_run(tmp_path, mode="deep_research"))
    _write_completed_report_ledger(prev, completed_stage="DISCOVER")
    downstream = tmp_path / "runs" / "proj" / "downstream-no-report"
    downstream.mkdir(parents=True)
    (downstream / "task_frame.artifact.json").write_text(json.dumps({"payload": {
        "mode": "deep_ideation", "product_contract": rp._mode_handoff("deep_ideation"),
    }}), encoding="utf-8")

    with pytest.raises(ValueError, match="REPORT completion"):
        rp.write_upstream_grounding(
            str(downstream), [str(prev)], downstream_mode="deep_ideation")


def test_caveated_completed_research_brief_is_explicitly_handed_to_deep_ideation(tmp_path):
    """Caveated research is usable for ideation only when the consumer opts in explicitly."""
    prev = Path(_fake_prev_run(tmp_path, mode="deep_research"))
    frame_path = prev / "task_frame.artifact.json"
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    frame["payload"]["product_contract"] = rp._mode_handoff("deep_research")
    frame_path.write_text(json.dumps(frame), encoding="utf-8")
    report = prev / "evidence" / "REPORT" / "report-note.artifact.json"
    report.write_text(json.dumps({"payload": {
        "summary": "bounded research landscape",
        "delivery_status": "USABLE_WITH_CAVEATS",
        "delivery_caveats": ["no high-strength source directly proves the proposed mechanism"],
    }}), encoding="utf-8")
    (prev / "director-review" / "research").mkdir(parents=True, exist_ok=True)
    (prev / "director-review" / "research" / "research-brief.md").write_text(
        "# Caveated research brief\n", encoding="utf-8")
    for name in rp._mode_handoff("deep_research")["reusable_artifacts"]:
        path = prev / "evidence" / "DISCOVER" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}", encoding="utf-8")

    downstream = tmp_path / "runs" / "proj" / "downstream-caveated"
    downstream.mkdir(parents=True)
    (downstream / "task_frame.artifact.json").write_text(json.dumps({"payload": {
        "mode": "deep_ideation", "product_contract": rp._mode_handoff("deep_ideation"),
    }}), encoding="utf-8")

    path = rp.write_upstream_grounding(
        str(downstream), [str(prev)], downstream_mode="deep_ideation")
    grounding = json.loads(Path(path).read_text(encoding="utf-8"))
    upstream = grounding["upstream_runs"][0]
    assert upstream["delivery_status"] == "USABLE_WITH_CAVEATS"
    assert upstream["delivery_caveats"]
    assert rp.validate_upstream_grounding(grounding) == []
    assert "landscape-map.artifact.json" not in upstream["missing_declared_artifacts"]


def test_handoff_hash_change_blocks_downstream_reuse(tmp_path):
    prev = _fake_prev_run(tmp_path)
    new_run = tmp_path / "runs" / "proj" / "nd-hash"
    new_run.mkdir(parents=True)
    (new_run / "task_frame.artifact.json").write_text(json.dumps({"payload": {
        "mode": "deep_ideation", "product_contract": rp._mode_handoff("deep_ideation"),
    }}), encoding="utf-8")
    rp.write_upstream_grounding(str(new_run), [prev], downstream_mode="deep_ideation")
    report = Path(prev) / "evidence" / "REPORT" / "report-note.artifact.json"
    report.write_text('{"payload":{"summary":"replaced after handoff"}}', encoding="utf-8")
    with pytest.raises(ValueError, match="handoff integrity failed"):
        rp.augment_worker_with_upstream({"prompt": "BODY"}, str(new_run))


def test_upstream_grounding_materializes_hash_verified_citation_snapshot(tmp_path):
    """A downstream run can re-open a hash-pinned upstream citation snapshot locally."""
    prev = Path(_fake_prev_run(tmp_path))
    quote = "An exact upstream citation snapshot."
    source = prev / "inbox" / "citation-snapshots" / "fulltext-contexts.txt"
    source.parent.mkdir(parents=True)
    source.write_text(quote, encoding="utf-8")
    document_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    claim_map = prev / "evidence" / "DISCOVER" / "claim-evidence-map.artifact.json"
    claim_map.parent.mkdir(parents=True, exist_ok=True)
    claim_map.write_text(json.dumps({
        "artifact_type": "claim_evidence_map",
        "status": "approved",
        "payload": {
            "attribution_contract_version": "claim-span/v1",
            "mappings": [{
                "claim_id": "C1",
                "overall_support": "supported",
                "loci": [{
                    "locus_id": "L1",
                    "source_ref": "doi:10.1/upstream",
                    "location": "snapshot",
                    "kind": "text",
                    "reported_result": quote,
                    "supports_claim": True,
                    "support_relation": "entails",
                    "directness": "direct",
                    "span_id": "SPAN-1",
                    "snapshot_ref": "inbox/citation-snapshots/fulltext-contexts.txt",
                    "document_hash": document_hash,
                    "parser_version": "utf-8-char/v1",
                    "char_start": 0,
                    "char_end": len(quote),
                    "exact_quote": quote,
                }],
            }],
        },
    }), encoding="utf-8")

    downstream = tmp_path / "runs" / "proj" / "downstream"
    downstream.mkdir(parents=True)
    grounding_path = Path(rp.write_upstream_grounding(str(downstream), [str(prev)]))
    grounding = json.loads(grounding_path.read_text(encoding="utf-8"))

    bridge = grounding["citation_snapshot_handoff"]
    materialized_manifest = downstream / bridge["manifest_ref"]
    manifest = json.loads(materialized_manifest.read_text(encoding="utf-8"))
    assert bridge["n_snapshots"] == 1
    assert manifest["contract_version"] == "upstream-citation-snapshot/v1"
    local_ref = manifest["snapshots"][0]["local_snapshot_ref"]
    assert (downstream / local_ref).read_text(encoding="utf-8") == quote
    rebased = json.loads((downstream / manifest["rebased_claim_maps"][0]["local_claim_map_ref"])
                         .read_text(encoding="utf-8"))
    rebased_locus = rebased["payload"]["mappings"][0]["loci"][0]
    assert rebased_locus["snapshot_ref"] == local_ref
    assert rebased_locus["document_hash"] == document_hash
    assert rp.validate_materialized_citation_snapshots(downstream, grounding) == []
    report = build_attribution_report(
        {"claims": [{"claim_id": "C1", "text": "The upstream claim is supported.",
                     "source_ref": "doi:10.1/upstream"}]},
        rebased["payload"],
        {"contract_version": "citation-attribution/v1", "independent_of_linker": True,
         "claim_results": [{"claim_id": "C1", "verdict": "entails", "locator_verified": True,
                            "verified_locus_ids": ["L1"], "unsupported_locus_ids": [],
                            "notes": "Independent reread."}]},
        run_dir=downstream,
    )
    assert report["verdict"] == "PASS"


def test_materialization_uses_the_same_claim_map_bytes_it_hashes(tmp_path, monkeypatch):
    """A map replaced between hashing and parsing cannot redirect the imported snapshot set."""
    prev = Path(_fake_prev_run(tmp_path))
    source_dir = prev / "inbox" / "citation-snapshots"
    source_dir.mkdir(parents=True)
    first = source_dir / "first.txt"
    second = source_dir / "second.txt"
    first.write_text("first snapshot", encoding="utf-8")
    second.write_text("second snapshot", encoding="utf-8")
    first_hash = hashlib.sha256(first.read_bytes()).hexdigest()
    second_hash = hashlib.sha256(second.read_bytes()).hexdigest()
    claim_map = prev / "evidence" / "DISCOVER" / "claim-evidence-map.artifact.json"
    claim_map.parent.mkdir(parents=True, exist_ok=True)

    def map_payload(snapshot_name, digest):
        return {
            "artifact_type": "claim_evidence_map",
            "status": "approved",
            "payload": {
                "attribution_contract_version": "claim-span/v1",
                "mappings": [{"claim_id": "C1", "loci": [{
                    "snapshot_ref": f"inbox/citation-snapshots/{snapshot_name}",
                    "document_hash": digest,
                }]}],
            },
        }

    original_payload = map_payload("first.txt", first_hash)
    replacement_payload = map_payload("second.txt", second_hash)
    claim_map.write_text(json.dumps(original_payload), encoding="utf-8")
    grounding = rp.upstream_grounding([str(prev)])
    original_read_json = rp._read_json

    def swap_claim_map_before_parse(path):
        if Path(path) == claim_map:
            claim_map.write_text(json.dumps(replacement_payload), encoding="utf-8")
        return original_read_json(path)

    # This reproduces the old hash-then-second-read race deterministically without a timing race.
    monkeypatch.setattr(rp, "_read_json", swap_claim_map_before_parse)
    downstream = tmp_path / "runs" / "proj" / "downstream-single-read"
    (downstream / "inbox").mkdir(parents=True)
    bridge = rp.materialize_upstream_citation_snapshots(downstream, grounding)
    manifest = json.loads((downstream / bridge["manifest_ref"]).read_text(encoding="utf-8"))
    assert [row["document_hash"] for row in manifest["snapshots"]] == [first_hash]


def test_upstream_grounding_refuses_mismatched_citation_snapshot_hash(tmp_path):
    """A changed upstream snapshot never creates a partial downstream evidence copy."""
    prev = Path(_fake_prev_run(tmp_path))
    source = prev / "inbox" / "citation-snapshots" / "fulltext-contexts.txt"
    source.parent.mkdir(parents=True)
    source.write_text("changed source", encoding="utf-8")
    claim_map = prev / "evidence" / "DISCOVER" / "claim-evidence-map.artifact.json"
    claim_map.parent.mkdir(parents=True, exist_ok=True)
    claim_map.write_text(json.dumps({
        "artifact_type": "claim_evidence_map",
        "status": "approved",
        "payload": {
            "attribution_contract_version": "claim-span/v1",
            "mappings": [{"claim_id": "C1", "loci": [{
                "snapshot_ref": "inbox/citation-snapshots/fulltext-contexts.txt",
                "document_hash": "0" * 64,
            }]}],
        },
    }), encoding="utf-8")
    downstream = tmp_path / "runs" / "proj" / "downstream"
    downstream.mkdir(parents=True)

    with pytest.raises(ValueError, match="snapshot hash mismatch"):
        rp.write_upstream_grounding(str(downstream), [str(prev)])
    assert not (downstream / "inbox" / "citation-snapshots" / "upstream").exists()


def test_augment_worker_rejects_tampered_handoff_ledger_chain(tmp_path):
    """Changing both grounding and its pin payload without rehashing the ledger is rejected."""
    prev = _fake_prev_run(tmp_path)
    runs = tmp_path / "runs"
    runstore.create_run(runs, "downstream", "deep_research", "DISCOVER", "2026-07-13T00:00:00Z",
                        project="proj")
    downstream = runs / "proj" / "downstream"
    grounding_path = Path(rp.write_upstream_grounding(str(downstream), [prev]))
    runstore.pin_upstream_grounding(downstream, grounding_path, "2026-07-13T00:00:01Z")

    grounding = json.loads(grounding_path.read_text(encoding="utf-8"))
    grounding["tamper_note"] = "changed after the handoff was pinned"
    grounding_path.write_text(json.dumps(grounding), encoding="utf-8")
    ledger_path = downstream / "ledger.jsonl"
    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]
    pin = next(event for event in events if event["event_type"] == "upstream_handoff_pinned")
    pin["payload"]["grounding_sha256"] = runstore.hash_file(grounding_path)
    ledger_path.write_text("\n".join(json.dumps(event) for event in events) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="ledger chain"):
        rp.augment_worker_with_upstream({"prompt": "BODY"}, str(downstream))


def test_materialization_rejects_claim_map_outside_declared_upstream_run(tmp_path):
    """An absolute artifact path cannot redirect a handoff to another directory."""
    prev = Path(_fake_prev_run(tmp_path))
    source = prev / "inbox" / "citation-snapshots" / "fulltext-contexts.txt"
    source.parent.mkdir(parents=True)
    source.write_text("quoted upstream evidence", encoding="utf-8")
    document_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    payload = {
        "artifact_type": "claim_evidence_map",
        "status": "approved",
        "payload": {
            "attribution_contract_version": "claim-span/v1",
            "mappings": [{"claim_id": "C1", "loci": [{
                "snapshot_ref": "inbox/citation-snapshots/fulltext-contexts.txt",
                "document_hash": document_hash,
            }]}],
        },
    }
    local_map = prev / "evidence" / "DISCOVER" / "claim-evidence-map.artifact.json"
    local_map.parent.mkdir(parents=True, exist_ok=True)
    local_map.write_text(json.dumps(payload), encoding="utf-8")
    external_map = tmp_path / "external-claim-map.json"
    external_map.write_text(json.dumps(payload), encoding="utf-8")
    grounding = rp.upstream_grounding([str(prev)])
    item = next(row for row in grounding["upstream_runs"][0]["artifact_manifest"]
                if row["artifact_type"] == "claim_evidence_map")
    item["path"] = str(external_map)
    item["sha256"] = "sha256:" + hashlib.sha256(external_map.read_bytes()).hexdigest()
    downstream = tmp_path / "runs" / "proj" / "downstream"
    downstream.mkdir(parents=True)

    with pytest.raises(ValueError, match="outside the declared upstream run"):
        rp.materialize_upstream_citation_snapshots(downstream, grounding)


def test_materialization_keeps_final_handoff_absent_if_staging_write_fails(tmp_path, monkeypatch):
    """A failed multi-snapshot import cannot expose a partially written handoff."""
    prev = Path(_fake_prev_run(tmp_path))
    snap_dir = prev / "inbox" / "citation-snapshots"
    snap_dir.mkdir(parents=True)
    first = snap_dir / "first.txt"
    second = snap_dir / "second.txt"
    first.write_text("first evidence", encoding="utf-8")
    second.write_text("second evidence", encoding="utf-8")
    claim_map = prev / "evidence" / "DISCOVER" / "claim-evidence-map.artifact.json"
    claim_map.parent.mkdir(parents=True, exist_ok=True)
    claim_map.write_text(json.dumps({
        "artifact_type": "claim_evidence_map",
        "status": "approved",
        "payload": {
            "attribution_contract_version": "claim-span/v1",
            "mappings": [{"claim_id": "C1", "loci": [
                {"snapshot_ref": "inbox/citation-snapshots/first.txt",
                 "document_hash": hashlib.sha256(first.read_bytes()).hexdigest()},
                {"snapshot_ref": "inbox/citation-snapshots/second.txt",
                 "document_hash": hashlib.sha256(second.read_bytes()).hexdigest()},
            ]}],
        },
    }), encoding="utf-8")
    grounding = rp.upstream_grounding([str(prev)])
    downstream = tmp_path / "runs" / "proj" / "downstream"
    (downstream / "inbox").mkdir(parents=True)
    original = rp._write_bytes_atomic
    calls = {"count": 0}

    def fail_second_snapshot(root, ref, value, *, label):
        calls["count"] += 1
        if calls["count"] == 2:
            raise OSError("simulated staging write failure")
        return original(root, ref, value, label=label)

    monkeypatch.setattr(rp, "_write_bytes_atomic", fail_second_snapshot)
    with pytest.raises(OSError, match="staging write failure"):
        rp.materialize_upstream_citation_snapshots(downstream, grounding)
    assert not (downstream / "inbox" / "upstream-citation-handoff").exists()
    assert not list((downstream / "inbox").glob(".upstream-citation-handoff-*"))


def test_write_upstream_grounding_checks_a_reparse_parent_before_any_mkdir(tmp_path, monkeypatch):
    """Portable stand-in for a Windows junction, which CI may lack permission to create."""
    prev = _fake_prev_run(tmp_path)
    downstream = tmp_path / "runs" / "proj" / "downstream-reparse"
    inbox = downstream / "inbox"
    inbox.mkdir(parents=True)
    (downstream / "task_frame.artifact.json").write_text(json.dumps({"payload": {
        "mode": "deep_ideation", "product_contract": rp._mode_handoff("deep_ideation"),
    }}), encoding="utf-8")
    original_reparse = rp._is_reparse_point
    original_mkdir = Path.mkdir

    def fake_reparse(path):
        return Path(path) == inbox or original_reparse(path)

    def fail_if_unchecked_inbox_mkdir(path, *args, **kwargs):
        if Path(path) == inbox:
            raise AssertionError("unsafe inbox mkdir before reparse check")
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(rp, "_is_reparse_point", fake_reparse)
    monkeypatch.setattr(Path, "mkdir", fail_if_unchecked_inbox_mkdir)
    with pytest.raises(ValueError, match="symlink or junction"):
        rp.write_upstream_grounding(
            str(downstream), [prev], downstream_mode="deep_ideation")


def test_handoff_manifest_itself_is_ledger_pinned(tmp_path):
    prev = _fake_prev_run(tmp_path)
    runs = tmp_path / "runs"
    runstore.create_run(runs, "nd-ledger", "deep_ideation", "DISCOVER", "2026-07-11T00:00:00Z",
                        project="proj")
    new_run = runs / "proj" / "nd-ledger"
    (new_run / "task_frame.artifact.json").write_text(json.dumps({"payload": {
        "mode": "deep_ideation",
        "product_contract": {
            "contract_version": rp.HANDOFF_CONTRACT_VERSION,
            "product_version": "idea-investment-memo/v2",
            "primary_markdown": "director-review/ideas/idea-bet-menu.md",
            "reusable_artifacts": [],
            "accepts": ["research-brief/v2"],
        },
    }}), encoding="utf-8")
    handoff_path = rp.write_upstream_grounding(
        str(new_run), [prev], downstream_mode="deep_ideation")
    runstore.pin_upstream_grounding(new_run, handoff_path, "2026-07-11T00:00:01Z")
    assert rp.augment_worker_with_upstream({"prompt": "BODY"}, str(new_run))

    handoff = json.loads(Path(handoff_path).read_text(encoding="utf-8"))
    handoff["downstream_mode"] = "tampered-mode"
    Path(handoff_path).write_text(json.dumps(handoff), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest hash does not match its ledger pin"):
        rp.augment_worker_with_upstream({"prompt": "BODY"}, str(new_run))


def test_upstream_grounding_robust_to_empty_run(tmp_path):
    empty = tmp_path / "runs" / "proj" / "empty-1"
    empty.mkdir(parents=True)
    g = rp.upstream_grounding([str(empty)])
    assert g["upstream_runs"][0]["run_id"] == "empty-1"
    assert g["upstream_runs"][0]["summary"] == ""


def test_write_and_augment_single_worker(tmp_path):
    prev = _fake_prev_run(tmp_path)
    runs = tmp_path / "runs"
    runstore.create_run(runs, "nd-2", "deep_research", "DISCOVER", "2026-07-13T00:00:00Z",
                        project="proj")
    new_run = runs / "proj" / "nd-2"
    grounding = rp.write_upstream_grounding(str(new_run), [prev])
    runstore.pin_upstream_grounding(new_run, grounding, "2026-07-13T00:00:01Z")
    worker = {"label": "x", "prompt": "ORIGINAL PROMPT BODY"}
    out = rp.augment_worker_with_upstream(worker, str(new_run))
    assert "ORIGINAL PROMPT BODY" in out["prompt"]
    assert "PRIOR CHAIN CONTEXT" in out["prompt"]
    assert "found 12 strong sources" in out["prompt"]


def test_augment_panel_worker(tmp_path):
    prev = _fake_prev_run(tmp_path)
    runs = tmp_path / "runs"
    runstore.create_run(runs, "nd-3", "deep_research", "DISCOVER", "2026-07-13T00:00:00Z",
                        project="proj")
    new_run = runs / "proj" / "nd-3"
    grounding = rp.write_upstream_grounding(str(new_run), [prev])
    runstore.pin_upstream_grounding(new_run, grounding, "2026-07-13T00:00:01Z")
    worker = {"workers": [{"prompt": "A"}, {"prompt": "B"}], "panel_note": "n"}
    out = rp.augment_worker_with_upstream(worker, str(new_run))
    assert all("PRIOR CHAIN CONTEXT" in w["prompt"] for w in out["workers"])
    assert out["workers"][0]["prompt"].startswith("A")


def test_augment_panel_sends_full_upstream_only_to_root_workers(tmp_path):
    prev = _fake_prev_run(tmp_path)
    runs = tmp_path / "runs"
    runstore.create_run(runs, "nd-4", "deep_research", "DISCOVER", "2026-07-13T00:00:00Z",
                        project="proj")
    new_run = runs / "proj" / "nd-4"
    grounding = rp.write_upstream_grounding(str(new_run), [prev])
    runstore.pin_upstream_grounding(new_run, grounding, "2026-07-13T00:00:01Z")
    panel = {"workers": [
        {"label": "root", "prompt": "ROOT"},
        {"label": "child", "prompt": "CHILD", "depends_on": ["root"]},
    ]}
    out = rp.augment_worker_with_upstream(panel, str(new_run))
    assert "found 12 strong sources" in out["workers"][0]["prompt"]
    assert "pointer only" in out["workers"][1]["prompt"]
    assert "found 12 strong sources" not in out["workers"][1]["prompt"]


def test_augment_is_noop_without_grounding(tmp_path):
    new_run = tmp_path / "runs" / "proj" / "solo-1"
    new_run.mkdir(parents=True)
    worker = {"prompt": "UNCHANGED"}
    out = rp.augment_worker_with_upstream(worker, str(new_run))
    assert out["prompt"] == "UNCHANGED"


def test_augment_handles_none_worker(tmp_path):
    new_run = tmp_path / "runs" / "proj" / "solo-2"
    new_run.mkdir(parents=True)
    assert rp.augment_worker_with_upstream(None, str(new_run)) is None


# --------------------------------------------------------------------------- CLI plan-propose

def test_cli_plan_propose_emits_valid_json(capsys):
    from research_agent_teams.operate.cli import main
    main(["plan-propose", "--request", "帮我找个研究方向"])
    out = json.loads(capsys.readouterr().out)
    assert out["matched"] is True
    assert out["intents"][0]["intent"] == "find_direction"
    # the recommended tier is a real, validated chain
    tiers = out["intents"][0]["tiers"]
    rec = [t for t in tiers if t["recommended"]][0]
    assert rec["validation"]["ok"]
    assert rec["cost"]["agent_hops"] > 0


def test_cli_plan_propose_forced_intent(capsys):
    from research_agent_teams.operate.cli import main
    main(["plan-propose", "--request", "x", "--intent", "scan_gaps"])
    out = json.loads(capsys.readouterr().out)
    assert [i["intent"] for i in out["intents"]] == ["scan_gaps"]


# --------------------------------------------------------------------------- catalog load caching

def test_a_catalog_is_parsed_once_but_an_on_disk_edit_still_takes_effect(tmp_path, monkeypatch):
    """Parsing these two files cost ~84 ms each and the outcome menu did it hundreds of times.

    Caching is only safe if a hand-edit is still picked up with no restart, so pin both halves.
    """
    path = tmp_path / "catalog.yaml"
    path.write_text("version: 1\nintents: {}\n", encoding="utf-8")
    parses = []
    real_load = rp.yaml.safe_load
    monkeypatch.setattr(rp.yaml, "safe_load",
                        lambda text: (parses.append(1), real_load(text))[1])

    assert rp.load_catalog(str(path))["version"] == 1
    assert rp.load_catalog(str(path))["version"] == 1
    assert len(parses) == 1, "the second read re-parsed the file"

    path.write_text("version: 2\nintents: {}\n", encoding="utf-8")
    assert rp.load_catalog(str(path))["version"] == 2
    assert len(parses) == 2


def test_a_caller_that_edits_a_loaded_catalog_cannot_poison_the_next_caller(tmp_path):
    """Existing callers deep-copy before mutating; the cache must not turn that habit into a trap."""
    path = tmp_path / "registry.yaml"
    path.write_text("modes:\n  demo:\n    operated: true\n", encoding="utf-8")
    first = rp.load_mode_registry(str(path))
    first["modes"]["demo"]["operated"] = False
    first["modes"]["injected"] = {"operated": True}
    second = rp.load_mode_registry(str(path))
    assert second["modes"]["demo"]["operated"] is True
    assert "injected" not in second["modes"]
