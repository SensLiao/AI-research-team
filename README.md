# Research Agent Teams (the machine)

Scientific publication figures now have an offline SVG/PDF/PNG adapter, a journal-choice/profile handoff, and automatic planned-figure preparation before manuscript integration. Reuse the existing architect/figure-engineer/figure-reviewer seats; see [the scientific-figure guide](docs/SCIENTIFIC-FIGURES.md) and [the source/asset catalogue](resources/scientific-figures/catalog.json). This does not imply support for every custom journal TeX class.

> Current status source (re-derived 2026-09-06): see `PLATFORM-FACTS.md` §0 and the live
> `worker_census` / `operate brief` commands. This checkout currently has **172 agents**
> (7 control + 165 workers), **27 registered modes** (**24 operated / 3 spec-only**), **163 tools**,
> **181 schemas**, **7 stages**, **5 human gates**, **2 hooks**, **7 domain profiles**,
> **33 `operate` subcommands**, and **259 test files** (in the workspace `tests/machine/`). Do not reuse these snapshot numbers in a run;
> derive them again. Codex worker specs/logs carry
> model-agnostic `capability_requirements`; optional concrete runtime fields are
> supplied only by deployment environment bindings. In addition,
> `read_paper_deep` has one historical real local-PDF smoke run plus a staged
> 20-worker A-core paper-reading panel. Evidence modes use methodology-derived
> source quality, semantic search traces, exact-span attribution, and independent
> citation audit. `new_direction` / `deep_ideation` expose a
> Markdown-first `/idea-bet` decision page at `director-review/ideas/idea-bet-menu.md`.
> GPU experiment execution remains server-gated and not operated.

Director entry surfaces currently include 20 Claude commands, 2 Claude skills, and 19 Codex skills;
all five human-decision Codex gates disable implicit invocation.

The **agent team itself**: its configuration, its control plane, and everything it produces while
running. This is one of **two cleanly separated systems**:

| System | Directory | Role |
|---|---|---|
| **Research Agent Teams** (this) | `research_agent_teams/` | THE MACHINE — agent roster + config + control plane + run outputs |
| **PhD-Research-OS** | `AI agent database/PhD-Research-OS/` | THE RESEARCH DATABASE — validated knowledge (the vault) |

> They must NOT be mixed. They connect at exactly **one seam**: the machine *reads* the database
> by reference (recall) and *promotes* vetted artifacts INTO it through an explicit-user director-command gate. Nothing else
> crosses. Full design: `_design/research-agent-teams-complete-blueprint-v1.md`.

> A director-reviewed final Markdown product is copied in full into a typed vault page by the document-admission
> lane of `/promote-to-vault` before its scratch run is cleaned up. This preserves readable research knowledge
> without pretending that a paper card, idea, or synthesis is a frozen experimental result.

## What this is (and is NOT)

Built **scientific-output-first**: independent workers gather evidence, read papers, prosecute gaps,
compare ideas, design and analyze experiments, then write mode-specific Markdown for a researcher.
The state machine, schemas, scheduler, receipts, and gates exist to keep those products honest; they
are supporting machinery, not the definition of research quality.

## Operated manuscript products

`manuscript_authoring` is the one-button, local-coverage-first AI-research
authoring path: it freezes a contract and paper-design tokens, routes external
metadata search only after a schema-valid local coverage artifact names a
deficit, then produces auditable LaTeX/PDF and a Markdown-first review packet.
`manuscript_review` is a separate operated run: it consumes frozen authoring
inputs, reconciles capability-review findings, and emits review/rebuttal advice
without changing the authoring run, submitting, or promoting anything to the
vault. Until a signed external scheduler receipt verifier is wired, the review
is explicitly advisory: it never claims external independence or submission
readiness.

## Research Product Standards

- [Paper reading standard and Markdown template](docs/PAPER-READING-STANDARD-CN.md)
- [Idea card and scientific-investment template](docs/IDEA-CARD-STANDARD-CN.md)
- [Research and paper progress-report standard](docs/RESEARCH-PROGRESS-REPORT-STANDARD-CN.md)
- [Storage, mode handoff, versioning, and promotion rules](docs/STORAGE-PIPELINE-AND-PROMOTION-CN.md)
- [Deep-research dossier author/review/repair convergence](docs/RESEARCH-DOSSIER-CONVERGENCE-CN.md)

Cross-mode reuse uses `mode-handoff/v2`: each operated mode declares its semantic
`product_version`, accepted upstream products, primary Markdown, and reusable artifacts in
`orchestrator/mode_registry.yaml`. The handoff manifest records relative paths, SHA-256 hashes,
artifact/schema versions, run status, and delivery status. It verifies transport integrity without
re-running upstream scientific review.

## Domain generality (hard rule)

Serves **computer-science / AI research in general** — NOT one domain. Medical-imaging prompt-based
segmentation is just **one profile** (`profiles/cv-medical-segmentation.profile.yaml`). All
domain-specific invariants live in pluggable **domain profiles** (`profiles/*.yaml`), never hardcoded
into the control plane or agents.

## Layout

```
research_agent_teams/
├── schemas/      JSON-Schema artifact contracts (domain-agnostic; live count verified by tests)
├── profiles/     7 pluggable domain profiles (cv-medical-segmentation, cs-nlp-llm, cs-rl, ai-generic, …)
├── tools/        deterministic validators/hashers/checkers — the enforcement primitives (incl. promote_gate)
├── agents/       rostered agent specs; `worker_census` derives the live count and reachability
├── orchestrator/ FSM engine (engine.py) + graph spec + mode registry (27) + router + model/gate policy
├── operate/      step-wise spine + 33-verb CLI (begin / worker / run-dets / commit / brief / report / …)
│                 operate/modes/ = wired mode recipes; REGISTRY is the operated-surface truth
├── reporting/    the two plain-language director reports: brief (before) + report (after)
├── execute/      gated GPU-execution layer (plan offline; live submit/status/pull director-gated) — GPU jobs tested, NOT operated
├── server_monitor/ read-only server status port (query_status only; never submit_job)
├── resources/    shared resource pool — secrets by REFERENCE only (env-var NAMES, never values)
├── workspace/    workspace control-plane registries (stage / skill / bridge / command)
├── gates/        5 human gates — idea-bet / venue-pick / venue-decide / aers-reference-approve
│                 plus the explicit-user director-command promote-to-vault gate
├── hooks/        node PreToolUse guards (permission-scope-guard + artifact-contract-enforcer)
├── projects/     per-project durable workspaces (results/scripts/figures/notes; gitignored) —
│                 created by `operate project-init`, removed whole by `operate project-delete`
└── runs/         run-store: runtime files (ephemeral, gitignored, outside the vault)
                  layout: runs/<project>/<run_id>/ — every new run belongs to a registered project
                  (single source of truth: the vault's 05-registry/project-registry.md)
```

## Build status (the complete form — DONE)

The control plane, the agent roster, the M⇄D seam, the operated mode layer, and
the gated GPU-execute layer are **built and self-tested**. Honest status:
paper reading has now been operated once on a real local PDF; GPU experiment
execution still emits scripts/plans only and has not run a real job because it
needs the director's wired server. Direction-finding runs now expose a human
Markdown idea-bet page before the human gate. See `PLATFORM-FACTS.md` for the
current by-the-numbers status.

Phase 01 release evidence was accepted only when the final full-suite JUnit and
the before/after current-source SHA-256 snapshots agreed (paired files, plus real-Windows-PDF,
immutable-Docker-Linux, AI-evaluation, security, route and completion evidence). Those files lived
under `.planning/evidence/phase-01/`; the whole `.planning/` tree is no longer in the working tree and
stays readable in git history up to commit `af9d8ea`.
This verifies the concrete recipes and their boundaries; it does not claim a
real research manuscript run, GPU execution, autonomous submission, or external
independent-review verification.

Historical business-output status (2026-08-03 `operate scoreboard --no-manual`): `overall_status =
machine_clean`, 45 runs in the store, **31 completed operated runs → 7 PASS / 12 advisory / 12 FAIL**,
where **all 12 FAILs are legacy pre-product-contract runs and 0 fail under the current contract**. The
12 are listed by name in `legacy_failure_run_ids`; clearing them requires a scientific rerun, not a
cosmetic Markdown upgrade. `machine_clean` is a statement about the machine's contracts, never a
scientific result.

- [x] **M0** — control plane: schemas + validator + canonical hash-chain + ledger + run-store + checkpoint/resume + FSM + routing + budget + observability + permission-scope/contract hooks + spine engine + foundation hardening
- [x] **M1–M2** — the agent roster (1 orchestrator + worker role-specs) + the deterministic checker tools behind every hard gate (breadth + depth modes)
- [x] **M3** — full 7-stage spine across all modes; **M3.5** — the M⇄D seam (recall by reference + promote-to-vault re-derivation), domain generality, two-repo git
- [x] **operate layer** — one-button step-wise driver + CLI (live mode set comes only from `operate/modes/REGISTRY`); **execute layer** — gated GPU runner (plan/submit/status/pull)
- [x] **governance / GPU / QC hardening (2026-06-10; promotion invocation updated 2026-07-14)** — director-veto recording + unresumable rejected runs; promote-gate entrypoint that self-derives from sha-verified audits + writes the ledger; always-on machine-root vault guard; idea/venue gates remain `disable-model-invocation`, while promotion runs only after an explicit top-level user source-command invocation; remote-exec injection / pull-fence / host-key fixes; 8 QC-tool correctness fixes. See `_design/remediation-2026-06-10-governance-gpu-qc-hardening.md`.
- [x] **absorption wave 1 (2026-06-10)** — landscape-scan absorption of 18 verified external patterns, constitution intact: live scholarly retrieval (`tools/paper_search.py` + `scholar_clients` + three-state `citation_existence`, free-first, no Sci-Hub) · optional PaperQA2 wrapper + deterministic retraction check (`fulltext_qa`) · bounded in-stage repair (`operate/bounded_repair.py`, wires the dead `debug_retries` counter) + AIDE `solution_tree` + RD-Agent `experiment_feedback` · real pairwise-debate Elo/Swiss tournament (`idea_dedup` + `elo_tournament`) · SPECS-lite review calibration (`review_calibration`) + optional decorrelated OpenReviewer seat + 2 ScholarPeer VERIFY agents (baseline-scout / sub-domain-historian) · ScholarEval score-only `idea_grounding` + retrieval-grounded novelty signal · TEMPR 4-channel RRF recall rebuild · Graphiti bi-temporal claim/comparison fields + vault BITEMPORAL lint + `invalidation_record` · operate REGISTRY 1→4 modes (+ new `deep_research`, both dead budget counters live) · 5 adapted K-Dense method skills under `skills/`. See `_design/research-agent-teams-absorption-wave1-build-contract.md` + the build record.
- [x] **absorption wave 2 (2026-09-05)** — the SciPhi AgentSearch retrieval recipe, clean-room over the existing free channels (`tools/search_funnel.py`: per-source broad recall → cross-channel Reciprocal Rank Fusion → best-passage rerank via one batched OpenAlex abstract request → citation/recency authority blend, plus a depth×breadth recursive related-query expansion whose stop is never a saturation verdict; `paper_search.search` now also returns each provider's own `channel_rankings`). The hosted SciPhi API, the Sensei-7B model and the 1.26 TB AgentSearch-V1 dataset were NOT absorbed — the service was unreachable on 2026-09-05. Director decision the same day: the funnel runs inside `operate pre-search` by default (depth 1 everywhere, depth 2 in `deep_research`; `--no-funnel` opts out), folding `funnel_rank` / `funnel_score` / `related_queries` into `search-results.json` and the passage snippets into `search-funnel.json`. Record: `_design/2026-09-05-agent-search-absorption-CN.md`.

Run the self-tests **from this directory** (`research_agent_teams/`):

```
python -m pytest tests/ -q          # run from the workspace root; trust current terminal evidence only
```

The machine's tests were consolidated into the workspace `tests/` home on 2026-08-13 — this machine's
core harness now lives at `tests/machine/`. Run from anywhere else and collection errors are a wrong
cwd, not a red suite.
