# T4 Research Agent Team Upgrade — Final Audit

Date: 2026-08-01  
State: `IMPLEMENTED / NATIVE_EXAMPLE_REVIEWED / FULL_SUITE_GREEN / DESIGN_ONLY / NON_CITABLE`  
Scope: incremental capability integration and control-plane validation; no server query, GPU execution, vault promotion, or scientific-result claim.

## 1. Outcome

The T4 upgrade is implemented as an incremental extension of the existing research system, not a replacement control plane.

The verified result is:

- one canonical `research-orchestrator` entry remains in control;
- explicit mode selection remains the highest-priority manual override;
- external projects contribute pinned concepts, rubrics, or future adapter decisions, not an imported autonomous runtime;
- an optional cross-disciplinary council forces `hypothesis → implementable mechanism → falsifiable experiment` closure;
- native work orders, completions, hashes, dependencies, precommitments, anonymous candidate packets, and repair traces prove that separate agents actually owned separate artifacts;
- the example project exposed four substantive design problems, preserved a failed first re-review, repaired only the remaining defects, and reached a strict independent targeted `PASS` without changing the PET/CT canonical.

This verifies control-plane behavior on one design-only case. It does not establish scientific efficacy, novelty, generalization, publication quality, runtime efficiency, or superiority over another agent architecture.

## 2. Immutable truth boundary

The example source manifest freezes:

```json
{
  "local_files_only": true,
  "server_query_performed": false,
  "gpu_experiment_performed": false,
  "scientific_result_allowed": false
}
```

The CPU synthetic dry-run remains:

```text
evidence_class = NOT_SCIENTIFIC_EVIDENCE
execution_kind = CPU_SYNTHETIC_CONTRACT_ONLY
preflight_state = PREFLIGHT_BLOCKED
```

No existing PET/CT experiment, OOF prediction, split, metric, gate, experiment ID, or canonical method was changed by this T4 work.

## 3. External source audit

Nine fixed local source snapshots were inspected under the out-of-repository review root. The machine lock records one commit per repository and 45 selected file SHA-256 receipts. No upstream installer, hook, MCP server, autonomous loop, or external skill implementation was executed.

| Repository | Pinned skills | License state | Local decision |
| --- | ---: | --- | --- |
| `Orchestra-Research/AI-research-SKILLs` | 98 | MIT | Concept/rubric guidance only |
| `Galaxy-Dawn/claude-scholar` | 45 | MIT | Evidence, claim, and writing discipline only |
| `Imbad0202/academic-research-skills` | 4 | CC BY-NC 4.0 | Clean-room concept use; no code or long-text copy |
| `lingzhi227/agent-research-skills` | 31 | No asserted license | Concept-only; no code or text copied |
| `K-Dense-AI/scientific-agent-skills` | 158 | MIT | Selective scientific contracts and future adapters |
| `Haojae/scipilot-figure-skill` | 1 | MIT | Figure layout/export QA concepts |
| `bahayonghang/drawio-skills` | 2 | MIT plus bundled notices | Offline adapter planned; not installed or operated |
| `icebird1998/drawio-scientific-illustrator` | 1 | MIT | Rejected live-control route retained as provenance only |
| `Yuan1z0825/nature-skills` | 19 | Apache-2.0 | Selective writing/statistics/review rubrics |
| **Total** | **359** | — | **Source lock validated** |

The authoritative source files are:

- `orchestrator/external_research_skill_sources.json`;
- `_design/review/external-research-skills-source-audit-2026-07-31.md`.

## 4. Phase-1 capability decisions

The selection registry contains exactly 25 capability decisions across six requested categories:

| Status | Count | Meaning |
| --- | ---: | --- |
| `implemented` | 20 | A local contract, router, overlay, validator, or bounded native capability exists. |
| `planned` | 4 | A named adapter target exists but is not represented as runnable. |
| `rejected` | 1 | The live-control scientific illustrator route is excluded from the runtime. |

The registry does not claim that all 25 are operated modes. It records provenance and an integration decision. In particular, paper-to-code, DICOM, figure export, and offline draw.io adapters remain planned where the full runnable adapter is not present.

Authoritative file: `orchestrator/research_skill_integration_registry.json`.

## 5. Single entry and routing

The only director-facing research entry remains `.agents/skills/research-orchestrator/SKILL.md`.

Routing behavior is now explicit:

```text
natural-language request
→ deterministic capability/mode selection
→ operated mode only
→ optional council plan
→ existing stage/gate/budget contracts
```

Key guarantees:

- `--mode <name>` overrides automatic selection;
- `--mode auto` cannot silently operate a spec-only mode;
- experiment-design language resolves to operated `full_rigor_minimal`, not the spec-only `design_experiment` definition;
- council selection can be enabled/disabled or narrowed manually;
- overlays cannot add agents, enable network access, write the vault, or execute an external repository.

## 6. Mechanism council architecture

The implemented council has seven native roles:

| Layer | Role | Scientific responsibility |
| --- | --- | --- |
| Required perspective | `mathematical_formalizer` | Formal variables, counterfactuals, estimands, falsifiers |
| Required perspective | `domain_reality_auditor` | PET/CT, anatomy, coordinate/provenance, leakage reality |
| Required perspective | `cognitive_intent_modeler` | Scribble as a state-relative communication act |
| Required perspective | `curriculum_design_specialist` | Learnability, ordering, ambiguity curriculum constraints |
| Required perspective | `causal_mechanism_critic` | Alternative explanations and discriminating controls |
| Supplemental contributor | `research_engineering_planner` | Runnable interfaces, invariants, F0 and failure checks |
| Compiler | `hypothesis_compiler` | Conflict-preserving hypothesis/mechanism/experiment closure |

This is a functional superset of the original five-specialist-plus-compiler construction brief:

```text
5 required scientific perspectives + 1 engineering contributor + 1 compiler = 7 roles
```

It must not be reported as an exact six-role implementation. Engineering was separated because the active goal explicitly requires an implementable mechanism and runnable plan rather than a purely conceptual synthesis.

## 7. Native dispatch evidence

The example project is `projects/t4-scribble-m0-mechanism-eval/`.

The validated native trace includes:

- six contributor work orders/completions with distinct agent owners;
- one compiler work order that depends on all six contributor outputs by SHA-256;
- one independent challenger with the same frozen brief and no council dependency;
- three distinct reviewers, each with a precommit stage and later blind-review stage;
- a mapping commitment created before judge authorization and a reveal recorded after all three review completions;
- two recorded fail-closed events and their recovery paths;
- two targeted re-reviews with separate outputs and immutable verdicts.

The first causal worker lost its collaboration stream twice. `WO-CAUSAL` was recorded as `ABANDONED_NO_OUTPUT`; `WO-CAUSAL-R2` used a different owner and produced the only admitted causal contribution.

The original repair worker detected that the reconciliation file bytes no longer matched its dispatched packet. It stopped before output, recorded `SOURCE_HASH_MISMATCH_AFTER_DISPATCH`, and never received a completion. A new immutable R2 packet repaired the current hash-bound source.

These events are important evidence: failures were not relabelled as successes, fixtures were not accepted as new outputs, and already-produced artifacts were not silently overwritten.

## 8. Scientific design preserved by the example

### Hypothesis

A scribble is not only geometry. Its intended corrective meaning depends on the current segmentation state `M0`; therefore, removing every M0-dependent route should reduce the model's ability to distinguish state-relative joint intent when geometry and other inputs are held fixed.

### Canonical ontology

```text
operation = {ADD, REMOVE}
target    = {SAME, NEW}
scope     = {LOCAL, COMPLETE}
```

Six joints are legal. `ADD_NEW_LOCAL` and `REMOVE_NEW_LOCAL` remain illegal.

### Primary mechanism test

The first-paper primary remains the simple-first 17-channel P2T model:

```text
full:  image + scribble + current-state M0 routes
no_M0: identical shape/capacity/initialization with every direct and derived M0 route neutralized
```

Cross-attention is not the primary. It remains a separately preregistered future ablation.

### Design contracts added by repair

- R1 freezes an exact six-joint patient-level proper loss, paired uncertainty procedure, direction, margin, decision rule, missingness, and multiplicity handling.
- R2 freezes the exhaustive transitive M0 provenance allowlist, exact neutralization, byte/capacity parity, and perturbation-invariance checks.
- R3 freezes replicate-aware binary loss-before-aggregation, equal patient weighting, patient bootstrap, canonical stratum-key JSON/UTF-8 bytes, and SHA-256 seed mapping.
- R4 freezes four-distinct-patient permutation cycles, boundary carry behavior, per-patient episode cycles, exact warm-up/cosine formulas, update indexing, and pre-step learning-rate application.

All are prospective design decisions. None has been executed against held-out outcomes.

## 9. Blind review and repair result

The X/Y mapping was committed before review and revealed afterward as:

```text
X = independent challenger
Y = mechanism council candidate
```

All three blind judges preferred X. Four substantive defects on Y were independently replicated by all three judges:

1. primary endpoint not fully frozen;
2. no_M0 neutralization not exhaustive;
3. ambiguity-strata estimand not fully executable;
4. shared training schedule not fully executable.

The reconciliation is a single-project descriptive review. It contains no p-value, confidence interval, population generalization, provider-usage comparison, or causal claim about council superiority.

Repair/re-review history:

| Artifact | Verdict | Exact outcome |
| --- | --- | --- |
| `reviews/targeted-re-review.json` | `FAIL` | R1/R2 closed; R3/R4 partial. Preserved unchanged. |
| `candidates/council-repaired-r3.md` | Design repair | Only the remaining R3/R4 deterministic algorithms were closed. |
| `reviews/targeted-re-review-r2.json` | `PASS` | 4/4 defects closed, 6/6 regressions true, zero fatal defects. |

The final reviewer was distinct from all candidate authors, repairers, the first targeted reviewer, and the three blind judges, and did not edit the candidate. Platform thread limits prevented a newly spawned fourth subagent; the independent completion auditor had performed a non-authoring preliminary content check before formal authorization. This limitation is disclosed in the review itself. Accordingly, the last step is an independent targeted re-review, not a new blind round.

## 10. Visualization and execution boundaries

The local visual router separates:

- quantitative result plots;
- scientific architecture/flow diagrams;
- editable canvas outputs.

Quantitative plots are blocked without real admitted data. No visualization generated from this design-only example may be presented as a result figure.

The CPU contract dry-run checks ontology, fixture split disjointness, arm parity, identifier exclusion, forward shapes, and patient aggregation. It ends `PREFLIGHT_BLOCKED`; it is not a GPU smoke test and does not prove the real implementation can train.

## 11. GPU resource and query contract

The resource registry contains two underlying compute resources:

| Alias | Registered hardware | Current task in this T4 audit | Honest status |
| --- | --- | --- | --- |
| `primary_gpu` | 2 × RTX A6000, 48 GiB each | `UNKNOWN` | Registration is known; live current state was not queried. |
| `secondary_gpu` | RTX 3090 + GTX 1080 Ti | `UNKNOWN` | Director reported the earlier problem resolved; live execution admission remains unverified. |

`server_monitor/query_contract.json` freezes eight read-only checks:

1. identity;
2. GPU inventory/process ownership;
3. tmux/process attribution;
4. project/run/campaign state;
5. receipts/gates/failed markers;
6. bytes and inodes;
7. Python/Conda/environment marker;
8. failure and duplicate-task risk.

`query_status` never grants `submit_job`. Missing, failed, or stale evidence yields `UNKNOWN`; historical state may not populate a current task. This T4 run intentionally made no live server connection.

## 12. Verification

Completed deterministic checks on the final evidence chain:

```text
Focused source/router/council/native tests: 60 passed in 69.99s
T4 native multi-agent evidence integration: 5 passed in 1.86s
Agent-spec/roster/connectivity regression after adding six role specs: 64 passed in 11.30s
Resource/query/evidence/roster focused regression: 88 passed in 17.10s
Repository-wide suite: 3914 passed, 4 skipped in 462.02s (0:07:42), exit code 0
```

The previous full-suite attempt found two real integration defects: the six new role specs lacked the mandatory north-star block and were absent from the roster/graph/mode connectivity contract. Both causes were fixed; the targeted regressions passed, and the final repository-wide rerun is green. The four skips are the suite's existing typed skips; they are not relabelled passes.

## 13. What remains planned or out of scope

- Four external capability adapters remain planned, not operated.
- The rejected live-control illustrator remains excluded.
- No real Stage-B provider receipt exists; no runtime/cost/quality comparison is claimed.
- No server query, upload, environment setup, job submission, GPU training, inference, patient-level evaluation, or external baseline was performed.
- The real PET/CT project must separately close F0 bundle/environment/channel/path manifests and obtain explicit live execution authorization.
- No artifact was promoted to the vault.

## 14. Reading order

1. `projects/t4-scribble-m0-mechanism-eval/README.md` — short orientation.
2. `projects/t4-scribble-m0-mechanism-eval/TASKS-DASHBOARD.md` — live status and truth boundary.
3. `_design/review/external-research-skills-source-audit-2026-07-31.md` — nine-repository source and license audit.
4. `orchestrator/research_skill_integration_registry.json` — all 25 integration decisions.
5. `projects/t4-scribble-m0-mechanism-eval/native-eval/reviews/reconciliation.json` — initial three-judge findings.
6. `projects/t4-scribble-m0-mechanism-eval/native-eval/reviews/targeted-re-review.json` — preserved first `FAIL`.
7. `projects/t4-scribble-m0-mechanism-eval/native-eval/candidates/council-repaired-r3.md` — repaired prospective design.
8. `projects/t4-scribble-m0-mechanism-eval/native-eval/reviews/targeted-re-review-r2.json` — final independent targeted `PASS`.
9. `tests/test_t4_native_multi_agent_evidence.py` — executable evidence-chain assertions.
