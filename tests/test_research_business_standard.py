from research_agent_teams.tools.research_business_standard import (
    MARKER,
    decorate_worker_quality,
    stage_quality_block,
)


def test_stage_blocks_encode_real_scientific_work():
    assert "disconfirming" in stage_quality_block("DISCOVER")
    assert "minimum falsification experiment" in stage_quality_block("IDEATE")
    assert "statistical plan" in stage_quality_block("DESIGN")
    assert "actually completed" in stage_quality_block("EXECUTE")
    assert "alternative explanations" in stage_quality_block("ANALYZE")
    assert "strongest rejection argument" in stage_quality_block("VERIFY")
    assert "human-readable Markdown" in stage_quality_block("REPORT")


def test_single_worker_gets_quality_contract_once():
    worker = {"label": "x", "model": "opus", "prompt": "Do the task."}
    decorate_worker_quality(worker, "IDEATE")
    decorate_worker_quality(worker, "IDEATE")
    assert worker["prompt"].count(MARKER) == 1
    assert "kill criteria" in worker["prompt"]


def test_every_panel_worker_gets_the_same_stage_contract():
    panel = {
        "workers": [
            {"label": "a", "prompt": "A"},
            {"label": "b", "prompt": "B"},
            {"label": "c", "prompt": "C"},
        ]
    }
    decorate_worker_quality(panel, "VERIFY")
    assert all(MARKER in worker["prompt"] for worker in panel["workers"])
    assert all("fatal blockers" in worker["prompt"] for worker in panel["workers"])
