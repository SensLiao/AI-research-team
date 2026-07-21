---
last_mapped_commit: "165d62a6deaa4cd57eee18352d5a48aab626c49d"
working_tree_state: dirty
analysis_date: "2026-07-21"
focus: quality
---

# Testing Patterns

**Analysis Date:** 2026-07-21

## Test Framework

**Runner:**
- pytest 8.4.2 in the mapping environment.
- Config: Not detected; discovery uses pytest defaults over `tests/test_*.py` because no committed `pytest.ini`, `pyproject.toml`, `tox.ini`, or `setup.cfg` exists.
- Shared fixtures: `tests/conftest.py` installs hermetic network and vault defaults for every test.

**Assertion Library:**
- Use Python `assert` plus `pytest.raises`, fixtures, `monkeypatch`, and `pytest.importorskip`, as seen in `tests/test_paper_search.py`, `tests/test_execute.py`, and `tests/test_citation_attribution.py`.

**Run Commands:**
```bash
python -m pytest tests -q
python -m pytest tests/test_scholar_clients.py -q
python -m pytest tests --collect-only -q
```

- From the directory above this repository, the equivalent documented command is `python -m pytest research_agent_teams/tests/ -q` in `README.md`.
- No watch-mode alias or coverage command is committed in `README.md` or test configuration.

## Current Verification Evidence

- Pytest collects 3,250 tests across 186 `tests/test_*.py` modules.
- A focused boundary suite covering `tests/test_scholar_clients.py`, `tests/test_paper_search.py`, `tests/test_fulltext_qa.py`, `tests/test_repo_verifier.py`, and `tests/test_execute.py` reports `59 passed in 0.57s`.
- The full `python -m pytest research_agent_teams/tests/ -q` run produced no pass/fail conclusion within a 120-second mapping ceiling. Treat the all-suite state as unverified by this map, not failed and not passed.

## Test File Organization

**Location:**
- Keep tests in the top-level `tests/` directory, separate from implementation in `tools/`, `operate/`, `orchestrator/`, `execute/`, and `server_monitor/`.
- Mirror source responsibilities in filenames: `tools/scholar_clients.py` maps to `tests/test_scholar_clients.py`; operated mode behavior maps to `tests/test_operate_<mode>.py`.

**Naming:**
- Use `test_<behavior>()` for functions and `Test<Contract>` classes for large schema matrices, as in `tests/test_vr_review_schemas.py`.
- Name fixtures and helpers with leading underscores unless reused through `tests/conftest.py`.

**Structure:**
```text
tests/
├── conftest.py
├── test_<deterministic_tool>.py
├── test_<artifact>_schemas.py
├── test_operate_<mode>.py
└── test_<boundary>_integration.py
```

## Test Structure

**Suite Organization:**
```python
def test_lookup_doi_404_means_none_other_errors_raise():
    def transport(url, headers):
        raise _HTTPStatusError(404, url)

    assert lookup_doi_crossref("10.5555/nope", transport=transport) is None
    with pytest.raises(ScholarLookupError):
        lookup_doi_crossref("10.5555/boom", transport=failing_transport)
```

- This injected-transport pattern comes from `tests/test_scholar_clients.py`; retain the semantic distinction between not-found and lookup-error.

**Patterns:**
- Arrange input constants/factories first, call one public boundary, then assert both the result and important side effects, following `tests/test_paper_search.py` and `tests/test_document_promotion.py`.
- Validate generated payloads against the real JSON Schema through `tools/validate_artifact.py`, as used by `tests/test_repo_verifier.py` and schema suites.
- Test fail-closed cases explicitly with `pytest.raises(..., match=...)`, especially for vault paths, authorization, hashes, and schema violations in `tests/test_execute.py` and `tests/test_document_promotion.py`.
- Use fixed timestamps and deterministic byte fixtures instead of wall-clock or live-provider data, following `tests/test_document_promotion.py` and `tests/test_scholar_clients.py`.

## Mocking

**Framework:** pytest `monkeypatch`, injected callables, and small fake objects; no repository-wide mocking framework is required.

**Patterns:**
```python
def fixed(body, capture=None):
    def transport(url, headers):
        if capture is not None:
            capture.append((url, headers))
        return body
    return transport
```

- The pattern is implemented in `tests/test_scholar_clients.py` and keeps all scholarly API tests offline.
- `tests/conftest.py` autouse-patches citation existence to an offline transport and disables access to the real vault.
- Use `tmp_path` for run stores, vault fixtures, SQLite caches, and document trees in `tests/test_runstore.py`, `tests/test_citation_existence.py`, and `tests/test_document_promotion.py`.

**What to Mock:**
- Mock network transports, SSH clients, external executors, environment variables, and optional service responses, following `tests/test_scholar_clients.py` and `tests/test_execute.py`.
- Mock only the external boundary; exercise real parsing, hashing, schema validation, ledger verification, and path fencing inside the process.

**What NOT to Mock:**
- Do not mock JSON Schema validation for artifact tests; call `validate_payload()`, `validate_against()`, or `validate_artifact()` from `tools/validate_artifact.py`.
- Do not mock hash-chain and authorization derivations when testing promotion or run integrity; use real functions from `tools/ledger.py`, `tools/runstore.py`, and `tools/document_promotion.py`.
- Do not contact the real vault, scholarly APIs, or lab server in default tests; the contracts in `tests/conftest.py` and `tests/test_execute.py` require hermetic execution.

## Fixtures and Factories

**Test Data:**
```python
@pytest.fixture(autouse=True)
def hermetic_gates(monkeypatch):
    monkeypatch.setattr(_shared, "EXISTENCE_TRANSPORT", _offline_transport)
    monkeypatch.setattr(_shared, "VAULT_ROOT_OVERRIDE", False)
    yield
```

**Location:**
- Put suite-wide isolation in `tests/conftest.py`.
- Keep domain-specific builders beside their tests, such as `_seed_vault()` and `_candidate()` in `tests/test_document_promotion.py`.
- Build real temporary trees rather than checked-in generated fixtures when testing filesystem boundaries.

## Coverage

**Requirements:** None enforced. No `.coveragerc`, pytest coverage options, CI coverage gate, or committed threshold is detected.

**View Coverage:**
```bash
# Not configured in this repository; add and pin pytest-cov before defining a canonical command.
```

## Test Types

**Unit Tests:**
- Deterministic scoring, parsing, schema, hashing, and policy functions dominate `tests/test_*.py`; examples include `tests/test_repo_verifier.py` and `tests/test_scholar_clients.py`.

**Integration Tests:**
- Run-store, mode, registry, panel, and promotion tests exercise multiple local modules and real temporary files, including `tests/test_collision_gate_integration.py`, `tests/test_m3_integration.py`, and `tests/test_document_promotion.py`.

**E2E Tests:**
- Local CLI/spine smoke coverage exists in `tests/test_cli_smoke.py`, `tests/test_m1_end_to_end.py`, and `tests/test_mode_ideate_design_verify_e2e.py`.
- Real network, real vault, live SSH, and GPU execution are not part of the automated suite; `tests/conftest.py` and `tests/test_execute.py` deliberately fence those surfaces.

## Common Patterns

**Async Testing:**
```python
# Not used; provider concurrency is synchronous ThreadPoolExecutor code in tools/paper_search.py.
```

**Error Testing:**
```python
with pytest.raises(PermissionError, match="vault"):
    operation_that_crosses_the_boundary()
```

- Assert the precise failure class and a stable semantic message fragment, as done across `tests/test_scope_guard.py`, `tests/test_execute.py`, and `tests/test_bounded_repair.py`.

**Optional Dependencies:**
- Use `pytest.importorskip("fitz")` for PyMuPDF-dependent tests such as `tests/test_citation_attribution.py`; record skips rather than treating optional PDF support as universally available.

---

*Testing analysis: 2026-07-21*
