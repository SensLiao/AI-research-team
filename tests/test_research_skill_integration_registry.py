from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REGISTRY_PATH = (
    ROOT
    / "research_agent_teams"
    / "orchestrator"
    / "research_skill_integration_registry.json"
)
SOURCE_LOCK_PATH = (
    ROOT
    / "research_agent_teams"
    / "orchestrator"
    / "external_research_skill_sources.json"
)

EXPECTED_CATEGORIES = (
    "automatic_research_systems",
    "trusted_research_assistants",
    "deep_research",
    "ai_for_science",
    "research_visualization",
    "top_journal_expression",
)
EXPECTED_CATEGORY_COUNTS = {
    "automatic_research_systems": 4,
    "trusted_research_assistants": 3,
    "deep_research": 4,
    "ai_for_science": 5,
    "research_visualization": 5,
    "top_journal_expression": 4,
}
CAPABILITY_FIELDS = {
    "capability_id",
    "category",
    "source_id",
    "path",
    "sha256",
    "local_target",
    "integration_kind",
    "implementation_status",
    "why",
    "not_now",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _local_path(target: str) -> Path:
    return ROOT / target.split("#", 1)[0]


def test_phase_one_registry_is_a_small_six_category_selection() -> None:
    registry = _load(REGISTRY_PATH)
    capabilities = registry["capabilities"]

    assert registry["schema_version"] == "research-skill-integration-registry/v1"
    assert registry["phase"] == "phase_1"
    assert registry["source_lock"] == SOURCE_LOCK_PATH.relative_to(ROOT).as_posix()
    assert registry["category_order"] == list(EXPECTED_CATEGORIES)
    assert registry["selection_scope"] == {
        "locked_source_count": 9,
        "locked_skill_count": 359,
        "selected_capability_count": 25,
        "selection_rule": "Select a small first-phase set with an explicit local contract, a bounded clean-room use, a named future adapter, or a recorded rejection.",
        "copy_boundary": "This registry stores provenance and local integration decisions only; it contains no upstream skill body or source code.",
    }
    assert len(capabilities) == 25
    assert len(capabilities) < 359
    assert Counter(item["category"] for item in capabilities) == EXPECTED_CATEGORY_COUNTS
    assert len({item["capability_id"] for item in capabilities}) == len(capabilities)


def test_every_selection_is_hash_bound_to_the_locked_source_artifact() -> None:
    registry = _load(REGISTRY_PATH)
    source_lock = _load(SOURCE_LOCK_PATH)
    sources = {source["source_id"]: source for source in source_lock["sources"]}
    allowed_kinds = {
        "clean_room_guidance",
        "native_contract",
        "planned_adapter",
        "rejected",
    }
    allowed_statuses = {"implemented", "planned", "rejected"}

    for capability in registry["capabilities"]:
        assert set(capability) == CAPABILITY_FIELDS
        assert capability["category"] in EXPECTED_CATEGORIES
        assert capability["source_id"] in sources
        assert re.fullmatch(r"[0-9a-f]{64}", capability["sha256"])
        artifacts = {
            (artifact["path"], artifact["sha256"])
            for artifact in sources[capability["source_id"]]["source_artifacts"]
        }
        assert (capability["path"], capability["sha256"]) in artifacts
        assert capability["integration_kind"] in allowed_kinds
        assert capability["implementation_status"] in allowed_statuses
        assert capability["why"].strip()
        assert capability["not_now"].strip()
        assert _local_path(capability["local_target"]).is_file()

        source = sources[capability["source_id"]]
        if capability["integration_kind"] == "rejected":
            assert capability["implementation_status"] == "rejected"
            assert source["selectable"] is False
        else:
            assert source["selectable"] is True
        if capability["integration_kind"] == "planned_adapter":
            assert capability["implementation_status"] == "planned"
        if capability["integration_kind"] in {"clean_room_guidance", "native_contract"}:
            assert capability["implementation_status"] == "implemented"

    assert {item["integration_kind"] for item in registry["capabilities"]} == allowed_kinds
    assert "operated" not in json.dumps(registry, ensure_ascii=False).lower()


def test_implemented_native_surfaces_are_mapped_without_overclaiming_adapters() -> None:
    capabilities = {
        item["capability_id"]: item for item in _load(REGISTRY_PATH)["capabilities"]
    }
    expected_implemented = {
        "single_entry_research_orchestrator": (
            ".agents/skills/research-orchestrator/SKILL.md",
            "native_contract",
        ),
        "mechanism_council": (
            "research_agent_teams/orchestrator/mechanism_council.json",
            "native_contract",
        ),
        "research_visual_router": (
            "research_agent_teams/tools/research_visual_router.py",
            "native_contract",
        ),
        "native_dispatch_trace": (
            "research_agent_teams/tools/native_dispatch_trace.py",
            "clean_room_guidance",
        ),
        "server_query_contract": (
            "research_agent_teams/server_monitor/query_contract.json",
            "native_contract",
        ),
    }
    for capability_id, (local_target, integration_kind) in expected_implemented.items():
        item = capabilities[capability_id]
        assert item["local_target"] == local_target
        assert item["integration_kind"] == integration_kind
        assert item["implementation_status"] == "implemented"

    for capability_id in (
        "paper_to_code_adapter",
        "pydicom_data_audit_adapter",
        "scientific_figure_export_adapter",
        "offline_drawio_adapter",
    ):
        item = capabilities[capability_id]
        assert item["integration_kind"] == "planned_adapter"
        assert item["implementation_status"] == "planned"

    rejected = capabilities["live_drawio_illustrator_rejection"]
    assert rejected["source_id"] == "drawio_scientific_illustrator"
    assert rejected["integration_kind"] == "rejected"
    assert rejected["implementation_status"] == "rejected"


def test_registry_is_metadata_only_and_does_not_embed_upstream_payloads() -> None:
    registry = _load(REGISTRY_PATH)
    forbidden_fields = {
        "source_excerpt",
        "source_text",
        "source_code",
        "copied_content",
        "install_command",
        "runtime_command",
    }
    assert forbidden_fields.isdisjoint(registry)
    for capability in registry["capabilities"]:
        assert forbidden_fields.isdisjoint(capability)
