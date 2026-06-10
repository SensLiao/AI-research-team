"""recall TEMPR rebuild — four-channel fusion behaviours the old token-only recall could not do (wave 1)."""
from __future__ import annotations

import json

from research_agent_teams.tools import recall
from research_agent_teams.tools.validate_artifact import validate_artifact
from research_agent_teams.operate.artifacts import envelope

TS = "2026-06-10T12:00:00Z"


def _page(root, folder, slug, body):
    d = root / "02-wiki" / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{slug}.md").write_text(body, encoding="utf-8")


def _index(root, slugs):
    (root / "00-system").mkdir(parents=True, exist_ok=True)
    (root / "00-system" / "index.md").write_text(
        "# Index\n" + "\n".join(f"- [[{s}]]" for s in slugs), encoding="utf-8")


def _validate(note):
    return validate_artifact(envelope("recall_note", "recall", note, TS))


def test_body_match_found_without_slug_overlap(tmp_path):
    """The headline TEMPR win: the query words appear only in the BODY, not the slug."""
    _page(tmp_path, "papers", "kirchhoff-2024-skeleton-recall",
          "---\ntype: paper\nyear: 2024\n---\n# Skeleton Recall\n\n"
          "Introduces a tubular continuity loss for centerline preservation in thin structures.\n")
    _page(tmp_path, "papers", "unrelated-botany-catalog",
          "---\ntype: paper\nyear: 2020\n---\n# Botany\n\nA catalogue of ferns.\n")
    _index(tmp_path, ["kirchhoff-2024-skeleton-recall", "unrelated-botany-catalog"])

    note = recall.recall("tubular continuity centerline preservation", vault_root=tmp_path)
    assert _validate(note) == []
    assert note["vault_silent"] is False
    assert note["citations"][0]["slug"] == "kirchhoff-2024-skeleton-recall"
    assert "bm25" in note["citations"][0]["supports"]


def test_wikilink_neighbor_expansion(tmp_path):
    """A page with no direct match gets surfaced as a 1-hop wikilink neighbor of a strong hit."""
    _page(tmp_path, "papers", "canal-segmentation-survey",
          "---\ntype: paper\nyear: 2023\n---\n# Canal segmentation survey\n\n"
          "Surveys canal segmentation; see also [[toothfairy-dataset-card]].\n")
    _page(tmp_path, "datasets", "toothfairy-dataset-card",
          "---\ntype: dataset\nyear: 2024\n---\n# ToothFairy\n\nVolumes and annotations.\n")
    _index(tmp_path, ["canal-segmentation-survey", "toothfairy-dataset-card"])

    note = recall.recall("canal segmentation survey", vault_root=tmp_path)
    slugs = [c["slug"] for c in note["citations"]]
    assert slugs[0] == "canal-segmentation-survey"
    assert "toothfairy-dataset-card" in slugs                       # neighbor surfaced
    nb = next(c for c in note["citations"] if c["slug"] == "toothfairy-dataset-card")
    assert "wikilink-neighbor" in nb["supports"]


def test_temporal_channel_reorders_genuine_ties(tmp_path):
    """Two equally-matching pages: the newer one ranks first (tie-aware RRF + temporal channel)."""
    body = "---\ntype: result\nyear: {y}\n---\n# Result\n\nfrozen split dice ablation result.\n"
    _page(tmp_path, "results", "aaa-old-result", body.format(y=2019))
    _page(tmp_path, "results", "bbb-new-result", body.format(y=2025))
    _index(tmp_path, ["aaa-old-result", "bbb-new-result"])

    note = recall.recall("frozen split dice ablation", vault_root=tmp_path)
    slugs = [c["slug"] for c in note["citations"]]
    # without the temporal channel the slug-ASC tiebreak would put aaa-old-result first
    assert slugs.index("bbb-new-result") < slugs.index("aaa-old-result")
    newer = next(c for c in note["citations"] if c["slug"] == "bbb-new-result")
    assert "recency(2025)" in newer["supports"]


def test_stopword_query_stays_silent_against_unrelated_vault(tmp_path):
    """Adversarial (reviewer HIGH): a query of pure function words must NOT defeat vault_silent by
    matching ubiquitous body tokens. Without stopword filtering the BM25 channel's positive idf
    floor returned high-confidence citations for any vault."""
    _page(tmp_path, "papers", "medical-imaging-only",
          "---\ntype: paper\nyear: 2024\n---\n# Imaging\n\n"
          "This is a paper about how the segmentation works with the data for the task.\n")
    _index(tmp_path, ["medical-imaging-only"])
    note = recall.recall("how does the universe work with this", vault_root=tmp_path)
    assert _validate(note) == []
    assert note["vault_silent"] is True                         # all query tokens were stopwords
    assert note["citations"] == []
    # the topical word still matches when it is genuinely present
    topical = recall.recall("segmentation task", vault_root=tmp_path)
    assert topical["vault_silent"] is False


def test_by_reference_no_body_leak_and_silent_unchanged(tmp_path):
    _page(tmp_path, "results", "medsam3-lora-ablation",
          "---\ntype: result\nyear: 2026\n---\n# MedSAM3 LoRA ablation\n\n"
          "SECRET_BODY_TOKEN dice=0.79 on the frozen split.\n")
    _index(tmp_path, ["medsam3-lora-ablation"])

    note = recall.recall("medsam3 lora ablation dice", vault_root=tmp_path)
    assert "SECRET_BODY_TOKEN" not in json.dumps(note)              # pointers only, never body
    assert note["citations"][0]["sha256"].startswith("sha256:")

    silent = recall.recall("quantum chromodynamics lattice", vault_root=tmp_path)
    assert silent["vault_silent"] is True and silent["citations"] == []
    assert silent["closest"]["slug"] == "medsam3-lora-ablation"     # newest page never auto-cited


def test_top_k_cap_and_determinism(tmp_path):
    for i in range(8):
        _page(tmp_path, "papers", f"paper-{i}-dice-study",
              f"---\ntype: paper\nyear: 202{i % 6}\n---\n# Study {i}\n\ndice study segmentation.\n")
    _index(tmp_path, [f"paper-{i}-dice-study" for i in range(8)])

    a = recall.recall("dice study segmentation", vault_root=tmp_path)
    b = recall.recall("dice study segmentation", vault_root=tmp_path)
    assert a == b                                                    # deterministic
    assert len(a["citations"]) == 6                                  # TOP_K cap
    assert _validate(a) == []
