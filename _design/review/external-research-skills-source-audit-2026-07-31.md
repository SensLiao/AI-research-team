# External research skills source audit — 2026-07-31

Status: `SOURCE_AUDIT_COMPLETE / NINE_SOURCE_LOCKED / SELECTIVE_OVERLAY_IMPLEMENTED / THIRD_PARTY_RUNTIME_NOT_EXECUTED`

Local review root:
`C:\Users\廖神\Desktop\Honor degree\.tmp\research-agent-skills-review\2026-07-31`

The nine repositories were cloned only for source review. No installer, hook, dependency manager,
MCP server, cloud runner, downloader, browser automation, or third-party research script was executed.
The production machine does not import these repositories. Selected ideas are represented by short
clean-room summaries in `orchestrator/research_capability_overlays.json`.

Machine-readable source lock:
`orchestrator/external_research_skill_sources.json`. It freezes all nine repositories, the selected
repository-relative review paths and SHA-256 values, license/copy policy, admission status, and complete
per-repository `SKILL.md` counts.
The authoritative count is **359** (`129` automatic-research + `45` trusted-assistant + `4` deep-research
+ `158` AI-for-Science + `4` visualization + `19` Nature-expression).

An earlier filesystem inspection reported `201` because `scientific-agent-skills` was materialized as a
root-only sparse worktree: its 158 indexed `skills/**/SKILL.md` files were not visible. Sparse checkout was
disabled without changing HEAD; the worktree and index now both contain 158 files and the nine-repository
total is 359. The old 201 figure is not a valid repository inventory.

## Source inventory

| Repository | Fixed HEAD | Skills | License finding | Admission / implementation |
|---|---|---:|---|---|
| `Orchestra-Research/AI-research-SKILLs` | `773a52944ba4747a18bd4ae9ade53fff041adcbc` | 98 | MIT | `concept_only / guidance_only`: ideation trajectory and outer/inner research loop |
| `Galaxy-Dawn/claude-scholar` | `2f7766fd541a723d4ddc6230b3277f948d61b093` | 45 | MIT | `concept_only / guidance_only`: results-to-claim discipline; reject hooks/global behavior |
| `Imbad0202/academic-research-skills` | `2cf3a51e159458b7a8c8784bb874248e79601f7b` | 4 | CC BY-NC 4.0 | `concept_only / guidance_only`: independent clean-room reimplementation; no code or long-text copy |
| `lingzhi227/agent-research-skills` | `9e6c085d65e313e475e921fdfe795ac11eb7589e` | 31 | no repository license found (`NOASSERTION`) | `concept_only_no_code / guidance_only`: clean-room math↔code↔number provenance |
| `K-Dense-AI/scientific-agent-skills` | `ab2f84ab10597c59fac186ecda6d5edd5dcc8b92` | 158 | MIT | `selective_concept_only / guidance_only`: hypothesis, power, DICOM, and figure-export guidance; scripts remain candidates |
| `Haojae/scipilot-figure-skill` | `43098ddb9e6a6d142218540c114f9ed38922fc42` | 1 | MIT | `layout_and_export_qa_concepts_only / guidance_only` |
| `bahayonghang/drawio-skills` | `27dac02ce3b4901c844aaa623ad64c3d577c3a72` | 2 | MIT plus bundled notices | `offline_adapter_concept / planned_adapter`; no renderer is installed or operated |
| `icebird1998/drawio-scientific-illustrator` | `9bbeca93ffd134a29bfc90023f22c65359efe584` | 1 | MIT | `rejected_live_control / rejected / selectable:false`: legacy CDP/live-control path duplicates safer offline route |
| `Yuan1z0825/nature-skills` | `cc29e56abcd14e6f8fb6a7b065208a051397f47a` | 19 | Apache-2.0 | `selective_rubric_concepts_only / guidance_only`; no published-asset copy |

Every selected source is file-hash-bound in the machine lock. The rejected illustrator is retained in
that nine-source ledger with `selectable:false`; catalog validation fails if an overlay references it.
The historical audit did not record a source-read receipt, so it cannot prove whether the original
review used materialized files, object reads, or repository metadata. The present fully materialized
snapshot independently verifies the locked files at the same commits.

A post-materialization SHA-256 comparison covered 5,640 upstream and 2,038 local text/source files.
It found no non-empty exact copy; the only two matches were empty files. This is exact-copy evidence,
not proof against a transformed derivative, so the license and clean-room policies remain mandatory.

## Selected research capabilities

### 1. Hypothesis and discriminating-prediction contract

Before design or result inspection, record the observation, estimand, focal hypothesis, rival
explanations, predictions that separate them, controls, operationalization, falsifier, and HARKing state.
This strengthens `new_direction`, `deep_ideation`, `design_experiment`, and verification without creating
a second workflow spine.

Primary source locations reviewed:

- `scientific-agent-skills/skills/hypothesis-generation/SKILL.md`
- `scientific-agent-skills/skills/hypothesis-generation/scripts/validate_hypothesis_schema.py`
- `scientific-agent-skills/skills/hypothesis-generation/scripts/validate_prediction_matrix.py`
- `AI-research-SKILLs/21-research-ideation/*`

### 2. Power and unit-of-analysis contract

Freeze the independent unit, patient/cluster/repeated-measure structure, estimand, multiplicity, dropout,
effect-size provenance, and an a-priori power or sensitivity rationale. Observed power is not accepted as
validation. Generic calculations never override the medical-imaging patient-level analysis contract.

### 3. Results-to-claim bundle

Every proposed claim must name its source result, analysis population, estimator, uncertainty,
assumptions, contradictory evidence, allowed wording, and decision status. It consumes receipt-bound raw
results; it cannot manufacture results or raise evidence strength.

### 4. Blind handoff and independent review

The useful mechanism is payload-only blindness with strict envelopes and explicit agreement,
disagreement, and transport-failure states. A synthesizer cannot silently repair a dissenting owner's
finding. Because the reviewed implementation is CC BY-NC, this mechanism must be independently
reimplemented rather than copied.

### 5. Submission freshness and persuasion invariance

Review evidence must bind the exact manuscript/figure/venue hashes and expire after material edits.
Scientific verdicts should remain invariant when only persuasive tone changes. Claim-auditor calibration
must measure both false negatives and false positives rather than accepting a self-asserted PASS.

### 6. DICOM inventory and de-identification audit

The reviewed `pydicom` tools are candidates for isolated, explicit local use after fixture tests and
license preservation. Their role is metadata inventory and PHI/de-identification evidence. They do not
diagnose, certify anonymization, overwrite clinical inputs, or upload patient data.

### 7. Quantitative figure and scientific diagram outputs

- Quantitative figures remain Python/R products driven by the statistical design and frozen result table.
- SciPilot contributes deterministic export, layout, font, DPI, and file checks; its heuristic chart
  recommender is not a scientific decision engine.
- Nature contributes a claim-first figure contract and statistics/caption checklist, not a renderer.
- `drawio-skills` is the only admitted diagram-renderer candidate: offline YAML canonical, allowlisted
  arguments, fixed workdir, and input/output receipts. MCP, `npx @latest`, live backend, and auto-update are
  forbidden.
- The legacy live-CDP illustrator and OpenRouter image route are rejected.

### 8. Methods and reviewer overlays

Methods writing uses a motivation → mechanism → evidence triad. Any claimed advantage must bind a real
experiment or be marked unvalidated. Manuscript review keeps contribution, methodology, statistics,
reproducibility, figures, citations, ethics, and claim calibration as independently evidenced axes before
synthesis; one worker does not impersonate multiple independent reviewers.

## Explicit rejections

The following do not enter the default or automatic path:

- whole-repository skill installation or global skill synchronization;
- Claude/Codex hooks that force skill selection or scan conversations into research memory;
- Zotero/Obsidian writes as a second knowledge base;
- plaintext key files, credential ingestion, or API-key propagation;
- Crossref/arXiv/Semantic Scholar metadata similarity as citation-entailment truth;
- “no overlap found” as proof of novelty;
- generic experiment generators that omit split leakage, estimand, independent unit, baseline fairness,
  and falsifiers;
- automatic pip/curl/npx installation, cloud execution, OpenRouter/Gemini figure generation, live CDP,
  or unpublished-data egress;
- copying code or prompt text from no-license or non-commercial-only sources into the runtime.

## Implemented integration boundary

The single entry remains `research-orchestrator`. `tools/research_capability_router.py` selects an existing
mode plus two to five curated overlays. The plan is hash-pinned in the task frame and stage-filtered by the
panel scheduler. It is advisory: it cannot add workers, tools, network, permissions, or vault writes.

Current runtime proof is limited to local contract tests. The DICOM tools, figure exporter, and offline
draw.io adapter are candidates, not operated production dependencies, until their isolated fixture and
dependency tests exist.
