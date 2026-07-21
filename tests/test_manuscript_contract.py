"""TDD contract for deterministic manuscript token resolution and freezing."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from research_agent_teams.tests.test_manuscript_predraft_schemas import (
    valid_manuscript_contract,
)
from research_agent_teams.tools.manuscript_contract import (
    TOKEN_LAYERS,
    ManuscriptContractError,
    affected_descendants,
    canonical_contract_hash,
    freeze_manuscript_contract,
    load_paper_design_token_profiles,
    resolve_paper_design_tokens,
)
from research_agent_teams.tools.validate_artifact import validate_payload


ROOT = Path(__file__).resolve().parents[1]
PROFILE_ROOT = ROOT / "profiles" / "paper_design_tokens"
NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
MAX_OFFICIAL_AGE = timedelta(days=45)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _canonical_sha(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _entry(
    value: object,
    *,
    layer: str,
    classification: str = "ADVISORY",
    weakenable: bool | None = None,
    delete: bool = False,
) -> dict:
    entry = {
        "value": value,
        "classification": classification,
        "weakenable": classification != "HARD" if weakenable is None else weakenable,
        "source_ref": f"token-overlays/{layer}.yaml",
        "source_sha256": _sha(layer),
    }
    if delete:
        entry["delete"] = True
        entry.pop("value")
    return entry


def _layer_document(layer: str, tokens: dict, *, mandatory_tokens=()) -> dict:
    return {
        "layer": layer,
        "source_ref": f"token-overlays/{layer}.yaml",
        "source_sha256": _sha(layer),
        "mandatory_tokens": list(mandatory_tokens),
        "tokens": tokens,
    }


def _five_layer_voice() -> dict:
    values = {
        "base": "neutral",
        "paper_type": "technical",
        "venue": "compact",
        "project": "measured",
        "run": "direct",
    }
    layers = {
        layer: _layer_document(layer, {"voice": _entry(value, layer=layer)})
        for layer, value in values.items()
    }
    hard_values = {
        "no_fabrication": True,
        "claim_traceability": "claim-number-citation-closure",
        "terminology_consistency": "frozen-glossary-and-notation",
        "asset_provenance": "hashed-source-and-result-refs",
        "compile_integrity": "references-and-cross-references-must-resolve",
        "no_shell_escape": True,
    }
    layers["base"]["tokens"].update(
        {
            token: _entry(
                value,
                layer="base",
                classification="HARD",
                weakenable=False,
            )
            for token, value in hard_values.items()
        }
    )
    layers["base"]["mandatory_tokens"] = list(hard_values)
    return layers


def _venue_requires_pdf(value: bool) -> dict:
    return _entry(value, layer="venue", classification="HARD", weakenable=False)


def _token_source_hashes() -> list[dict]:
    return [
        {
            "ref": f"token-overlays/{layer}.yaml",
            "sha256": _sha(layer),
            "kind": "TOKEN_OVERLAY",
        }
        for layer in TOKEN_LAYERS
    ]


def _valid_frozen_contract(*, requires_pdf: bool = True) -> dict:
    payload = valid_manuscript_contract()
    venue_rule = payload["venue_profile"]["official_rule_refs"][0]
    venue_rule["sha256"] = _sha("venue-rule")
    payload["venue_profile"].update(
        retrieved_at="2026-07-20T12:00:00Z",
        template_sha256=_sha("venue-template"),
        requires_pdf=requires_pdf,
    )
    policy = payload["venue_profile"]["hard_field_policy"]["requires_pdf"]
    policy.update(
        source_ref=venue_rule["ref"],
        source_sha256=venue_rule["sha256"],
    )

    layers = _five_layer_voice()
    layers["venue"]["tokens"]["requires_pdf"] = {
        "value": requires_pdf,
        "classification": "HARD",
        "weakenable": False,
        "source_ref": venue_rule["ref"],
        "source_sha256": venue_rule["sha256"],
    }
    payload["resolved_tokens"] = resolve_paper_design_tokens(layers)

    dependency_slice = payload["dependency_slices"][0]
    dependency_slice["slice_sha256"] = _canonical_sha(
        {key: value for key, value in dependency_slice.items() if key != "slice_sha256"}
    )

    source_hashes = [
        row
        for row in payload["source_hashes"]
        if row["kind"] not in {"VENUE_RULE", "TEMPLATE", "TOKEN_OVERLAY"}
    ]
    source_hashes.extend(
        [
            {
                "ref": venue_rule["ref"],
                "sha256": venue_rule["sha256"],
                "kind": "VENUE_RULE",
            },
            {
                "ref": payload["venue_profile"]["template_ref"],
                "sha256": payload["venue_profile"]["template_sha256"],
                "kind": "TEMPLATE",
            },
            *_token_source_hashes(),
        ]
    )
    payload["source_hashes"] = source_hashes
    payload["manuscript_snapshot_sha256"] = "0" * 64
    return payload


def _freeze(payload: dict, tmp_path: Path, *, name: str = "contract.json") -> dict:
    def verified_result(row: dict) -> dict:
        return {
            "verified": True,
            "result_ref": row["ref"],
            "result_sha256": row["sha256"],
            "receipt_ref": row["receipt_ref"],
            "receipt_sha256": row["receipt_sha256"],
        }

    return freeze_manuscript_contract(
        payload,
        Path("state") / name,
        run_root=tmp_path,
        now=NOW,
        max_official_age=MAX_OFFICIAL_AGE,
        result_receipt_verifier=verified_result,
    )


def test_token_layers_are_exact_and_resolution_ignores_input_mapping_order():
    assert TOKEN_LAYERS == ("base", "paper_type", "venue", "project", "run")
    layers = _five_layer_voice()
    reverse_layers = OrderedDict(reversed(list(layers.items())))

    normal = resolve_paper_design_tokens(layers)
    reversed_input = resolve_paper_design_tokens(reverse_layers)

    assert normal == reversed_input
    assert normal["resolved"]["voice"] == "direct"
    assert normal["snapshot_sha256"] == reversed_input["snapshot_sha256"]


def test_every_override_records_full_provenance_and_prior_value():
    result = resolve_paper_design_tokens(_five_layer_voice())
    provenance = result["provenance"]["voice"]

    assert provenance["layer"] == "run"
    assert provenance["source_ref"] == "token-overlays/run.yaml"
    assert provenance["source_sha256"] == _sha("run")
    assert provenance["classification"] == "ADVISORY"
    assert provenance["prior_value"] == "measured"
    assert [event["layer"] for event in provenance["history"]] == list(TOKEN_LAYERS)
    assert [event["prior_value"] for event in provenance["history"]] == [
        None,
        "neutral",
        "technical",
        "compact",
        "measured",
    ]


def test_valid_advisory_overrides_produce_nonblocking_caveats():
    result = resolve_paper_design_tokens(_five_layer_voice())

    assert len(result["caveats"]) == 4
    assert all(row["code"] == "ADVISORY_OVERRIDE" for row in result["caveats"])
    assert all(row["blocking"] is False for row in result["caveats"])
    assert all(row["daily_state"] == "USABLE_WITH_CAVEATS" for row in result["caveats"])
    assert result["hard_failures"] == []


@pytest.mark.parametrize(
    ("override", "error_code"),
    [
        (_entry(False, layer="project"), "HARD_RULE_OVERRIDE"),
        (_entry(None, layer="project", delete=True), "HARD_RULE_DELETE"),
        (
            _entry(True, layer="project", classification="ADVISORY"),
            "HARD_RULE_RECLASSIFICATION",
        ),
        (
            _entry(True, layer="project", classification="HARD", weakenable=True),
            "HARD_RULE_WEAKENING",
        ),
    ],
)
def test_inherited_hard_rule_cannot_be_changed_deleted_reclassified_or_weakened(
    override: dict, error_code: str
):
    layers = {
        "venue": _layer_document(
            "venue", {"requires_pdf": _venue_requires_pdf(True)}
        ),
        "project": _layer_document("project", {"requires_pdf": override}),
    }

    with pytest.raises(ManuscriptContractError, match=error_code):
        resolve_paper_design_tokens(layers)


@pytest.mark.parametrize("official_value", [True, False])
def test_official_requires_pdf_boolean_is_preserved(official_value: bool):
    layers = {
        "venue": _layer_document(
            "venue", {"requires_pdf": _venue_requires_pdf(official_value)}
        ),
        "run": _layer_document("run", {"voice": _entry("direct", layer="run")}),
    }

    result = resolve_paper_design_tokens(layers)
    token = next(row for row in result["tokens"] if row["token"] == "requires_pdf")

    assert token["value"] is official_value
    assert token["classification"] == "HARD"
    assert token["resolved_layer"] == "venue"
    assert token["weakenable"] is False


def test_requires_pdf_cannot_be_declared_outside_official_venue_layer():
    layers = {
        "project": _layer_document(
            "project", {"requires_pdf": _entry(True, layer="project")}
        )
    }

    with pytest.raises(ManuscriptContractError, match="REQUIRES_PDF_AUTHORITY"):
        resolve_paper_design_tokens(layers)


def test_unknown_mandatory_token_is_rejected():
    layers = {
        "base": _layer_document(
            "base",
            {"voice": _entry("neutral", layer="base")},
            mandatory_tokens=("not_declared",),
        )
    }

    with pytest.raises(ManuscriptContractError, match="UNKNOWN_MANDATORY_TOKEN"):
        resolve_paper_design_tokens(layers)


def test_style_token_cannot_self_declare_hard_even_in_base_layer():
    layers = {
        "base": _layer_document(
            "base",
            {
                "voice": _entry(
                    "mandatory-voice",
                    layer="base",
                    classification="HARD",
                    weakenable=False,
                )
            },
        )
    }

    with pytest.raises(ManuscriptContractError, match="UNAUTHORIZED_HARD_TOKEN"):
        resolve_paper_design_tokens(layers)


def test_reserved_truth_token_cannot_be_downgraded_to_advisory():
    layers = {
        "base": _layer_document(
            "base",
            {
                "no_fabrication": _entry(
                    False,
                    layer="base",
                    classification="ADVISORY",
                    weakenable=True,
                )
            },
        )
    }

    with pytest.raises(ManuscriptContractError, match="BASE_HARD_POLICY"):
        resolve_paper_design_tokens(layers)


def test_profile_loader_hashes_three_domain_neutral_configuration_files():
    layers = load_paper_design_token_profiles(PROFILE_ROOT, paper_type="METHOD")

    assert set(layers) == {"base", "paper_type", "project"}
    assert layers["base"]["layer"] == "base"
    assert layers["paper_type"]["layer"] == "paper_type"
    assert layers["project"]["layer"] == "project"
    for layer in layers.values():
        assert re.fullmatch(r"[0-9a-f]{64}", layer["source_sha256"])
        assert layer["source_ref"].startswith("profiles/paper_design_tokens/")


def test_profiles_keep_small_hard_core_and_style_as_advisory():
    base = yaml.safe_load((PROFILE_ROOT / "base.yaml").read_text(encoding="utf-8"))
    paper_types = yaml.safe_load(
        (PROFILE_ROOT / "paper_types.yaml").read_text(encoding="utf-8")
    )
    ai_defaults = yaml.safe_load(
        (PROFILE_ROOT / "ai_research.yaml").read_text(encoding="utf-8")
    )

    classifications = [row["classification"] for row in base["tokens"].values()]
    assert classifications.count("HARD") < classifications.count("ADVISORY")
    assert set(paper_types["paper_types"]) == {
        "METHOD",
        "EMPIRICAL",
        "DATASET",
        "SYSTEMS",
        "THEORY",
        "POSITION_SURVEY",
    }
    assert all(
        token["classification"] == "ADVISORY"
        for profile in paper_types["paper_types"].values()
        for token in profile["tokens"].values()
    )
    assert all(
        token["classification"] == "ADVISORY"
        for token in ai_defaults["tokens"].values()
    )


def test_profiles_contain_no_transient_or_host_specific_control_plane_constants():
    combined = "\n".join(
        (PROFILE_ROOT / name).read_text(encoding="utf-8")
        for name in ("base.yaml", "paper_types.yaml", "ai_research.yaml")
    ).lower()

    forbidden = (
        "deadline",
        "username",
        "c:\\users",
        "/home/",
        "icml",
        "neurips",
        "openai",
        "anthropic",
        "claude",
        "gpt-",
        "medical-imaging",
    )
    assert not any(value in combined for value in forbidden)
    assert "requires_pdf" not in combined


def test_canonical_contract_hash_is_stable_and_ignores_existing_stamp():
    first = _valid_frozen_contract()
    second = json.loads(json.dumps(first, sort_keys=False))
    second = OrderedDict(reversed(list(second.items())))
    second["manuscript_snapshot_sha256"] = "f" * 64

    assert canonical_contract_hash(first) == canonical_contract_hash(second)
    assert re.fullmatch(r"[0-9a-f]{64}", canonical_contract_hash(first))


def test_one_upstream_change_changes_contract_hash():
    before = _valid_frozen_contract()
    after = copy.deepcopy(before)
    after["north_star"] = "A changed, still evidence-bounded north star."

    assert canonical_contract_hash(before) != canonical_contract_hash(after)


@pytest.mark.parametrize("requires_pdf", [True, False])
def test_freeze_validates_complete_contract_and_writes_canonical_snapshot(
    tmp_path: Path, requires_pdf: bool
):
    source = _valid_frozen_contract(requires_pdf=requires_pdf)
    source_before = copy.deepcopy(source)

    frozen = _freeze(source, tmp_path)
    written = json.loads((tmp_path / "state" / "contract.json").read_text("utf-8"))

    assert source == source_before
    assert written == frozen
    assert validate_payload("manuscript_contract", frozen) == []
    assert frozen["manuscript_snapshot_sha256"] == canonical_contract_hash(frozen)
    requires_pdf_token = next(
        row for row in frozen["resolved_tokens"]["tokens"]
        if row["token"] == "requires_pdf"
    )
    assert requires_pdf_token["value"] is requires_pdf
    assert not (tmp_path / "state" / "contract.json.tmp").exists()


@pytest.mark.parametrize("missing", ["paper_type", "north_star", "source_hashes"])
def test_freeze_rejects_missing_d12_snapshot_fields(tmp_path: Path, missing: str):
    payload = _valid_frozen_contract()
    payload.pop(missing)

    with pytest.raises(ManuscriptContractError, match="SCHEMA_INVALID"):
        _freeze(payload, tmp_path)

    assert not (tmp_path / "state" / "contract.json").exists()


def test_freeze_rejects_stale_or_future_official_sources(tmp_path: Path):
    stale = _valid_frozen_contract()
    stale["venue_profile"]["retrieved_at"] = "2026-01-01T00:00:00Z"
    future = _valid_frozen_contract()
    future["venue_profile"]["retrieved_at"] = "2026-07-22T00:00:00Z"

    with pytest.raises(ManuscriptContractError, match="OFFICIAL_SOURCE_STALE"):
        _freeze(stale, tmp_path, name="stale.json")
    with pytest.raises(ManuscriptContractError, match="OFFICIAL_SOURCE_FUTURE"):
        _freeze(future, tmp_path, name="future.json")


def test_freeze_rejects_unhashed_official_source_before_writing(tmp_path: Path):
    payload = _valid_frozen_contract()
    payload["venue_profile"]["official_rule_refs"][0]["sha256"] = "not-a-hash"

    with pytest.raises(ManuscriptContractError, match="OFFICIAL_SOURCE_HASH"):
        _freeze(payload, tmp_path)

    assert not (tmp_path / "state" / "contract.json").exists()


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload["claim_ledger"][0]["evidence_refs"].append(
            "evidence/unknown"
        ),
        lambda payload: payload["asset_plan"][0]["result_refs"].append(
            "results/unknown"
        ),
    ],
)
def test_freeze_rejects_unknown_evidence_or_result_references(tmp_path: Path, mutate):
    payload = _valid_frozen_contract()
    mutate(payload)

    with pytest.raises(ManuscriptContractError, match="UNKNOWN_(EVIDENCE|RESULT)_REF"):
        _freeze(payload, tmp_path)


def test_freeze_rejects_mutated_dependency_slice(tmp_path: Path):
    payload = _valid_frozen_contract()
    payload["dependency_slices"][0]["input_refs"][0]["slice_kind"] = "RESULT_FACT"

    with pytest.raises(ManuscriptContractError, match="DEPENDENCY_SLICE_HASH_MISMATCH"):
        _freeze(payload, tmp_path)


def test_freeze_rejects_schema_only_or_tampered_token_resolution(tmp_path: Path):
    schema_only = _valid_frozen_contract()
    schema_only["resolved_tokens"] = schema_only["resolved_tokens"]["resolved_tokens"]
    with pytest.raises(ManuscriptContractError, match="TOKEN_RESOLUTION_ATTESTATION"):
        _freeze(schema_only, tmp_path, name="schema-only.json")

    tampered = _valid_frozen_contract()
    voice = next(
        row for row in tampered["resolved_tokens"]["tokens"] if row["token"] == "voice"
    )
    voice.update(classification="HARD", weakenable=False)
    with pytest.raises(ManuscriptContractError, match="TOKEN_RESOLUTION_TAMPERED"):
        _freeze(tampered, tmp_path, name="tampered.json")


def test_freeze_requires_injected_verified_result_and_receipt_facts(tmp_path: Path):
    payload = _valid_frozen_contract()
    with pytest.raises(ManuscriptContractError, match="RESULT_VERIFIER_REQUIRED"):
        freeze_manuscript_contract(
            payload,
            "state/no-verifier.json",
            run_root=tmp_path,
            now=NOW,
            max_official_age=MAX_OFFICIAL_AGE,
        )

    def forged_facts(row: dict) -> dict:
        return {
            "verified": True,
            "result_ref": row["ref"],
            "result_sha256": row["sha256"],
            "receipt_ref": row["receipt_ref"],
            "receipt_sha256": "f" * 64,
        }

    with pytest.raises(ManuscriptContractError, match="RESULT_RECEIPT_UNVERIFIED"):
        freeze_manuscript_contract(
            payload,
            "state/forged-verifier.json",
            run_root=tmp_path,
            now=NOW,
            max_official_age=MAX_OFFICIAL_AGE,
            result_receipt_verifier=forged_facts,
        )

    def truthy_but_not_verified(row: dict) -> dict:
        return {
            "verified": 1,
            "result_ref": row["ref"],
            "result_sha256": row["sha256"],
            "receipt_ref": row["receipt_ref"],
            "receipt_sha256": row["receipt_sha256"],
        }

    with pytest.raises(ManuscriptContractError, match="RESULT_RECEIPT_UNVERIFIED"):
        freeze_manuscript_contract(
            payload,
            "state/truthy-verifier.json",
            run_root=tmp_path,
            now=NOW,
            max_official_age=MAX_OFFICIAL_AGE,
            result_receipt_verifier=truthy_but_not_verified,
        )


def test_freeze_rejects_venue_hard_token_without_official_source(tmp_path: Path):
    payload = _valid_frozen_contract()
    layers = copy.deepcopy(payload["resolved_tokens"]["source_layers"])
    layers["venue"]["tokens"]["anonymity"] = _entry(
        "double-blind",
        layer="venue",
        classification="HARD",
        weakenable=False,
    )
    payload["resolved_tokens"] = resolve_paper_design_tokens(layers)

    with pytest.raises(ManuscriptContractError, match="VENUE_HARD_SOURCE"):
        _freeze(payload, tmp_path, name="unofficial-venue-hard.json")


def test_freeze_is_idempotent_but_never_overwrites_a_different_snapshot(tmp_path: Path):
    payload = _valid_frozen_contract()
    first = _freeze(payload, tmp_path)

    assert _freeze(payload, tmp_path) == first
    changed = _valid_frozen_contract()
    changed["north_star"] = "Different immutable contract."
    with pytest.raises(ManuscriptContractError, match="FROZEN_CONTRACT_CONFLICT"):
        _freeze(changed, tmp_path)
    assert json.loads((tmp_path / "state" / "contract.json").read_text("utf-8")) == first


def test_concurrent_freeze_is_create_once_and_leaves_no_temporary_files(tmp_path: Path):
    first = _valid_frozen_contract()
    second = _valid_frozen_contract()
    second["north_star"] = "A concurrent but different immutable contract."

    def attempt(payload: dict):
        try:
            return _freeze(payload, tmp_path, name="concurrent.json")
        except ManuscriptContractError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, (first, second)))

    assert sum(isinstance(outcome, dict) for outcome in outcomes) == 1
    assert outcomes.count("FROZEN_CONTRACT_CONFLICT") == 1
    written = json.loads((tmp_path / "state" / "concurrent.json").read_text("utf-8"))
    assert written in [outcome for outcome in outcomes if isinstance(outcome, dict)]
    assert list((tmp_path / "state").glob("*.tmp")) == []


def test_freeze_rejects_output_path_outside_injected_run_root(tmp_path: Path):
    outside = tmp_path.parent / "outside-contract.json"

    with pytest.raises(Exception, match="PATH_OUTSIDE_RUN"):
        freeze_manuscript_contract(
            _valid_frozen_contract(),
            outside,
            run_root=tmp_path,
            now=NOW,
            max_official_age=MAX_OFFICIAL_AGE,
            result_receipt_verifier=lambda row: {
                "verified": True,
                "result_ref": row["ref"],
                "result_sha256": row["sha256"],
                "receipt_ref": row["receipt_ref"],
                "receipt_sha256": row["receipt_sha256"],
            },
        )


def test_freeze_applies_shared_secret_scan_before_persistence(tmp_path: Path):
    payload = _valid_frozen_contract()
    payload["north_star"] = "Never persist FIXTURE_ONLY_NOT_A_REAL_SECRET_0111."

    with pytest.raises(Exception, match="SECRET_LEAKAGE"):
        freeze_manuscript_contract(
            payload,
            "state/contract.json",
            run_root=tmp_path,
            now=NOW,
            max_official_age=MAX_OFFICIAL_AGE,
            result_receipt_verifier=lambda row: {
                "verified": True,
                "result_ref": row["ref"],
                "result_sha256": row["sha256"],
                "receipt_ref": row["receipt_ref"],
                "receipt_sha256": row["receipt_sha256"],
            },
            secret_sentinels={"fixture": "FIXTURE_ONLY_NOT_A_REAL_SECRET_0111"},
        )
    assert not (tmp_path / "state" / "contract.json").exists()


def test_affected_descendants_returns_only_explicit_transitive_consumers():
    graph = {
        "contract": ["section-method", "integration"],
        "section-method": ["integration"],
        "integration": ["review", "build"],
        "review": [],
        "build": [],
        "unrelated-asset": [],
    }

    invalidated = affected_descendants({"contract"}, graph)

    assert invalidated == ["section-method", "integration", "review", "build"]
    assert "contract" not in invalidated
    assert "unrelated-asset" not in invalidated


def test_affected_descendants_rejects_unknown_nodes_and_cycles():
    with pytest.raises(ManuscriptContractError, match="UNKNOWN_DEPENDENCY_NODE"):
        affected_descendants({"missing"}, {"contract": ["author"], "author": []})
    with pytest.raises(ManuscriptContractError, match="DEPENDENCY_CYCLE"):
        affected_descendants({"contract"}, {"contract": ["author"], "author": ["contract"]})
