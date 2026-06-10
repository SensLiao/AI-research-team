# Research Agent Teams (the machine)

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

Built **control-plane-first**: the system core is a state-machine + artifact schemas + permission
scopes + hash-ledger + hard gates + observability. **Agents are controlled workers, not the system
itself.** We build + test the machine before operating it on real research.

## Domain generality (hard rule)

Serves **computer-science / AI research in general** — NOT one domain. Medical-imaging prompt-based
segmentation is just **one profile** (`profiles/cv-medical-segmentation.profile.yaml`). All
domain-specific invariants live in pluggable **domain profiles** (`profiles/*.yaml`), never hardcoded
into the control plane or agents.

## Layout

```
research_agent_teams/
├── schemas/      JSON-Schema artifact contracts (domain-agnostic) — 86 schemas
├── profiles/     pluggable domain profiles (cv-medical-segmentation, nlp-text-classification, ai-generic)
├── tools/        deterministic validators/hashers/checkers — the enforcement primitives (incl. the promote_gate)
├── tests/        REAL pytest for every tool — no "passes" without terminal evidence
├── agents/       agent .md specs — the team roster (1 orchestrator + worker role-specs)
├── orchestrator/ FSM engine (engine.py) + graph spec + mode registry + routing resolver + model policy
├── operate/      step-wise spine + CLI the orchestrator skill drives (begin / run-dets / commit / reject / status / menu)
├── execute/      gated GPU-execution layer (plan offline; live submit/status/pull director-gated) — tested, NOT operated
├── gates/        the 4 human gates (idea-bet / promote-to-vault / venue-pick / venue-decide) — disable-model-invocation
├── hooks/        node PreToolUse guards (permission-scope-guard + artifact-contract-enforcer)
└── runs/         run-store: runtime files (ephemeral, gitignored, outside the vault)
```

## Build status (the complete form — DONE)

The control plane, the agent roster, the M⇄D seam, and the gated GPU-execute layer are **all built and
self-tested**. M3 is the designed final form (there is no M4). Honest status: **tested, NOT operated** on
real research — the GPU-execute layer emits the scripts but has never run a real job (it needs the
director's wired server). See `RESEARCH-SYSTEM-OVERVIEW.md` for the full by-the-numbers status.

- [x] **M0** — control plane: schemas + validator + canonical hash-chain + ledger + run-store + checkpoint/resume + FSM + routing + budget + observability + permission-scope/contract hooks + spine engine + foundation hardening
- [x] **M1–M2** — the agent roster (1 orchestrator + worker role-specs) + the deterministic checker tools behind every hard gate (breadth + depth modes)
- [x] **M3** — full 7-stage spine across all modes; **M3.5** — the M⇄D seam (recall by reference + promote-to-vault re-derivation), domain generality, two-repo git
- [x] **operate layer** — one-button step-wise driver + CLI (new_direction wired); **execute layer** — gated GPU runner (plan/submit/status/pull)
- [x] **governance / GPU / QC hardening (2026-06-10)** — director-veto recording + unresumable rejected runs; promote-gate entrypoint that self-derives from sha-verified audits + writes the ledger; always-on machine-root vault guard + the 4 gates installed as real `disable-model-invocation` commands; remote-exec injection / pull-fence / host-key fixes; 8 QC-tool correctness fixes. See `_design/remediation-2026-06-10-governance-gpu-qc-hardening.md`.
- [x] **absorption wave 1 (2026-06-10)** — landscape-scan absorption of 18 verified external patterns, constitution intact: live scholarly retrieval (`tools/paper_search.py` + `scholar_clients` + three-state `citation_existence`, free-first, no Sci-Hub) · optional PaperQA2 wrapper + deterministic retraction check (`fulltext_qa`) · bounded in-stage repair (`operate/bounded_repair.py`, wires the dead `debug_retries` counter) + AIDE `solution_tree` + RD-Agent `experiment_feedback` · real pairwise-debate Elo/Swiss tournament (`idea_dedup` + `elo_tournament`) · SPECS-lite review calibration (`review_calibration`) + optional decorrelated OpenReviewer seat + 2 ScholarPeer VERIFY agents (baseline-scout / sub-domain-historian) · ScholarEval score-only `idea_grounding` + retrieval-grounded novelty signal · TEMPR 4-channel RRF recall rebuild · Graphiti bi-temporal claim/comparison fields + vault BITEMPORAL lint + `invalidation_record` · operate REGISTRY 1→4 modes (+ new `deep_research`, both dead budget counters live) · 5 adapted K-Dense method skills under `skills/`. See `_design/research-agent-teams-absorption-wave1-build-contract.md` + the build record.

Run the self-tests (from the case-for-research dir):

```
python -m pytest research_agent_teams/tests/ -q     # 1753 green (pre-wave) → see build record for the wave-1 count
```
