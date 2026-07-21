"""Adversarial tests for the shared manuscript trust boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import quote_plus

import pytest

from research_agent_teams.tools import manuscript_security
from research_agent_teams.tools.manuscript_security import (
    ManuscriptExecutionViolation,
    ManuscriptPathViolation,
    ManuscriptSecretViolation,
    ManuscriptTexViolation,
    scan_persisted_text,
    validate_execution_claim,
    validate_run_owned_path,
    validate_tex_sources,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _auditable_fixture_result() -> dict:
    raw_bytes = "fixture-result:v1|accuracy=0.81"
    receipt_bytes = "fixture-receipt:v1|executor=deterministic|exit=0"
    raw_sha = hashlib.sha256(raw_bytes.encode("utf-8")).hexdigest()
    return {
        "status": "FROZEN",
        "synthetic_fixture": True,
        "raw_source": {"canonical_bytes": raw_bytes, "sha256": raw_sha},
        "executor_receipt": {
            "executor_kind": "DETERMINISTIC_FIXTURE_NON_LLM",
            "exit_code": 0,
            "raw_source_sha256": raw_sha,
            "receipt_canonical_bytes": receipt_bytes,
            "receipt_sha256": hashlib.sha256(receipt_bytes.encode("utf-8")).hexdigest(),
            "fixture_only": True,
        },
        "admissibility": {
            "observed_evidence": True,
            "plan_only": False,
            "script_only": False,
            "metadata_only": False,
            "real_research_execution": False,
        },
    }


def test_run_owned_regular_unicode_and_ascii_space_paths_are_portable(tmp_path):
    run_root = tmp_path / "runs" / "r1"
    existing = run_root / "论文 draft" / "main file.tex"
    existing.parent.mkdir(parents=True)
    existing.write_text("safe", encoding="utf-8")

    existing_result = validate_run_owned_path(existing, run_root=run_root)
    future_result = validate_run_owned_path(
        "输出 figures/plot one.pdf",
        run_root=run_root,
        owned_output_roots=(run_root / "输出 figures",),
    )

    assert existing_result["relative_path"] == "论文 draft/main file.tex"
    assert existing_result["existing_kind"] == "file"
    assert future_result["relative_path"] == "输出 figures/plot one.pdf"
    assert future_result["existing_kind"] == "missing"
    json.dumps(existing_result, ensure_ascii=False)
    json.dumps(future_result, ensure_ascii=False)


@pytest.mark.parametrize(
    "candidate",
    [
        "../outside.tex",
        "sections/../../outside.tex",
        "C:\\outside\\paper.tex",
        "\\\\server\\share\\paper.tex",
    ],
    ids=["parent", "nested-parent", "windows-drive", "windows-unc"],
)
def test_path_traversal_and_cross_platform_absolute_escapes_are_rejected(tmp_path, candidate):
    run_root = tmp_path / "runs" / "r1"
    run_root.mkdir(parents=True)

    with pytest.raises(ManuscriptPathViolation) as caught:
        validate_run_owned_path(candidate, run_root=run_root)

    assert caught.value.code in {"PATH_TRAVERSAL", "PATH_OUTSIDE_RUN"}
    json.dumps(caught.value.findings)


def test_native_absolute_external_and_unowned_output_roots_are_rejected(tmp_path):
    run_root = tmp_path / "runs" / "r1"
    owned = run_root / "manuscript"
    owned.mkdir(parents=True)

    with pytest.raises(ManuscriptPathViolation, match="PATH_OUTSIDE_RUN"):
        validate_run_owned_path(tmp_path / "outside" / "main.tex", run_root=run_root)
    with pytest.raises(ManuscriptPathViolation, match="UNOWNED_OUTPUT_ROOT"):
        validate_run_owned_path(
            run_root / "logs" / "main.tex",
            run_root=run_root,
            owned_output_roots=(owned,),
        )


def test_symlink_escape_is_rejected_without_touching_target(tmp_path, monkeypatch):
    run_root = tmp_path / "runs" / "r1"
    outside = tmp_path / "outside"
    run_root.mkdir(parents=True)
    outside.mkdir()
    target = outside / "untouched.txt"
    target.write_text("director-owned", encoding="utf-8")
    link = run_root / "linked"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        link.mkdir()
        monkeypatch.setattr(
            manuscript_security,
            "_is_reparse_point",
            lambda path, _stat: path == link,
        )

    before = _sha256(target)
    with pytest.raises(ManuscriptPathViolation) as caught:
        validate_run_owned_path(link / "new.txt", run_root=run_root)

    assert caught.value.code in {"SYMLINK_PATH", "REPARSE_PATH"}
    assert _sha256(target) == before


def test_windows_reparse_simulation_rejects_future_output(tmp_path, monkeypatch):
    run_root = tmp_path / "runs" / "r1"
    junction = run_root / "junction"
    junction.mkdir(parents=True)
    monkeypatch.setattr(
        manuscript_security,
        "_is_reparse_point",
        lambda path, _stat: path == junction,
    )

    with pytest.raises(ManuscriptPathViolation, match="REPARSE_PATH"):
        validate_run_owned_path(junction / "future" / "paper.tex", run_root=run_root)


def test_hardlink_output_alias_is_rejected_without_touching_director_asset(tmp_path):
    run_root = tmp_path / "runs" / "r1"
    director_root = tmp_path / "director-assets"
    run_root.mkdir(parents=True)
    director_root.mkdir()
    asset = director_root / "source.txt"
    asset.write_text("director-owned", encoding="utf-8")
    alias = run_root / "output.txt"
    try:
        os.link(asset, alias)
    except OSError as exc:
        pytest.skip(f"hard links unavailable on this filesystem: {exc}")
    before = _sha256(asset)

    with pytest.raises(ManuscriptPathViolation, match="HARDLINK_PATH"):
        validate_run_owned_path(
            alias,
            run_root=run_root,
            purpose="write",
            director_asset_roots=(director_root,),
        )

    assert _sha256(asset) == before


@pytest.mark.parametrize(
    "candidate",
    ["figures/plot\u00a0one.pdf", "figures/trailing-space .pdf ", "figures/trailing-dot."],
    ids=["nbsp", "trailing-space", "trailing-dot"],
)
def test_unicode_or_platform_ambiguous_spaces_are_not_silently_normalized(tmp_path, candidate):
    run_root = tmp_path / "runs" / "r1"
    run_root.mkdir(parents=True)

    with pytest.raises(ManuscriptPathViolation, match="AMBIGUOUS_PATH"):
        validate_run_owned_path(candidate, run_root=run_root)


def test_director_asset_is_read_hashable_but_never_an_output(tmp_path):
    run_root = tmp_path / "runs" / "r1"
    director_root = tmp_path / "director-assets"
    run_root.mkdir(parents=True)
    director_root.mkdir()
    asset = director_root / "source figure.svg"
    asset.write_text("<svg>director</svg>", encoding="utf-8")
    before = _sha256(asset)

    read_result = validate_run_owned_path(
        asset,
        run_root=run_root,
        purpose="read",
        director_asset_roots=(director_root,),
        expected_sha256=before,
    )
    with pytest.raises(ManuscriptPathViolation, match="DIRECTOR_ASSET_IMMUTABLE"):
        validate_run_owned_path(
            asset,
            run_root=run_root,
            purpose="write",
            director_asset_roots=(director_root,),
        )

    assert read_result["owner"] == "director"
    assert read_result["sha256"] == before
    assert _sha256(asset) == before


def test_vault_write_and_scope_permission_violation_leave_external_files_unchanged(tmp_path):
    runs_root = tmp_path / "runs"
    run_root = runs_root / "r1"
    allowed = run_root / "evidence" / "DESIGN"
    vault = tmp_path / "vault"
    other_stage = run_root / "evidence" / "EXECUTE" / "note.md"
    allowed.mkdir(parents=True)
    vault.mkdir()
    marker = vault / "inventory.txt"
    marker.write_text("unchanged", encoding="utf-8")
    before = _sha256(marker)
    scope = {
        "run_root": str(runs_root),
        "run_id": "r1",
        "stage": "DESIGN",
        "vault_root": str(vault),
    }

    accepted = validate_run_owned_path(
        allowed / "note.md", run_root=run_root, scope=scope, vault_root=vault
    )
    with pytest.raises(ManuscriptPathViolation, match="VAULT_WRITE"):
        validate_run_owned_path(
            vault / "02-wiki" / "forged.md",
            run_root=run_root,
            vault_root=vault,
        )
    with pytest.raises(ManuscriptPathViolation, match="SCOPE_DENIED"):
        validate_run_owned_path(other_stage, run_root=run_root, scope=scope, vault_root=vault)

    assert accepted["scope_checked"] is True
    assert _sha256(marker) == before


def test_scope_validation_never_falls_back_to_environment(tmp_path, monkeypatch):
    from research_agent_teams.tools import scope_guard

    runs_root = tmp_path / "runs"
    run_root = runs_root / "r1"
    target = run_root / "evidence" / "DESIGN" / "note.md"
    target.parent.mkdir(parents=True)
    monkeypatch.setattr(
        scope_guard,
        "discover_vault_root",
        lambda: pytest.fail("vault environment discovery"),
    )
    monkeypatch.setattr(
        scope_guard,
        "discover_projects_root",
        lambda: pytest.fail("projects environment discovery"),
    )

    result = validate_run_owned_path(
        target,
        run_root=run_root,
        scope={
            "run_root": str(runs_root),
            "run_id": "r1",
            "stage": "DESIGN",
            "vault_root": None,
            "projects_root": "",
        },
    )

    assert result["scope_checked"] is True


def test_safe_run_relative_tex_directives_pass_with_spaces_and_unicode(tmp_path):
    run_root = tmp_path / "runs" / "r1"
    source_root = run_root / "manuscript source"
    source_root.mkdir(parents=True)
    sources = {
        "main.tex": (
            "\\documentclass{article}\n"
            "\\input{sections/方法}\n"
            "\\includegraphics[width=0.8\\linewidth]{figures/plot one.pdf}\n"
            "\\bibliography{refs}\n"
        ),
        "sections/方法.tex": "Ordinary content.\n",
    }

    result = validate_tex_sources(
        sources, run_root=run_root, source_root=source_root
    )

    assert result["ok"] is True
    assert result["files_checked"] == 2
    assert result["directives_checked"] == 3
    json.dumps(result, ensure_ascii=False)


@pytest.mark.parametrize(
    ("source", "code"),
    [
        (r"\immediate\write18{python exploit.py}", "TEX_EXECUTION_DIRECTIVE"),
        (r"\openout1=outside.txt", "TEX_WRITE_DIRECTIVE"),
        (r"\input{../../outside.tex}", "TEX_EXTERNAL_PATH"),
        (r"\include{/etc/passwd}", "TEX_EXTERNAL_PATH"),
        (r"\includegraphics{C:\\secret\\figure.pdf}", "TEX_EXTERNAL_PATH"),
        (r"\bibliography{https://example.invalid/refs}", "TEX_EXTERNAL_PATH"),
        (r"\directlua{os.execute('whoami')}", "TEX_EXECUTION_DIRECTIVE"),
        (r"\def\evil{\csname write18\endcsname}", "TEX_DYNAMIC_COMMAND"),
        (r"\^^69nput{/etc/passwd}", "TEX_OBFUSCATED_COMMAND"),
        (r"\InputIfFileExists{/etc/passwd}{}{}", "TEX_EXTERNAL_PATH"),
        (r"\RequirePackage{minted}", "TEX_EXECUTION_DIRECTIVE"),
        (r"\inputminted{python}{outside.py}", "TEX_EXECUTION_DIRECTIVE"),
        (r"\begin{filecontents}{outside.txt}", "TEX_WRITE_DIRECTIVE"),
    ],
    ids=[
        "write18", "openout", "parent-input", "absolute-include",
        "windows-graphics", "url-bibliography", "directlua", "dynamic-command",
        "caret-obfuscation", "conditional-input", "minted-package", "input-minted",
        "filecontents-write",
    ],
)
def test_unsafe_tex_directives_and_external_paths_fail_closed(tmp_path, source, code):
    run_root = tmp_path / "runs" / "r1"
    source_root = run_root / "manuscript"
    source_root.mkdir(parents=True)

    with pytest.raises(ManuscriptTexViolation) as caught:
        validate_tex_sources(
            {"main.tex": source}, run_root=run_root, source_root=source_root
        )

    assert caught.value.code == code
    json.dumps(caught.value.findings)


@pytest.mark.parametrize(
    "channel",
    ["url", "error", "tex", "bibtex", "build_metadata", "build_log", "markdown"],
)
def test_caller_supplied_secret_sentinel_blocks_every_durable_channel(channel):
    secret = "sentinel-secret-value-001"

    with pytest.raises(ManuscriptSecretViolation) as caught:
        scan_persisted_text(
            channel,
            f"durable {channel} text contains {secret}",
            sentinels={"test_credential": secret},
        )

    assert caught.value.code == "SECRET_LEAKAGE"
    assert secret not in str(caught.value)
    assert caught.value.findings == [{
        "code": "SECRET_SENTINEL",
        "channel": channel,
        "sentinel": "test_credential",
        "line": 1,
    }]
    json.dumps(caught.value.findings)


def test_secret_scanner_uses_only_caller_supplied_text_and_patterns(monkeypatch):
    monkeypatch.setattr(Path, "read_text", lambda *_args, **_kwargs: pytest.fail("secret file read"))

    safe = scan_persisted_text(
        "markdown",
        "No sensitive material here.",
        sentinels={"named_secret": "not-present"},
        patterns={"token_shape": r"token-[0-9]{8}"},
    )

    assert safe == {
        "ok": True,
        "policy": "persisted_text",
        "channel": "markdown",
        "findings": [],
    }


def test_secret_scanner_decodes_lowercase_percent_and_form_url_encodings():
    secret = "key/value with space"
    encoded = quote_plus(secret, safe="").lower()

    with pytest.raises(ManuscriptSecretViolation) as caught:
        scan_persisted_text("url", f"https://example.invalid/?token={encoded}", sentinels={"key": secret})

    assert caught.value.findings[0]["sentinel"] == "key"
    assert secret not in str(caught.value)


def test_frozen_non_llm_receipt_allows_supported_execution_prose():
    facts = _auditable_fixture_result()
    result = validate_execution_claim(
        "We executed the registered evaluation and observed accuracy 0.81.",
        facts,
    )

    assert result["ok"] is True
    assert result["execution_claim"] is True
    assert result["receipt_sha256"] == facts["executor_receipt"]["receipt_sha256"]
    json.dumps(result)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda facts: facts.update(status="PROVISIONAL"), "RESULT_NOT_FROZEN"),
        (lambda facts: facts["admissibility"].update(script_only=True), "SCRIPTS_ONLY"),
        (lambda facts: facts["admissibility"].update(plan_only=True), "PLAN_ONLY"),
        (
            lambda facts: facts["executor_receipt"].update(executor_kind="LLM_WORKER"),
            "MODEL_AUTHORED_RECEIPT",
        ),
        (
            lambda facts: facts["executor_receipt"].update(raw_source_sha256="c" * 64),
            "RECEIPT_SOURCE_MISMATCH",
        ),
        (
            lambda facts: facts["admissibility"].update(real_research_execution=False),
            "NOT_REAL_EXECUTION",
        ),
    ],
    ids=["not-frozen", "scripts-only", "plan-only", "model-receipt", "hash-mismatch", "not-real"],
)
def test_false_or_unsupported_execution_prose_hard_blocks(mutate, code):
    facts = _auditable_fixture_result()
    mutate(facts)

    with pytest.raises(ManuscriptExecutionViolation) as caught:
        validate_execution_claim("We ran a real GPU experiment and achieved 0.91.", facts)

    assert caught.value.code == code
    json.dumps(caught.value.findings)


def test_mixed_negative_and_positive_execution_language_still_requires_evidence():
    with pytest.raises(ManuscriptExecutionViolation, match="UNSUPPORTED_EXECUTION_CLAIM"):
        validate_execution_claim(
            "No experiment was run in the pilot; we achieved 0.99 on a real GPU experiment.",
            {},
        )


def test_plain_self_asserted_real_receipt_requires_independent_reverification():
    facts = _auditable_fixture_result()
    facts["synthetic_fixture"] = False
    facts["executor_receipt"].update(
        executor_kind="SIGNED_EXTERNAL_EXECUTOR",
        fixture_only=False,
    )
    facts["admissibility"]["real_research_execution"] = True

    with pytest.raises(ManuscriptExecutionViolation, match="EXECUTION_REVERIFY_REQUIRED"):
        validate_execution_claim("We executed the registered evaluation.", facts)


def test_explicit_scripts_only_non_claim_does_not_invent_execution():
    result = validate_execution_claim(
        "Scripts only: no experiment was run and no result is claimed.",
        {},
    )

    assert result == {
        "ok": True,
        "policy": "execution_truth",
        "execution_claim": False,
        "findings": [],
    }
