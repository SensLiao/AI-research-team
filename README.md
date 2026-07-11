# Research Agent Teams (the machine)

> Current status source (2026-07-10): see `PLATFORM-FACTS.md`. The operated
> surface is 10 modes, the roster is 140 agents (134 scientific workers), and
> Codex worker specs/logs carry
> model-agnostic `capability_requirements`; optional concrete runtime fields are
> supplied only by deployment environment bindings. In addition,
> `read_paper_deep` has one historical real local-PDF smoke run plus a staged
> 20-worker A-core paper-reading panel. Evidence modes use methodology-derived
> source quality, semantic search traces, exact-span attribution, and independent
> citation audit. `new_direction` / `deep_ideation` expose a
> Markdown-first `/idea-bet` decision page at `director-review/ideas/idea-bet-menu.md`.
> GPU experiment execution remains server-gated and not operated.

The **agent team itself**: its configuration, its control plane, and everything it produces while
running. This is one of **two cleanly separated systems**:

| System | Directory | Role |
|---|---|---|
| **Research Agent Teams** (this) | `research_agent_teams/` | THE MACHINE — agent roster + config + control plane + run outputs |
| **PhD-Research-OS** | `AI agent database/PhD-Research-OS/` | THE RESEARCH DATABASE — validated knowledge (the vault) |

> They must NOT be mixed. They connect at exactly **one seam**: the machine *reads* the database
> by reference (recall) and *promotes* vetted artifacts INTO it through a human gate. Nothing else
> crosses. Full design: `_design/research-agent-teams-complete-blueprint-v1.md`.

## What this is (and is NOT)

Built **scientific-output-first**: independent workers gather evidence, read papers, prosecute gaps,
compare ideas, design and analyze experiments, then write mode-specific Markdown for a researcher.
The state machine, schemas, scheduler, receipts, and gates exist to keep those products honest; they
are supporting machinery, not the definition of research quality.

## Research Product Standards

- [Paper reading standard and Markdown template](docs/PAPER-READING-STANDARD-CN.md)
- [Idea card and scientific-investment template](docs/IDEA-CARD-STANDARD-CN.md)
- [Research and paper progress-report standard](docs/RESEARCH-PROGRESS-REPORT-STANDARD-CN.md)
- [Storage, mode handoff, versioning, and promotion rules](docs/STORAGE-PIPELINE-AND-PROMOTION-CN.md)

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
├── schemas/      JSON-Schema artifact contracts (domain-agnostic; current count is verified by tests)
├── profiles/     pluggable domain profiles (cv-medical-segmentation, nlp-text-classification, ai-generic)
├── tools/        deterministic validators/hashers/checkers — the enforcement primitives (incl. the promote_gate)
├── tests/        REAL pytest for every tool — no "passes" without terminal evidence
├── agents/       agent .md specs — the team roster (1 orchestrator + worker role-specs)
├── orchestrator/ FSM engine (engine.py) + graph spec + mode registry + routing resolver + model policy
├── operate/      step-wise spine + CLI the orchestrator skill drives (begin / run-dets / commit / reject / status / menu)
├── execute/      gated GPU-execution layer (plan offline; live submit/status/pull director-gated) — GPU jobs tested, NOT operated
├── gates/        the 4 human gates (idea-bet / promote-to-vault / venue-pick / venue-decide) — disable-model-invocation
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

Current local verification on 2026-07-11: `3062 passed`. The historical business-output
scoreboard remains deliberately blocked: 45 completed operated runs predate the current
mode-specific Markdown and scientific-truth contracts and must be rerun, not cosmetically upgraded.

- [x] **M0** — control plane: schemas + validator + canonical hash-chain + ledger + run-store + checkpoint/resume + FSM + routing + budget + observability + permission-scope/contract hooks + spine engine + foundation hardening
- [x] **M1–M2** — the agent roster (1 orchestrator + worker role-specs) + the deterministic checker tools behind every hard gate (breadth + depth modes)
- [x] **M3** — full 7-stage spine across all modes; **M3.5** — the M⇄D seam (recall by reference + promote-to-vault re-derivation), domain generality, two-repo git
- [x] **operate layer** — one-button step-wise driver + CLI (10 operated modes); **execute layer** — gated GPU runner (plan/submit/status/pull)
- [x] **governance / GPU / QC hardening (2026-06-10)** — director-veto recording + unresumable rejected runs; promote-gate entrypoint that self-derives from sha-verified audits + writes the ledger; always-on machine-root vault guard + the 4 gates installed as real `disable-model-invocation` commands; remote-exec injection / pull-fence / host-key fixes; 8 QC-tool correctness fixes. See `_design/remediation-2026-06-10-governance-gpu-qc-hardening.md`.
- [x] **absorption wave 1 (2026-06-10)** — landscape-scan absorption of 18 verified external patterns, constitution intact: live scholarly retrieval (`tools/paper_search.py` + `scholar_clients` + three-state `citation_existence`, free-first, no Sci-Hub) · optional PaperQA2 wrapper + deterministic retraction check (`fulltext_qa`) · bounded in-stage repair (`operate/bounded_repair.py`, wires the dead `debug_retries` counter) + AIDE `solution_tree` + RD-Agent `experiment_feedback` · real pairwise-debate Elo/Swiss tournament (`idea_dedup` + `elo_tournament`) · SPECS-lite review calibration (`review_calibration`) + optional decorrelated OpenReviewer seat + 2 ScholarPeer VERIFY agents (baseline-scout / sub-domain-historian) · ScholarEval score-only `idea_grounding` + retrieval-grounded novelty signal · TEMPR 4-channel RRF recall rebuild · Graphiti bi-temporal claim/comparison fields + vault BITEMPORAL lint + `invalidation_record` · operate REGISTRY 1→4 modes (+ new `deep_research`, both dead budget counters live) · 5 adapted K-Dense method skills under `skills/`. See `_design/research-agent-teams-absorption-wave1-build-contract.md` + the build record.

Run the self-tests (from the case-for-research dir):

```
python -m pytest research_agent_teams/tests/ -q
```
