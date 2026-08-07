"""Regression tests for the director-reviewed final-Markdown admission lane.

The tests deliberately prove the boundary the user asked for: readable documents can be copied into the
vault and later survive scratch cleanup, but that path cannot masquerade as a frozen experiment result.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from research_agent_teams.tools.document_promotion import (
    document_admission_is_authorized,
    run_document_admission_batch,
)
from research_agent_teams.tools.ledger import read_events, verify_chain
from research_agent_teams.tools.promote_gate import document_candidate_paths
from research_agent_teams.tools.validate_artifact import validate_payload


TS = "2026-07-14T09:00:00Z"


def _sha(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _seed_vault(root: Path) -> Path:
    for folder in (
        "papers", "syntheses", "ideas", "sources", "methods", "models", "datasets",
        "protocols", "experiments",
    ):
        (root / "02-wiki" / folder).mkdir(parents=True, exist_ok=True)
    (root / "00-system").mkdir(parents=True, exist_ok=True)
    (root / "07-logs").mkdir(parents=True, exist_ok=True)
    (root / "00-system" / "index.md").write_text("---\ntype: index\nupdated: 2026-07-01\n---\n# Index\n", encoding="utf-8")
    (root / "00-system" / "hot.md").write_text("---\ntype: hot\nupdated: 2026-07-01\n---\n# Hot\n", encoding="utf-8")
    (root / "07-logs" / "log.md").write_text("---\ntype: log\nupdated: 2026-07-01\n---\n# Log\n", encoding="utf-8")
    (root / "05-registry").mkdir(parents=True, exist_ok=True)
    (root / "05-registry" / "type-registry.md").write_text(
        "| type | Folder | Purpose | Required type-specific fields | Optional fields |\n"
        "|------|--------|---------|-------------------------------|-----------------|\n"
        "| `paper` | `papers/` | External paper | `authors`, `year`, `venue`, `reading-status`, `relevance` | |\n"
        "| `synthesis` | `syntheses/` | Synthesis | `covers` | |\n"
        "| `idea` | `ideas/` | Idea | `idea-status`, `rationale` | |\n"
        "| `source` | `sources/` | Source | `source-type`, `maintained-by` | `canonical` |\n"
        "| `method` | `methods/` | Method | `category` | |\n"
        "| `model` | `models/` | Model | `family`, `native-dim` | |\n"
        "| `dataset` | `datasets/` | Dataset | `size`, `modality` | |\n"
        "| `protocol` | `protocols/` | Protocol | `protocol-type`, `protocol-version`, `applies-to` | |\n"
        "| `experiment` | `experiments/` | Experiment | `experiment-id`, `model`, `dataset`, `protocol`, `serves-rq`, `serves-contrib` | |\n",
        encoding="utf-8",
    )
    return root


def _candidate(workspace: Path, *, slug: str = "final-brief",
               crlf_source: bool = False) -> tuple[dict, Path, str]:
    source = workspace / "research_agent_teams" / "runs" / "petct-residual-correction" / "run-1" / "director-review" / "evidence.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    raw = b"# Final evidence brief\n\nThe source body survives scratch cleanup.\n"
    if crlf_source:
        raw = raw.replace(b"\n", b"\r\n")
    source.write_bytes(raw)
    candidate = {
        "admission_id": "rac-pet-final-documents-20260714",
        "slug": slug,
        "vault_type": "synthesis",
        "project": "petct-residual-correction",
        "title": "RAC-PET Final Evidence Brief",
        "status": "active",
        "confidence": "medium",
        "evidence_class": "ASSUMPTION",
        "source_ref": {
            "path": "research_agent_teams/runs/petct-residual-correction/run-1/director-review/evidence.md",
            "sha256": _sha(raw),
        },
        "metadata": {"covers": ["[[petct-residual-correction-brief]]"]},
        "domain": ["medical-imaging"],
        "tags": [],
        "related": ["[[petct-residual-correction-brief]]"],
    }
    candidates = workspace / "research_agent_teams" / "projects" / "petct-residual-correction" / "vault-admissions" / "rac-pet-final-documents-20260714"
    candidates.mkdir(parents=True, exist_ok=True)
    candidate_path = candidates / f"{slug}.document-promotion-candidate.json"
    raw_candidate = json.dumps(candidate, ensure_ascii=False, indent=2).encode("utf-8")
    candidate_path.write_bytes(raw_candidate)
    return candidate, candidate_path, _sha(raw_candidate)


def test_document_admission_requires_exact_out_of_band_authorization(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    vault = _seed_vault(tmp_path / "vault")
    candidate, candidate_path, candidate_sha = _candidate(workspace)
    monkeypatch.delenv("RAT_DOCUMENT_ADMISSION_AUTHORIZED", raising=False)

    records = run_document_admission_batch(
        [(candidate, candidate_path, candidate_sha)],
        admission_id=candidate["admission_id"],
        admission_root=candidate_path.parent,
        workspace_root=workspace,
        vault_root=vault,
        human_authorized=document_admission_is_authorized(candidate["admission_id"]),
        decided_by="director",
        decided_at=TS,
    )

    assert len(records) == 1 and records[0]["admissible"] is False
    assert validate_payload("document_promotion_record", records[0]) == []
    assert not (vault / "02-wiki" / "syntheses" / "final-brief.md").exists()


def test_document_admission_copies_full_body_and_never_emits_result_fields(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    vault = _seed_vault(tmp_path / "vault")
    candidate, candidate_path, candidate_sha = _candidate(workspace)
    monkeypatch.setenv("RAT_DOCUMENT_ADMISSION_AUTHORIZED", candidate["admission_id"])

    records = run_document_admission_batch(
        [(candidate, candidate_path, candidate_sha)],
        admission_id=candidate["admission_id"],
        admission_root=candidate_path.parent,
        workspace_root=workspace,
        vault_root=vault,
        human_authorized=document_admission_is_authorized(candidate["admission_id"]),
        decided_by="director",
        decided_at=TS,
    )

    assert len(records) == 1 and records[0]["admissible"] is True
    assert validate_payload("document_promotion_record", records[0]) == []
    page = (vault / "02-wiki" / "syntheses" / "final-brief.md").read_text(encoding="utf-8")
    assert "The source body survives scratch cleanup." in page
    assert "source-markdown-sha256:" in page
    assert "result-status:" not in page
    assert "can-cite-thesis:" not in page
    assert "[[final-brief]]" in (vault / "00-system" / "index.md").read_text(encoding="utf-8")
    assert "[[final-brief]]" in (vault / "00-system" / "hot.md").read_text(encoding="utf-8")
    assert "DOCUMENT-ADMISSION" in (vault / "07-logs" / "log.md").read_text(encoding="utf-8")
    assert verify_chain(read_events(candidate_path.parent / "admission-ledger.jsonl")) == []


def test_document_admission_normalizes_crlf_source_without_blank_line_expansion(monkeypatch, tmp_path):
    """A Windows-produced final Markdown must not double-space once wrapped by Vault frontmatter."""
    workspace = tmp_path / "workspace"
    vault = _seed_vault(tmp_path / "vault")
    candidate, candidate_path, candidate_sha = _candidate(workspace, crlf_source=True)
    monkeypatch.setenv("RAT_DOCUMENT_ADMISSION_AUTHORIZED", candidate["admission_id"])

    records = run_document_admission_batch(
        [(candidate, candidate_path, candidate_sha)],
        admission_id=candidate["admission_id"],
        admission_root=candidate_path.parent,
        workspace_root=workspace,
        vault_root=vault,
        human_authorized=True,
        decided_by="director",
        decided_at=TS,
    )

    assert records[0]["admissible"] is True
    page = (vault / "02-wiki" / "syntheses" / "final-brief.md")
    raw = page.read_bytes()
    assert b"\r\r\n" not in raw
    assert "# Final evidence brief\n\nThe source body survives scratch cleanup." in page.read_text(encoding="utf-8")


def test_document_admission_accepts_explicit_director_command_without_env(monkeypatch, tmp_path, capsys):
    """A top-level user source-command may admit a document without asking the user to run shell setup.

    This is deliberately a CLI-level director command, not a worker-mode path.  The result records the
    authorization basis so the vault migration remains auditable.
    """
    from research_agent_teams.tools import promote_gate

    workspace = tmp_path / "workspace"
    vault = _seed_vault(tmp_path / "vault")
    candidate, candidate_path, _ = _candidate(workspace)
    monkeypatch.delenv("RAT_DOCUMENT_ADMISSION_AUTHORIZED", raising=False)

    rc = promote_gate.main([
        "--document-batch", str(candidate_path.parent),
        "--admission-id", candidate["admission_id"],
        "--workspace-root", str(workspace),
        "--vault", str(vault),
        "--director-invoked",
        "--ts", TS,
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["admissible"] is True
    assert payload["records"][0]["authorization_basis"] == "explicit-director-command"
    assert (vault / "02-wiki" / "syntheses" / "final-brief.md").exists()


def test_bad_batch_preflight_is_all_or_nothing_even_for_an_otherwise_valid_candidate(monkeypatch, tmp_path):
    """R3 C5 (2026-08-07): source_ref.sha256 re-verification is gone (bad_sha is no longer a
    preflight failure mode — document_promotion.py:258-262). Path escape (kept — see
    test_document_source_cannot_escape_project_paths) still poisons preflight, and the batch-wide
    all-or-nothing gate (document_promotion.py:753-763) still rejects a same-batch candidate that
    would otherwise have been admissible on its own."""
    workspace = tmp_path / "workspace"
    vault = _seed_vault(tmp_path / "vault")
    good, good_path, good_sha = _candidate(workspace, slug="good-brief")
    escaping, escaping_path, escaping_sha = _candidate(workspace, slug="escaping-brief")
    outside = workspace / "README.md"
    outside.write_text("# not a project source", encoding="utf-8")
    escaping["source_ref"] = {"path": "README.md", "sha256": _sha(outside.read_bytes())}
    monkeypatch.setenv("RAT_DOCUMENT_ADMISSION_AUTHORIZED", good["admission_id"])

    records = run_document_admission_batch(
        [(good, good_path, good_sha), (escaping, escaping_path, escaping_sha)],
        admission_id=good["admission_id"],
        admission_root=good_path.parent,
        workspace_root=workspace,
        vault_root=vault,
        human_authorized=True,
        decided_by="director",
        decided_at=TS,
    )

    assert all(record["admissible"] is False for record in records)
    assert any(
        "outside this project's runs/workspace" in reason
        for record in records for reason in record["reasons"]
    )
    assert not (vault / "02-wiki" / "syntheses" / "good-brief.md").exists(), "batch must be all-or-nothing"
    assert not (vault / "02-wiki" / "syntheses" / "escaping-brief.md").exists()


def test_document_source_cannot_escape_project_paths(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    vault = _seed_vault(tmp_path / "vault")
    candidate, candidate_path, candidate_sha = _candidate(workspace)
    outside = workspace / "README.md"
    outside.parent.mkdir(parents=True, exist_ok=True)
    outside.write_text("# not a project source", encoding="utf-8")
    candidate["source_ref"] = {"path": "README.md", "sha256": _sha(outside.read_bytes())}
    monkeypatch.setenv("RAT_DOCUMENT_ADMISSION_AUTHORIZED", candidate["admission_id"])

    records = run_document_admission_batch(
        [(candidate, candidate_path, candidate_sha)],
        admission_id=candidate["admission_id"],
        admission_root=candidate_path.parent,
        workspace_root=workspace,
        vault_root=vault,
        human_authorized=True,
        decided_by="director",
        decided_at=TS,
    )

    assert records[0]["admissible"] is False
    assert any("outside this project's runs/workspace" in reason for reason in records[0]["reasons"])


def test_current_route_admission_turns_verified_legacy_canonical_page_into_pointer(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    vault = _seed_vault(tmp_path / "vault")
    legacy = vault / "02-wiki" / "sources" / "petct-residual-correction-brief.md"
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text(
        "---\n"
        "title: Legacy PET/CT brief\n"
        "type: source\n"
        "status: active\n"
        "project: petct-residual-correction\n"
        "canonical: true\n"
        "---\n\n"
        "# Legacy project brief\n",
        encoding="utf-8",
    )
    candidate, candidate_path, candidate_sha = _candidate(workspace, slug="rac-pet-research-master")
    candidate["canonical_redirects"] = ["petct-residual-correction-brief"]
    monkeypatch.setenv("RAT_DOCUMENT_ADMISSION_AUTHORIZED", candidate["admission_id"])

    records = run_document_admission_batch(
        [(candidate, candidate_path, candidate_sha)],
        admission_id=candidate["admission_id"],
        admission_root=candidate_path.parent,
        workspace_root=workspace,
        vault_root=vault,
        human_authorized=True,
        decided_by="director",
        decided_at=TS,
    )

    assert records[0]["admissible"] is True
    assert records[0]["canonical_redirects"] == ["petct-residual-correction-brief"]
    redirected = legacy.read_text(encoding="utf-8")
    assert "status: deprecated" in redirected
    assert "canonical: false" in redirected
    assert "[[rac-pet-research-master]]" in redirected
    assert "current-route-supersession: rac-pet-research-master" in redirected
    assert "CONTRACT-EDIT [[petct-residual-correction-brief]]" in (vault / "07-logs" / "log.md").read_text(encoding="utf-8")


def test_document_admission_accepts_registered_non_result_page_types(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    vault = _seed_vault(tmp_path / "vault")
    candidate, candidate_path, _candidate_sha = _candidate(workspace, slug="rac-pet-project-index")
    candidate.update({
        "vault_type": "source",
        "title": "RAC-PET Project Index",
        "evidence_class": "VAULT-CITE",
        "metadata": {"source-type": "readme", "maintained-by": "both", "canonical": True},
    })
    raw_candidate = json.dumps(candidate, ensure_ascii=False, indent=2).encode("utf-8")
    candidate_path.write_bytes(raw_candidate)
    candidate_sha = _sha(raw_candidate)
    monkeypatch.setenv("RAT_DOCUMENT_ADMISSION_AUTHORIZED", candidate["admission_id"])

    records = run_document_admission_batch(
        [(candidate, candidate_path, candidate_sha)],
        admission_id=candidate["admission_id"],
        admission_root=candidate_path.parent,
        workspace_root=workspace,
        vault_root=vault,
        human_authorized=True,
        decided_by="director",
        decided_at=TS,
    )

    assert records[0]["admissible"] is True
    assert records[0]["document_type"] == "source"
    page = (vault / "02-wiki" / "sources" / "rac-pet-project-index.md").read_text(encoding="utf-8")
    assert "type: \"source\"" in page
    assert "canonical: true" in page
    assert "result-status:" not in page


def test_document_admission_deprecates_same_project_pages_without_deleting_history(monkeypatch, tmp_path):
    workspace = tmp_path / "workspace"
    vault = _seed_vault(tmp_path / "vault")
    old_master = vault / "02-wiki" / "syntheses" / "autopet-v-structured-intent-research-master.md"
    old_master.write_text(
        "---\ntitle: Old master\ntype: synthesis\nstatus: active\nupdated: 2026-07-01\n"
        "project: petct-residual-correction\n---\n\n# Old master\n\nHistorical scientific body.\n",
        encoding="utf-8",
    )
    old_idea = vault / "02-wiki" / "ideas" / "idea-3-clicks-to-text-recovery-head.md"
    old_idea.write_text(
        "---\ntitle: Old idea\ntype: idea\nstatus: active\nupdated: 2026-07-01\n"
        "project: petct-residual-correction\nidea-status: greenlit\n---\n\n# Old idea\n\nHistorical idea body.\n",
        encoding="utf-8",
    )
    candidate, candidate_path, _candidate_sha = _candidate(workspace, slug="rac-pet-complete-research-dossier")
    candidate["supersede_pages"] = [
        {"vault_type": "synthesis", "slug": "autopet-v-structured-intent-research-master"},
        {"vault_type": "idea", "slug": "idea-3-clicks-to-text-recovery-head"},
    ]
    raw_candidate = json.dumps(candidate, ensure_ascii=False, indent=2).encode("utf-8")
    candidate_path.write_bytes(raw_candidate)
    candidate_sha = _sha(raw_candidate)
    monkeypatch.setenv("RAT_DOCUMENT_ADMISSION_AUTHORIZED", candidate["admission_id"])

    records = run_document_admission_batch(
        [(candidate, candidate_path, candidate_sha)],
        admission_id=candidate["admission_id"],
        admission_root=candidate_path.parent,
        workspace_root=workspace,
        vault_root=vault,
        human_authorized=True,
        decided_by="director",
        decided_at=TS,
    )

    assert records[0]["admissible"] is True
    assert records[0]["superseded_pages"] == [
        "synthesis/autopet-v-structured-intent-research-master",
        "idea/idea-3-clicks-to-text-recovery-head",
    ]
    master_text = old_master.read_text(encoding="utf-8")
    idea_text = old_idea.read_text(encoding="utf-8")
    assert "status: deprecated" in master_text
    assert "Historical scientific body." in master_text
    assert "[[rac-pet-complete-research-dossier]]" in master_text
    assert "status: deprecated" in idea_text
    assert "idea-status: parked" in idea_text
    assert "Historical idea body." in idea_text
    assert "CONTRACT-EDIT [[autopet-v-structured-intent-research-master]], [[idea-3-clicks-to-text-recovery-head]]" in (
        vault / "07-logs" / "log.md"
    ).read_text(encoding="utf-8")


def test_document_candidate_discovery_ignores_prior_admission_records(tmp_path):
    batch = tmp_path / "batch"
    batch.mkdir()
    candidate = batch / "final-brief.document-promotion-candidate.json"
    record = batch / "document-promotion-record-final-brief.document-promotion-candidate.json"
    candidate.write_text("{}", encoding="utf-8")
    record.write_text("{}", encoding="utf-8")

    assert document_candidate_paths(batch) == [candidate]
