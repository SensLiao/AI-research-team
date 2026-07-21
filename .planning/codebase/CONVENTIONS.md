---
last_mapped_commit: "165d62a6deaa4cd57eee18352d5a48aab626c49d"
working_tree_state: dirty
analysis_date: "2026-07-21"
focus: quality
---

# Coding Conventions

**Analysis Date:** 2026-07-21

## Naming Patterns

**Files:**
- Use `snake_case.py` for Python modules, as in `tools/scholar_clients.py`, `tools/paper_search.py`, and `operate/panel_scheduler.py`.
- Name tests `tests/test_<subject>.py`, keeping them in the separate `tests/` tree; examples are `tests/test_scholar_clients.py` and `tests/test_operate_read_paper_deep.py`.
- Name JSON Schema contracts `<artifact_type>.schema.json`, matching registry keys in `tools/validate_artifact.py` to files such as `schemas/run_manifest.schema.json`.
- Use kebab-case for agent and skill specifications, such as `agents/source-quality-ranker.md` and `skills/research-lookup.md`.

**Functions:**
- Use `snake_case`; prefix module-private helpers with `_`, as shown by `_openalex_params()` in `tools/scholar_clients.py` and `_reject_vault_path()` in `tools/paper_search.py`.
- Give public operations verb-oriented names such as `search_many()`, `validate_artifact()`, `checkpoint_stage()`, and `run_dets_with_repair()` in `tools/paper_search.py`, `tools/validate_artifact.py`, `tools/runstore.py`, and `operate/modes/evidence_deep.py`.
- Accept injectable boundaries where determinism matters: scholarly clients accept a `transport`, and full-text QA accepts an `engine` in `tools/scholar_clients.py` and `tools/fulltext_qa.py`.

**Variables:**
- Use `snake_case` for locals and parameters; use short names only for tightly scoped parsed objects, as in `tools/scholar_clients.py`.
- Use `UPPER_SNAKE_CASE` for module constants and registries, including `DEFAULT_SOURCES` in `tools/paper_search.py`, `STAGES` in `tools/runstore.py`, and `PAYLOAD_SCHEMAS` in `tools/validate_artifact.py`.
- Use explicit suffixes such as `_path`, `_ref`, `_hash`, `_dir`, and `_payload` for provenance-bearing values throughout `tools/runstore.py` and `operate/modes/evidence_deep.py`.

**Types:**
- Use `PascalCase` for classes and exceptions, such as `ScholarLookupError` in `tools/scholar_clients.py`, `LiveConnectionRefused` in `execute/runner.py`, and `UnsafeServerCommand` in `server_monitor/monitor.py`.
- Prefer ordinary dictionaries for schema-governed artifacts, then validate them through `tools/validate_artifact.py`; do not introduce an alternate object model for JSON artifacts without updating the schemas and registry.
- Add type hints to public boundaries and non-obvious helpers, following `tools/paper_search.py`, `tools/fulltext_qa.py`, and `tools/runstore.py`.

## Code Style

**Formatting:**
- Start Python modules with a purpose/invariant docstring and `from __future__ import annotations`, following `tools/scholar_clients.py`, `orchestrator/engine.py`, and `tests/conftest.py`.
- Use four-space indentation, blank lines between import groups and top-level definitions, and UTF-8 for text I/O; explicit `encoding="utf-8"` appears throughout `tools/runstore.py` and `tools/paper_search.py`.
- Use `pathlib.Path` for local path construction and resolution, especially at trust boundaries in `tools/fulltext_qa.py`, `tools/paper_search.py`, and `execute/runner.py`.
- Serialize human-readable artifacts with `json.dumps(..., ensure_ascii=False, indent=...)`, matching `operate/cli.py` and `tools/paper_search.py`.
- No committed `pyproject.toml`, `ruff.toml`, `setup.cfg`, or formatter configuration is present; preserve the style of the nearest module instead of assuming an unenforced formatter configuration. The cache exclusion in `.gitignore` does not establish formatting rules.

**Linting:**
- No committed lint command or rule set is defined in `README.md` or repository configuration; do not claim a lint pass from the presence of `.ruff_cache/`, which is excluded by `.gitignore`.
- Keep new code compatible with the explicit imports and type-annotated style in `tools/` and `operate/`; validate behavior with the relevant `tests/test_*.py` module.

## Import Organization

**Order:**
1. Put `from __future__ import annotations` immediately after the module docstring, as in `tools/scholar_clients.py`.
2. Group standard-library imports next, such as `json`, `os`, `pathlib`, and `urllib` in `tools/scholar_clients.py` and `tools/paper_search.py`.
3. Put third-party imports after a blank line, such as `pytest` and `yaml` in `tests/conftest.py` or `Draft202012Validator` in `tools/validate_artifact.py`.
4. Put project imports last. Use absolute `research_agent_teams...` imports across top-level packages and tests, as in `tests/test_paper_search.py`.
5. Use package-relative imports only for tightly coupled siblings, as in `operate/modes/_deep_ideate.py` and `tools/schema_normalizer.py`.

**Path Aliases:**
- No source alias is configured. Import from the package root `research_agent_teams`, as demonstrated in `tests/conftest.py` and `tools/paper_search.py`.

## Error Handling

**Patterns:**
- Raise `ValueError` for malformed caller inputs and contract mismatches, following `tools/paper_search.py` and `operate/modes/evidence_deep.py`.
- Raise a policy-specific exception for fail-closed boundaries: `GateBlock` in operated modes, `PermissionError` or path-boundary errors for filesystem fences, and `LiveConnectionRefused` for unauthorized SSH in `execute/runner.py`.
- Preserve the three-state scholarly lookup distinction in `tools/scholar_clients.py`: a confirmed 404 may mean not found, while transport or parse failures remain `ScholarLookupError` and must not be converted to absence.
- Return structured degradation only where the contract explicitly allows it, such as `available=False` from `tools/fulltext_qa.py`; never fabricate evidence to keep a run moving.
- When catching an exception for a persisted error field, sanitize credentials and personal query parameters before serialization; `tools/scholar_clients.py` and `tools/paper_search.py` are the relevant boundary.

## Logging

**Framework:** No logging framework is detected; command surfaces use structured stdout and limited human-oriented stderr.

**Patterns:**
- Emit machine-readable JSON through `_emit()` in `operate/cli.py` and `execute/cli.py`.
- Keep explanatory menus and script previews on stderr in `operate/cli.py` and `execute/cli.py`, so stdout remains parseable.
- Return dictionaries or write validated artifacts from library modules instead of printing, following `tools/runstore.py` and `tools/validate_artifact.py`.
- Never log environment values. Refer to environment variable names only, consistent with `execute/config.py` and `tools/scholar_clients.py`.

## Comments

**When to Comment:**
- Explain invariants, trust boundaries, and why a conservative branch exists; examples include the vault seam comments in `tools/fulltext_qa.py` and the execution authorization comments in `execute/runner.py`.
- Use comments to record scientific semantics that code alone cannot convey, such as score-only versus hard-gate behavior in `tools/paper_search.py`.
- Avoid comments that merely restate syntax; keep maintenance history in `_design/` rather than expanding already-large implementation modules.

**JSDoc/TSDoc:**
- Not applicable. Python docstrings are the documentation convention in `tools/`, `operate/`, `orchestrator/`, and `tests/`.

## Function Design

**Size:** Keep deterministic calculations small and side-effect free where possible, then wrap them with I/O functions. `tools/repo_verifier.py` and `tools/paper_search.py` are representative. Do not add unrelated logic to oversized `operate/modes/read_paper_deep.py` or `tools/schema_normalizer.py`.

**Parameters:** Inject transports, engines, clocks/timestamps, roots, and approval flags rather than reading global state inside scientific logic, following `tools/scholar_clients.py`, `tools/fulltext_qa.py`, and `orchestrator/engine.py`.

**Return Values:** Return JSON-compatible dictionaries/lists for artifact payloads and validate them through `tools/validate_artifact.py`. Use empty error lists for successful deterministic validators and explicit exceptions for policy blocks.

## Module Design

**Exports:** Keep modules responsibility-focused. Register artifact types centrally in `tools/validate_artifact.py` and operated modes explicitly in `operate/modes/__init__.py`.

**Barrel Files:** `operate/modes/__init__.py` is an intentional registry/barrel whose contents are mirror-tested by `tests/test_operate_wiring.py` and `tests/test_capability_catalog.py`; other packages generally import concrete modules directly.

---

*Convention analysis: 2026-07-21*
