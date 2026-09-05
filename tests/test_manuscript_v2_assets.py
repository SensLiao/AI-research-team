"""Actual-byte integration coverage for v2 conceptual and quantitative assets."""
from __future__ import annotations

import copy
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from research_agent_teams.operate.modes import manuscript_authoring as authoring
from research_agent_teams.tools.manuscript_contract import canonical_contract_hash
from research_agent_teams.tools.manuscript_integrator import ManuscriptIntegrationError, materialize_source_tree
from research_agent_teams.tools.validate_artifact import validate_payload
from .test_manuscript_integration import (
    EVIDENCE_REF, RECEIPT_REF, RESULT_REF, SECTIONS, _bundle, _canonical_hash,
    _file_hash, _integrate, _rewrite_bundle, _setup_run, _stamp, _write_json,
)


def _refresh_bundles(root: Path, contract: dict, refs: list[str]) -> None:
    contract["manuscript_snapshot_sha256"] = canonical_contract_hash(contract)
    receipt = json.loads((root / RECEIPT_REF).read_text(encoding="utf-8"))
    for row, ref, authorization in zip(SECTIONS, refs, receipt["authorizations"]):
        bundle = _bundle(contract, row, _canonical_hash(authorization))
        for item in bundle["input_refs"]:
            if item["ref"] == EVIDENCE_REF:
                item["sha256"] = contract["evidence_refs"][0]["sha256"]
        _write_json(root / ref, _stamp(bundle, "content_hash"))


def _v2_case(tmp_path: Path, *, quantitative: bool = False, pdf: bool = False):
    root, contract, refs = _setup_run(tmp_path)
    evidence = root / EVIDENCE_REF
    _write_json(evidence, {"proposition": "A precedes B; no effect size is claimed."})
    evidence_sha = _file_hash(evidence)
    contract["evidence_refs"][0]["sha256"] = evidence_sha
    contract["bibliography"]["entries"][0]["source_sha256"] = evidence_sha
    for row in contract["source_hashes"]:
        if row["ref"] == EVIDENCE_REF:
            row["sha256"] = evidence_sha
    for dependency in contract["dependency_slices"]:
        dependency["input_refs"][0]["sha256"] = evidence_sha
        _stamp(dependency, "slice_sha256")
    suffix = ".pdf" if pdf else ".png"
    contract["asset_plan"] = [{
        "asset_id": "fig-process", "kind": "FIGURE", "label": "fig:process",
        "planned_path": "figures/process" + suffix, "source_refs": [EVIDENCE_REF],
        "result_refs": [RESULT_REF] if quantitative else [],
    }]
    _refresh_bundles(root, contract, refs)
    source_inputs = [{"ref": EVIDENCE_REF, "sha256": evidence_sha, "kind": "EXTERNAL_EVIDENCE", "immutable": True}]
    if quantitative:
        source_inputs.append({"ref": RESULT_REF, "sha256": contract["result_refs"][0]["sha256"], "kind": "FROZEN_RESULT", "immutable": True})
    svg = b'<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60" viewBox="0 0 120 60"><title>Process</title><text x="10" y="30" font-size="12">A precedes B</text></svg>'
    buffer = io.BytesIO()
    Image.new("RGB", (120, 60), "white").save(buffer, format="PNG")
    bodies = {"draft/figure-candidates/process.svg": svg, "draft/figure-candidates/process.png": buffer.getvalue()}
    if pdf:
        fitz = pytest.importorskip("fitz")
        document = fitz.open()
        document.new_page(width=120, height=60).insert_text((10, 30), "A precedes B")
        bodies["draft/figure-candidates/process.pdf"] = document.tobytes()
        document.close()
    outputs = []
    formats = {".svg": ("SVG", "image/svg+xml"), ".png": ("PNG", "image/png"), ".pdf": ("PDF", "application/pdf")}
    for ref, body in bodies.items():
        path = root / ref
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        format_name, media_type = formats[path.suffix]
        outputs.append({"path": ref, "format": format_name, "media_type": media_type, "sha256": _file_hash(path), "byte_size": len(body), "owner_run_id": root.name, "run_owned": True, "overwrite_policy": "CREATE_NEW"})
    asset = {
        "asset_id": "fig-process", "label": "fig:process",
        "semantic_type": "QUANTITATIVE_PLOT" if quantitative else "CONCEPTUAL_SCHEMATIC",
        "render_template": "EVIDENCE_HEATMAP" if quantitative else "HIDDEN_ORACLE_PATHWAY",
        "caption": {"text": "Frozen process illustration.", "owner_role": "manuscript-figure-table-engineer"},
        "accessibility_text": "A precedes B without a quantitative causal claim.",
        "claim_refs": ["CLM-INTRO"], "source_inputs": source_inputs, "outputs": outputs,
        "permission": {"status": "OWNED", "license_ref": "original-project-figure", "public_release_allowed": True},
    }
    manifest = {
        "schema_version": "2.0.0", "run_id": root.name,
        "manuscript_sha256": contract["manuscript_snapshot_sha256"],
        "asset_plan_sha256": _canonical_hash(contract["asset_plan"]), "assets": [asset],
        "plan_closure": {
            "status": "CLOSED", "planned_asset_ids": ["fig-process"], "rendered_asset_ids": ["fig-process"],
            "planned_labels": ["fig:process"], "rendered_labels": ["fig:process"],
            "planned_output_refs": list(bodies), "rendered_output_refs": list(bodies),
        },
    }
    if quantitative:
        asset["numeric_cells"] = [{"result_ref": RESULT_REF, "cell_ref": "metrics.score", "value": 0.8125, "units": "fraction", "uncertainty": {"kind": "NOT_APPLICABLE", "value": 0, "units": "fraction"}}]
        renderer_ref = "research_agent_teams/tools/review_asset_renderer.py"
        receipt = {
            "renderer_ref": renderer_ref, "renderer_sha256": _file_hash(Path(__file__).resolve().parents[2] / renderer_ref),
            "shell": False, "argv": ["fixture-adapter-receipt"], "fixed_parameters": {},
            "parameters_sha256": _canonical_hash({}), "source_set_sha256": _canonical_hash(source_inputs),
            "output_set_sha256": _canonical_hash(outputs),
        }
        asset["render_receipt"] = _stamp(receipt, "receipt_sha256")
        manifest["render_environment"] = _stamp({"python": "fixture", "pillow": "fixture", "pymupdf": "fixture", "font_set_sha256": "a" * 64}, "environment_sha256")
    _stamp(asset, "asset_record_sha256")
    _stamp(manifest, "manifest_sha256")
    assert validate_payload("manuscript_asset_manifest", manifest) == []

    def add_figure(bundle):
        bundle["draft_latex"] += (
            "\\begin{figure}\\centering\\includegraphics{figures/process" + suffix + "}"
            "\\caption{Frozen process illustration.}\\label{fig:process}\\end{figure}\n"
        )
        bundle["labels"].append("fig:process")
        bundle["asset_refs"].append("fig-process")
    _rewrite_bundle(root, refs[0], add_figure)
    return root, contract, refs, manifest, bodies


def test_v2_conceptual_bytes_integrate_without_fabricated_numbers(tmp_path):
    root, contract, refs, manifest, bodies = _v2_case(tmp_path)
    before = copy.deepcopy(manifest)
    candidate = _integrate(root, contract, refs, asset_manifest=manifest, result_receipt_verifier=None)
    source = materialize_source_tree(candidate, run_root=root)
    assert candidate["asset_manifest"] == before == manifest
    assert "numeric_cells" not in manifest["assets"][0]
    assert "result_refs" not in manifest["assets"][0]
    for ref, data in bodies.items():
        assert (source / "figures" / Path(ref).name).read_bytes() == data
    metadata = json.loads((source / "build/integration-metadata.json").read_text())
    assert metadata["asset_copies"][0]["source"] == "draft/figure-candidates/process.svg"
    assert metadata["asset_copies"][0]["destination"] == "figures/process.svg"


def test_v2_pdf_is_the_explicit_planned_primary_output(tmp_path):
    root, contract, refs, manifest, bodies = _v2_case(tmp_path, pdf=True)
    candidate = _integrate(root, contract, refs, asset_manifest=manifest)
    assert candidate["files"]["figures/process.pdf"] == bodies["draft/figure-candidates/process.pdf"]
    assert b"includegraphics{figures/process.pdf}" in candidate["files"]["sections/introduction.tex"]


def test_actual_scientific_figure_receipt_enters_canonical_source(tmp_path):
    from research_agent_teams.tools.scientific_figure import bundle_manifest, render_figure

    root, contract, refs, seed, _ = _v2_case(tmp_path, pdf=True)
    asset = seed["assets"][0]
    spec = {key: copy.deepcopy(asset[key]) for key in ("asset_id", "label", "caption", "accessibility_text", "claim_refs", "source_inputs")}
    svg = asset["outputs"][0]
    spec.update(
        run_id=root.name, purpose="Explain the frozen proposition.",
        svg_source={"ref": svg["path"], "sha256": svg["sha256"]},
        output_stem="draft/operated-figures/process", width_mm=60, dpi=600, min_font_pt=8,
    )
    rendered = render_figure(root, spec)
    manifest = bundle_manifest(root.name, contract["manuscript_snapshot_sha256"], {"assets": [spec]}, [rendered])
    candidate = _integrate(root, contract, refs, asset_manifest=manifest, generated_command_verifier=None)
    assert candidate["asset_manifest"] == manifest
    assert candidate["files"]["figures/process.pdf"].startswith(b"%PDF-")
    assert rendered["checks"]["effective_dpi"] >= 599
    (root / svg["path"]).write_bytes(b"changed source SVG")
    with pytest.raises(ManuscriptIntegrationError, match="GENERATED_RECEIPT_UNVERIFIED"):
        _integrate(root, contract, refs, asset_manifest=manifest)


@pytest.mark.parametrize("mutation", ["source_bytes", "auxiliary_svg_bytes", "missing_png", "permission", "output_owner", "unknown_claim", "path_escape", "source_kind", "closure", "format"])
def test_v2_invalid_provenance_or_output_fails_before_source_publish(tmp_path, mutation):
    root, contract, refs, manifest, _ = _v2_case(tmp_path)
    asset = manifest["assets"][0]
    if mutation == "source_bytes":
        (root / EVIDENCE_REF).write_text("changed evidence", encoding="utf-8")
    elif mutation == "auxiliary_svg_bytes":
        (root / asset["outputs"][0]["path"]).write_bytes(b"changed editable source")
    elif mutation == "missing_png":
        (root / asset["outputs"][1]["path"]).unlink()
    elif mutation == "permission":
        asset["permission"].update(status="PENDING", public_release_allowed=False)
    elif mutation == "output_owner":
        asset["outputs"][0]["owner_run_id"] = "another-run"
    elif mutation == "unknown_claim":
        asset["claim_refs"] = ["CLM-NOT-FROZEN"]
    elif mutation == "path_escape":
        asset["outputs"][0]["path"] = "../escaped.svg"
    elif mutation == "source_kind":
        asset["source_inputs"][0]["kind"] = "FROZEN_RESULT"
    elif mutation == "closure":
        manifest["plan_closure"]["planned_asset_ids"] = ["another-asset"]
    elif mutation == "format":
        asset["outputs"][0].update(format="PNG", media_type="image/png")
    _stamp(asset, "asset_record_sha256")
    _stamp(manifest, "manifest_sha256")
    with pytest.raises(ManuscriptIntegrationError):
        _integrate(root, contract, refs, asset_manifest=manifest)
    assert not (root / "source").exists()


def test_v2_quantitative_assets_require_result_and_render_authority(tmp_path):
    root, contract, refs, manifest, _ = _v2_case(tmp_path, quantitative=True)
    with pytest.raises(ManuscriptIntegrationError, match="GENERATED_RECEIPT_UNVERIFIED"):
        _integrate(root, contract, refs, asset_manifest=manifest, generated_command_verifier=None)
    with pytest.raises(ManuscriptIntegrationError, match="RESULT_RECEIPT_UNVERIFIED"):
        _integrate(root, contract, refs, asset_manifest=manifest, result_receipt_verifier=None)
    assert _integrate(root, contract, refs, asset_manifest=manifest)["asset_manifest"] == manifest


def test_authoring_preserves_v2_and_derives_realized_output_facts(tmp_path):
    root, contract, refs, manifest, _ = _v2_case(tmp_path)
    normalized = authoring._normalize_asset_manifest_for_integration(root, manifest)
    assert normalized == manifest
    assert normalized is not manifest
    assert authoring._manifest_asset_sources(manifest) == {"fig-process": "draft/figure-candidates/process.png"}
    candidate = _integrate(root, contract, refs, asset_manifest=normalized)
    facts = authoring._derive_manuscript_audit_facts(
        contract=contract, bundle_payloads={}, claim_map={"mappings": []},
        integration=candidate["integration"], request={}, asset_manifest=normalized,
    )
    assert facts["assets"][0]["path"] == "figures/process.png"
    assert facts["assets"][0]["result_refs"] == []


_SAFE_TEMPLATE = r"""\documentclass[10pt]{report}
\usepackage{graphicx}
\title{@@MANUSCRIPT_TITLE@@}
\author{Anonymous authors}
\begin{document}
\maketitle
@@MANUSCRIPT_SECTIONS@@
\bibliographystyle{plain}
\bibliography{@@MANUSCRIPT_BIBLIOGRAPHY@@}
\end{document}
"""


def _template_case(tmp_path: Path, template: str = _SAFE_TEMPLATE):
    root, contract, refs = _setup_run(tmp_path)
    template_ref = "inbox/templates/frozen-skeleton.tex"
    path = root / template_ref
    path.parent.mkdir(parents=True)
    path.write_text(template, encoding="utf-8")
    contract["venue_profile"].update(template_ref=template_ref, template_sha256=_file_hash(path))
    contract["source_hashes"].append({"ref": template_ref, "sha256": _file_hash(path), "kind": "TEMPLATE"})
    _refresh_bundles(root, contract, refs)
    venue_slice = {
        "contract_version": "1.0", "venue_profile_slice_id": "venue-fixture",
        "worker_role": "manuscript-venue-corpus-scout",
        "authorization_receipt": {"ref": "inbox/scout-authorization.json", "sha256": "a" * 64, "worker_role": "manuscript-venue-corpus-scout"},
        "manuscript_snapshot_sha256": contract["manuscript_snapshot_sha256"],
        "local_literature_coverage_ref": "evidence/DISCOVER/local-literature-coverage.artifact.json",
        "local_literature_coverage_sha256": "b" * 64,
        "venue_profile": copy.deepcopy(contract["venue_profile"]),
    }
    _stamp(venue_slice, "venue_profile_slice_sha256")
    return root, contract, refs, venue_slice, path


def test_local_frozen_template_drives_class_and_reference_style(tmp_path):
    root, contract, refs, venue_slice, template_path = _template_case(tmp_path)
    original = template_path.read_bytes()
    candidate = _integrate(root, contract, refs, venue_profile_slice=venue_slice)
    main = candidate["files"]["main.tex"].decode("utf-8")
    assert r"\documentclass[10pt]{report}" in main
    assert r"\bibliographystyle{plain}" in main
    assert r"\bibliography{refs}" in main
    assert r"\input{sections/introduction.tex}" in main
    assert "@@MANUSCRIPT_" not in main
    assert "apalike" not in main
    metadata = json.loads(candidate["files"]["build/integration-metadata.json"])
    assert metadata["venue_template"]["template_sha256"] == _file_hash(template_path)
    assert metadata["venue_template"]["custom_class_enabled"] is False
    source = materialize_source_tree(candidate, run_root=root)
    assert (source / "main.tex").read_bytes() == main.encode("utf-8")
    assert template_path.read_bytes() == original


@pytest.mark.parametrize("mutation", ["template_changed", "template_missing", "stale_slice", "wrong_venue", "undeclared_template"])
def test_template_binding_failures_do_not_fall_back_to_generic_article(tmp_path, mutation):
    root, contract, refs, venue_slice, path = _template_case(tmp_path)
    if mutation == "template_changed":
        path.write_text(_SAFE_TEMPLATE.replace("[10pt]", "[11pt]"), encoding="utf-8")
    elif mutation == "template_missing":
        path.unlink()
    elif mutation == "stale_slice":
        venue_slice["manuscript_snapshot_sha256"] = "e" * 64
    elif mutation == "wrong_venue":
        venue_slice["venue_profile"]["venue_id"] = "another-venue"
    elif mutation == "undeclared_template":
        contract["source_hashes"] = [row for row in contract["source_hashes"] if row["kind"] != "TEMPLATE"]
        _refresh_bundles(root, contract, refs)
        venue_slice["manuscript_snapshot_sha256"] = contract["manuscript_snapshot_sha256"]
    _stamp(venue_slice, "venue_profile_slice_sha256")
    with pytest.raises(ManuscriptIntegrationError):
        _integrate(root, contract, refs, venue_profile_slice=venue_slice)
    assert not (root / "source").exists()


@pytest.mark.parametrize("template, expected", [
    (_SAFE_TEMPLATE.replace("@@MANUSCRIPT_SECTIONS@@", "Unbounded prose slot"), "VENUE_TEMPLATE_UNSUPPORTED"),
    (_SAFE_TEMPLATE.replace("{report}", "{unreviewed-journal-class}"), "UNSAFE_TEX"),
    (_SAFE_TEMPLATE.replace(r"\maketitle", r"\immediate\write18{echo forbidden}"), "UNSAFE_TEX"),
])
def test_template_port_preserves_existing_tex_safety_and_explicit_slots(tmp_path, template, expected):
    root, contract, refs, venue_slice, _ = _template_case(tmp_path, template)
    with pytest.raises(ManuscriptIntegrationError, match=expected):
        _integrate(root, contract, refs, venue_profile_slice=venue_slice)
    assert not (root / "source").exists()
