"""Schema validate/reject tests for figure_reading.schema.json (P1, paper-reading upgrade).

Uses validate_against(schema_filename, instance) which validates directly against
a schema file — no PAYLOAD_SCHEMAS registration needed (green before the lead's
registry step).

Covers: (a) a valid full instance accepts, (b) a missing-required instance rejects,
(c) an unknown-property instance rejects (proves additionalProperties:false).
"""
from __future__ import annotations

from research_agent_teams.tools.validate_artifact import validate_against


# ===========================================================================
# figure_reading.schema.json — required [source_ref, figures]
# ===========================================================================

_GOOD_FIGURE_READING = {
    "source_ref": "arxiv:2409.00001",
    "figures": [
        {
            "figure_ref": "Figure 3",
            "axes": "x: training set size; y: Dice on held-out test.",
            "controls": "Compared against nnU-Net and TransUNet baselines.",
            "error_bars": "95% CI over 5 seeds.",
            "take_home": "The method holds its margin even at small training sizes.",
            "distrust": "Only one dataset; no cross-center validation shown.",
        },
        {
            "figure_ref": "Figure 5",
            "axes": "Qualitative panels: GT vs prediction overlays.",
            "controls": None,
            "error_bars": None,
            "take_home": "Predictions visually recover the thin canal tail.",
            "distrust": "Cherry-picked best cases; no failure example.",
        },
    ],
}


def test_figure_reading_valid():
    assert validate_against("figure_reading.schema.json", _GOOD_FIGURE_READING) == []


def test_figure_reading_minimal_figure_valid():
    """A figure with only the required figure_ref + take_home is valid."""
    good = {
        "source_ref": "arxiv:2409.00001",
        "figures": [{"figure_ref": "Figure 1", "take_home": "Overview of the pipeline."}],
    }
    assert validate_against("figure_reading.schema.json", good) == []


def test_figure_reading_empty_figures_valid():
    """An empty figures list is schema-valid (the field must be present, not non-empty)."""
    good = {"source_ref": "arxiv:2409.00001", "figures": []}
    assert validate_against("figure_reading.schema.json", good) == []


def test_figure_reading_missing_source_ref_rejected():
    bad = {"figures": [{"figure_ref": "Figure 1", "take_home": "x"}]}
    assert validate_against("figure_reading.schema.json", bad) != []


def test_figure_reading_missing_figures_rejected():
    bad = {"source_ref": "arxiv:2409.00001"}
    assert validate_against("figure_reading.schema.json", bad) != []


def test_figure_reading_empty_source_ref_rejected():
    """Empty source_ref (minLength 1) is rejected."""
    bad = {"source_ref": "", "figures": []}
    assert validate_against("figure_reading.schema.json", bad) != []


def test_figure_reading_figure_missing_figure_ref_rejected():
    """Each figure requires figure_ref."""
    bad = {
        "source_ref": "arxiv:2409.00001",
        "figures": [{"take_home": "Some take-home with no figure_ref."}],
    }
    assert validate_against("figure_reading.schema.json", bad) != []


def test_figure_reading_figure_missing_take_home_rejected():
    """Each figure requires take_home."""
    bad = {
        "source_ref": "arxiv:2409.00001",
        "figures": [{"figure_ref": "Figure 2", "axes": "x vs y"}],
    }
    assert validate_against("figure_reading.schema.json", bad) != []


def test_figure_reading_unknown_top_level_property_rejected():
    """additionalProperties:false — an unknown top-level key is rejected."""
    bad = {
        "source_ref": "arxiv:2409.00001",
        "figures": [],
        "not_a_real_field": "leak",
    }
    assert validate_against("figure_reading.schema.json", bad) != []


def test_figure_reading_figure_unknown_property_rejected():
    """Each figure is additionalProperties:false."""
    bad = {
        "source_ref": "arxiv:2409.00001",
        "figures": [
            {"figure_ref": "Figure 2", "take_home": "x", "caption": "leaks an extra field"}
        ],
    }
    assert validate_against("figure_reading.schema.json", bad) != []
