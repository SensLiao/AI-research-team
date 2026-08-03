"""The workbench's honesty floor: an evidence state above SIMULATED cannot be self-claimed."""
from __future__ import annotations

from research_agent_teams.workbench.model import (
    EVIDENCE_LADDER,
    EVIDENCE_STATE_WORDS,
    SELF_CLAIMABLE_CEILING,
    WORK_STATE_WORDS,
    EvidenceState,
    ProjectRow,
    TaskRow,
    WorkState,
    coerce_evidence_state,
    coerce_work_state,
    derive_evidence_state,
)


# --------------------------------------------------------------------- the ladder itself

def test_every_state_has_plain_chinese_words_so_a_view_never_shows_a_bare_code():
    for state in EvidenceState:
        assert EVIDENCE_STATE_WORDS[state].strip()
    for state in WorkState:
        assert WORK_STATE_WORDS[state].strip()


def test_superseded_is_outside_the_ladder_because_it_is_terminal():
    assert EvidenceState.SUPERSEDED not in EVIDENCE_LADDER
    assert EVIDENCE_LADDER[-1] is EvidenceState.FROZEN


def test_the_self_claimable_ceiling_sits_below_observed():
    assert SELF_CLAIMABLE_CEILING is EvidenceState.SIMULATED
    assert EVIDENCE_LADDER.index(SELF_CLAIMABLE_CEILING) < EVIDENCE_LADDER.index(
        EvidenceState.OBSERVED
    )


# ------------------------------------------------------- derivation from facts (no claim)

def test_no_execution_record_is_only_a_proposal():
    verdict = derive_evidence_state()
    assert verdict.state is EvidenceState.PROPOSED
    assert verdict.downgraded_from is None


def test_a_dry_run_is_a_dry_run():
    assert derive_evidence_state(ran_dry=True).state is EvidenceState.DRY_RUN


def test_synthetic_data_reaches_simulated_but_no_further():
    assert derive_evidence_state(simulated=True, ran_dry=True).state is EvidenceState.SIMULATED


def test_a_receipt_bound_to_raw_result_bytes_is_the_only_route_to_observed():
    assert derive_evidence_state(
        has_executor_receipt=True, has_raw_result=True
    ).state is EvidenceState.OBSERVED
    # Either half alone proves nothing.
    assert derive_evidence_state(has_executor_receipt=True).state is EvidenceState.PROPOSED
    assert derive_evidence_state(has_raw_result=True).state is EvidenceState.PROPOSED


def test_frozen_needs_a_human_freeze_on_top_of_real_observation():
    assert derive_evidence_state(
        has_executor_receipt=True, has_raw_result=True, human_frozen=True
    ).state is EvidenceState.FROZEN


def test_a_freeze_over_unobserved_work_cannot_make_a_proposal_citable():
    verdict = derive_evidence_state(human_frozen=True, claimed="frozen")
    assert verdict.state is EvidenceState.PROPOSED
    assert verdict.downgraded_from is EvidenceState.FROZEN
    assert "没有执行凭据" in verdict.reason


def test_superseded_beats_every_other_fact_including_a_real_receipt():
    verdict = derive_evidence_state(
        has_executor_receipt=True, has_raw_result=True, human_frozen=True, superseded=True
    )
    assert verdict.state is EvidenceState.SUPERSEDED


# ------------------------------------------------------------------- claims are not proof

def test_claiming_observed_without_receipts_is_downgraded_to_the_honest_floor():
    verdict = derive_evidence_state(claimed="observed", ran_dry=True)
    assert verdict.state is EvidenceState.DRY_RUN
    assert verdict.downgraded_from is EvidenceState.OBSERVED


def test_claiming_frozen_without_receipts_is_downgraded_too():
    verdict = derive_evidence_state(claimed="frozen", simulated=True)
    assert verdict.state is EvidenceState.SIMULATED
    assert verdict.downgraded_from is EvidenceState.FROZEN


def test_a_claim_inside_the_ceiling_is_honoured():
    verdict = derive_evidence_state(claimed="simulated")
    assert verdict.state is EvidenceState.SIMULATED
    assert verdict.downgraded_from is None


def test_a_claim_below_the_established_floor_never_lowers_a_real_observation():
    verdict = derive_evidence_state(
        claimed="proposed", has_executor_receipt=True, has_raw_result=True
    )
    assert verdict.state is EvidenceState.OBSERVED


def test_a_junk_claim_is_dropped_rather_than_guessed():
    assert coerce_evidence_state("definitely-true") is None
    assert coerce_evidence_state(None) is None
    assert derive_evidence_state(claimed="definitely-true").state is EvidenceState.PROPOSED


def test_the_verdict_serializes_with_its_reason_so_a_reader_need_not_trust_it():
    payload = derive_evidence_state(claimed="observed").as_dict()
    assert payload["evidence_state"] == "proposed"
    assert payload["downgraded_from"] == "observed"
    assert payload["evidence_state_label"] and payload["reason"]


# ------------------------------------------------------------- the two states stay separate

def test_an_unknown_work_state_falls_back_instead_of_inventing_progress():
    assert coerce_work_state("shipped-probably") is WorkState.BACKLOG
    assert coerce_work_state("shipped-probably", WorkState.READY) is WorkState.READY
    assert coerce_work_state("active") is WorkState.ACTIVE


def test_a_finished_task_can_still_carry_the_weakest_evidence():
    """The whole point of splitting the states: "code is written" != "hypothesis supported"."""
    row = TaskRow(
        task_id="T-042",
        project="petct-residual-correction",
        title="Test whether M0 encodes intent rather than localization",
        work_state="done",
        evidence_state="proposed",
        priority="P0",
    ).as_dict()
    assert row["work_state"] == "done"
    assert row["evidence_state"] == "proposed"
    assert row["work_state_label"] and row["evidence_state_label"]


def test_task_and_project_rows_round_trip_their_sequences_as_lists():
    task = TaskRow(
        task_id="T-1", project="p", title="t", blockers=("waiting on a GPU slot",)
    ).as_dict()
    assert task["blockers"] == ["waiting on a GPU slot"]
    project = ProjectRow(
        slug="p", truth_boundary=("0 publishable six-class result",), counts={"artifacts": 3}
    ).as_dict()
    assert project["truth_boundary"] == ["0 publishable six-class result"]
    assert project["counts"] == {"artifacts": 3}
    assert project["title"] == "p"
