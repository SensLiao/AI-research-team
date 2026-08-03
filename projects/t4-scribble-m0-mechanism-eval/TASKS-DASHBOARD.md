# T4 Scribble–M0 Mechanism Council — Tasks Dashboard

> Scope: research-agent control-plane validation only. No GPU experiment, server query, PET/CT metric, scientific result, or vault write occurred.  
> Current state: `DESIGN_ONLY / NATIVE_MULTI_AGENT_TRACE_VALIDATED / TARGETED_REVIEW_PASS / NON_CITABLE`.  
> Final release check: `3914 passed, 4 skipped` in the repository-wide suite; exit code 0.

## Status summary

| Area | Verified state | Evidence |
| --- | --- | --- |
| External sources | 9 pinned repositories, 359 visible `SKILL.md` files, 45 hash-bound source artifacts | `orchestrator/external_research_skill_sources.json` |
| Phase-1 integration | 25 selected capabilities: 20 implemented, 4 planned, 1 rejected | `orchestrator/research_skill_integration_registry.json` |
| Single entry | Automatic routing uses the operated entry; explicit mode remains authoritative | `tools/research_capability_router.py`, `orchestrator/router.py` |
| Mechanism council | 5 required scientific perspectives + 1 supplemental engineering contributor + 1 compiler | `orchestrator/mechanism_council.json` |
| Native evidence | Seven council roles, one independent challenger, three precommitted blind judges, repairs, and re-reviews have hash-bound work orders/completions | `native-eval/` |
| Scientific state | Prospective design only; the real downstream F0 bundle remains blocked | `native-eval/preflight/contract-dry-run.json` |
| Server state | Two registered GPU resources; current tasks are `UNKNOWN`; this T4 run made no live query | `server_monitor/query_contract.json` |

The council is an intentional functional superset of the construction brief: it contains the five required scientific perspectives, a separate engineering contributor, and the compiler (`5 + 1 + 1 = 7`). It must not be described as an exact six-role council.

## Work products

| ID | Work product | State | Verification |
| --- | --- | --- | --- |
| T4-E0 | Freeze external source lock | `DONE` | 9 sources, 359 skills, commits/licenses/file SHA-256 values validated. |
| T4-E1 | Select the bounded Phase-1 capability set | `DONE` | 25 decisions resolve to 20 implemented, 4 planned, and 1 rejected capability. |
| T4-E2 | Preserve one smart entry and manual override | `DONE` | Auto experiment design resolves to operated `full_rigor_minimal`; a named mode overrides auto routing; spec-only operation remains refused. |
| T4-E3 | Dispatch the mechanism council | `DONE` | Six distinct contributor outputs plus a dependency-bound compiler output have valid work orders, completions, unique owners, nonces, timestamps, and hashes. |
| T4-E4 | Build an independent challenger | `DONE` | Challenger used the same frozen brief, had no council dependency, and had a distinct agent owner. |
| T4-E5 | Precommit and blind the comparison | `DONE` | Mapping commitment preceded judge authorization; candidates were sealed as X/Y before three review work orders. |
| T4-E6 | Run three-agent blind review | `DONE` | Domain, methods/statistics, and evidence judges were distinct; all reviewed the same packet and selected X. |
| T4-E7 | Reconcile substantive defects | `DONE` | Four Y/council defects were independently replicated 3/3; the report remains descriptive and claims no inferential superiority. |
| T4-E8 | Repair and re-review | `DONE` | Original repair aborted on a source-hash mismatch; R2 closed 2/4 and correctly received `FAIL`; R3 closed 4/4 and received `PASS` with 6/6 regression guards intact. |
| T4-E9 | Run a CPU contract dry-run | `DONE` | Six synthetic contract checks and three tests passed; state remains `PREFLIGHT_BLOCKED / NOT_SCIENTIFIC_EVIDENCE`. |
| T4-E10 | Lock the evidence chain in integration tests | `DONE` | `tests/test_t4_native_multi_agent_evidence.py`: 5/5 pass, including commitment/reveal ordering and the fail-closed repair history. |
| T4-E11 | Repository-wide regression and final audit | `DONE` | `python -m pytest -q -p no:cacheprovider tests`: exit 0, 3914 passed, 4 skipped in 462.02s. |

## Blind review and repair outcome

| Round | Outcome | Meaning |
| --- | --- | --- |
| Initial blind panel | X/challenger won 3–0 | Single-project descriptive review only; not a population-level method comparison. |
| Replicated defects on Y/council | 4 defects, each 3/3 | Primary endpoint, exhaustive no_M0 neutralization, ambiguity-strata estimand, and shared training schedule were not fully frozen. |
| R2 targeted re-review | `FAIL` | Endpoint and no_M0 intervention closed; strata and schedule remained partial. This file is preserved unchanged. |
| R3 independent targeted re-review | `PASS` | All four defects closed; six canonical/truth regressions remained true; fatal defects were absent. |

The R3 reviewer was different from every author, repairer, first targeted reviewer, and blind judge, and did not edit the candidate. Because platform thread limits prevented a newly spawned fourth subagent and the auditor had performed a non-authoring preliminary content check before formal authorization, the R3 review is honestly classified as an independent targeted re-review, not a new blind round.

## Scientific invariants preserved

- Scribble construction precedes intent inference.
- Intent is factorized as `operation × target × scope`:
  - `operation={ADD,REMOVE}`;
  - `target={SAME,NEW}`;
  - `scope={LOCAL,COMPLETE}`.
- Only six joints are legal; `ADD_NEW_LOCAL` and `REMOVE_NEW_LOCAL` are illegal.
- The existing patient-excluded OOF M0 artifact remains an immutable upstream input and was not regenerated.
- The first-paper P2T primary remains the simple-first 17-channel `full` versus exhaustive `no_M0` comparison.
- Cross-attention remains future work; it was not promoted into the primary.
- No training, inference, patient metric, external comparison, scientific result, or publication claim exists in this example.

## Final verification receipt

Run from `research_agent_teams/`:

```powershell
python -m pytest -q -p no:cacheprovider tests
```

Result:

```text
exit_code = 0
3914 passed, 4 skipped in 462.02s (0:07:42)
```

T4-E11 is closed. Real PET/CT execution remains a separate, explicitly authorized project task.
