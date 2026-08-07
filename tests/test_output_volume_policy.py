"""Worker output volume is FLOOR-bounded, never CAP-bounded (director lock 2026-08-04).

Director's words: *"这些个 agents 输出的东西是不是太少了？…量大的输出，不要控制住，本身就需要量大，
最后才会有丰富的语义和计划，ideas，methods 等等等产物."*

Why this is a real policy and not a preference — measured inside ONE run
(`new_direction-20260804T052848Z`, all seats on the same model, same corpus of 122 retrieved records):

* the mechanism-graph packet stated a **floor** (">=3 nodes and >=2 edges") and the seat returned
  **31 nodes / 38 edges** — the artifact three independent reviewers called substantive;
* the evidence-table packet stated a **cap** ("sources 4-6") and the seat returned **exactly 6** — the
  thing the same three reviewers called too thin to support a novelty claim.

Same model, same run, opposite instruction shapes, opposite outcomes. For WORKER OUTPUT the throttle was
never the model and never the schema (only 14 of 167 schemas carry any `maxItems`, and none on the output
arrays) — it was the packet wording. These tests pin the wording.

Do not generalise that into "there were no caps anywhere". A second round (2026-08-04, same day) found a
real one on a different array: the number of external METHOD LENSES that may reach a worker was pinned to
five by four agreeing locks — `selection_max` in the overlay catalog policy, an equality check on that same
number inside `load_overlay_catalog`, `maxItems: 5` on `task_frame /capability_overlay_plan/overlays`, and a
literal `<= 5` in two tests. Volume of *output* and breadth of *input guidance* are separate dials; that one
is pinned by `test_external_method_channel_is_not_recapped`.

They deliberately do NOT assert prose, only the SHAPE of the quantity instruction, so the templates stay
free to be rewritten as long as they keep asking for volume.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

MODES = Path(__file__).resolve().parents[1] / "operate" / "modes"

#: Every template that tells a worker how many items to produce, with the token that must carry a floor.
VOLUME_TEMPLATES = {
    "new_direction.py": ("evidence_table.sources",),
    # The proposer/ranker templates moved to _ideation_prompts.py on 2026-08-07 (new_direction.py had
    # outgrown the size limit). The floor policy follows the text, not the file.
    "_ideation_prompts.py": ("hypotheses",),
    "evidence_review.py": ("sources",),
    "deep_research.py": ("sources",),
    "evidence_deep.py": ("sources",),
    "gap_breadth.py": ("signals",),
    "_deep_ideate.py": ("mappings",),
}

#: A range like "4-6 sources" or "Emit 3-5 ideas" is a cap in disguise: it tells the worker where to stop.
#: Years (2025), ASVS-style versions and file/line refs are not quantity instructions, so the pattern is
#: anchored to a following countable noun.
_COUNTABLE = (r"sources|claims|signals|ideas|hypotheses|nodes|edges|mappings|conflicts|"
              r"gaps|sketches|items")
_CAP = re.compile(
    # both word orders occur in the real templates: "4-6 sources" and "sources 4-6"
    rf"(\b\d+\s*-\s*\d+\s+(?:{_COUNTABLE})\b)|(\b(?:{_COUNTABLE})\s+\d+\s*-\s*\d+\b)",
    re.IGNORECASE,
)
_EMIT_CAP = re.compile(r"\b[Ee]mit\s+\d+\s*-\s*\d+\b")


@pytest.mark.parametrize("filename", sorted(VOLUME_TEMPLATES))
def test_no_quantity_instruction_is_a_closed_range(filename):
    """A closed range caps output. Floors (">=N") are the only permitted quantity instruction."""
    source = (MODES / filename).read_text(encoding="utf-8")
    caps = _CAP.findall(source) + _EMIT_CAP.findall(source)
    assert caps == [], (
        f"{filename} still caps worker output with a closed range: {caps}. "
        "State a floor (>=N) instead — the director's lock is volume, bounded per-item by the quality bar, "
        "not by a count.")


@pytest.mark.parametrize("filename,tokens", sorted(VOLUME_TEMPLATES.items()))
def test_every_volume_template_states_a_floor(filename, tokens):
    """Removing a cap is only half the fix; the packet must positively ask for a floor."""
    source = (MODES / filename).read_text(encoding="utf-8")
    assert ">=" in source, f"{filename} states no floor at all"
    for token in tokens:
        # The floor and its noun must appear in the same instruction, in either order.
        near = re.search(
            rf"(>=\s*\d+[^\n]{{0,80}}{re.escape(token)})|({re.escape(token)}[^\n]{{0,80}}>=\s*\d+)",
            source)
        assert near, f"{filename} does not tie a floor to {token!r}"


@pytest.mark.parametrize("filename", sorted(VOLUME_TEMPLATES))
def test_no_template_tells_a_worker_to_keep_the_list_short(filename):
    """The anti-volume instruction that produced the thin run must not come back in any wording."""
    source = (MODES / filename).read_text(encoding="utf-8")
    banned = [
        "fewer, sharper",
        "beat a long shallow list",
        "beats a long shallow list",
        "keep the list short:",
    ]
    hits = [phrase for phrase in banned if phrase in source]
    assert hits == [], f"{filename} still discourages volume: {hits}"


def test_the_quality_bar_survived_the_volume_change():
    """Volume was raised; grounding was NOT relaxed. This is the safety floor, not a style point."""
    own = (MODES / "new_direction.py").read_text(encoding="utf-8")
    for required in ("Ground every claim/gap in a real page",
                     "genuinely OPEN"):     # each gap must still be defensible one by one
        assert required in own, f"the per-item quality bar lost: {required!r}"
    # The fabricated-reference block is shared by every mode, so it is pinned where it lives.
    shared = (MODES / "_shared.py").read_text(encoding="utf-8")
    assert "never invent a slug" in shared, "the fabricated-vault-ref block lost"


def test_cap_detector_would_have_caught_the_pre_lock_wording():
    """A guard that cannot fail is not a guard — check it against the real pre-fix strings."""
    assert _CAP.search("Quantities: evidence_table.sources 4-6 (>=1 \"strong\"); claims 2-3")
    assert _EMIT_CAP.search("Emit 3-5 hypotheses and 3-5 ideas.")
    # And it must not fire on things that merely look numeric.
    assert not _CAP.search("year 2024-2025 coverage")
    assert not _EMIT_CAP.search("see lines 10-20 of the contract")


# ------------------------------------------- workers must be TOLD the upstream originals exist
# Director question 2026-08-04: "现在的 research team 的能力是不是已经可以使用外部那些仓库 skills 的能力了?"
# Measured answer at the time: no — 358 vendored bundles were distilled into 11 summary cards, and NOT ONE
# packet named the originals, so a worker could not consult the upstream method in its own words even
# though the text sits on disk. The pointer below is the fix; the execution boundary is unchanged.

def test_a_worker_packet_names_the_vendored_upstream_originals():
    from research_agent_teams.operate import panel_scheduler

    pointer = panel_scheduler._UPSTREAM_ORIGINALS_POINTER
    assert "vendor/upstream-research-skills" in pointer, "the pointer must name a real path"
    assert "workbench capabilities" in pointer, "the pointer must name how to search it"
    # And the read-only boundary must travel with it, or the pointer becomes an execution invitation.
    lowered = pointer.lower()
    assert "never execute" in lowered and "never install" in lowered


def test_the_vendored_path_the_pointer_names_actually_exists():
    """A pointer to a path that does not exist is worse than no pointer."""
    from research_agent_teams.operate import panel_scheduler

    machine_root = Path(panel_scheduler.__file__).resolve().parents[1]   # …/research_agent_teams
    assert (machine_root / "vendor" / "upstream-research-skills").is_dir(), (
        "the packet points workers at a directory that is not there")


def test_the_pointer_reaches_a_real_packet_not_just_the_constant():
    """Wired, not merely defined: any stage carrying an overlay plan must render the pointer."""
    import json

    from research_agent_teams.operate.panel_scheduler import capability_overlay_block

    tmp = Path(__file__).resolve().parents[1] / "runs" / "_volume_policy_probe"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        (tmp / "task_frame.artifact.json").write_text(json.dumps({"payload": {
            "capability_overlay_plan": {
                "contract_version": "research-capability-route/v1",
                "overlays": [{"overlay_id": "x", "title": "T", "guidance": "G",
                              "target_stages": ["DISCOVER"], "non_goals": []}],
            }}}), encoding="utf-8")
        block, contract = capability_overlay_block(tmp, "DISCOVER")
        assert "vendor/upstream-research-skills" in block
        assert contract["external_skill_execution"] is False, (
            "telling a worker where the text is must not flip the execution boundary")
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
