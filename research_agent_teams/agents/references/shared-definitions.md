# Shared Definitions — Authoritative Single Source of Truth

> This file is the **single authoritative source** for cross-agent definitions that appear inline
> in multiple agent specs. Agents MUST remain self-contained (keep their inline copy for prompt
> completeness), but MUST point to this file as the authoritative reference to prevent drift.
>
> Maintainer: update this file first; then mirror any semantic change into every agent that
> carries the inline copy (search for `(authoritative shared definition: references/shared-definitions.md)`).
>
> Last revised: 2026-06-12 (spec_version 1.1.0 baseline)

---

## 1. `claim_support` — Source Grading Scale

Four-tier grading of how strongly a source supports the specific research claim under investigation.
Grade is assigned per (source, query) pair — the same source can carry different grades for
different queries.

| Value | Meaning |
|---|---|
| `strong` | The source directly demonstrates, measures, or proves the specific claim; the link is explicit and traceable (e.g. a benchmark number, ablation result, or formal proof). |
| `moderate` | The source provides relevant evidence that is related to the claim but does not directly prove it (e.g. a closely analogous result, a study in a related domain, or indirect corroboration). |
| `weak` | The source is tangentially related or provides only background context; it cannot carry the claim on its own. |
| `none` | The source was gathered for search coverage but has no meaningful support for this specific claim. |

**Usage discipline:**
- Assign `claim_support` based on what the source demonstrates for the SPECIFIC query, not
  on the source's general prestige, citation count, or relevance to the broader topic.
- `strong` requires that you can trace an explicit evidence path (section, figure, metric, or proof)
  from the source to the claim. If you cannot trace it, cap at `moderate`.
- `evidence-verifier`'s deterministic floor requires ≥1 `strong` source; inflating grades to pass
  this gate is a deliberate violation of the evidence contract.

*(authoritative shared definition — inline copies in: `lit-scout.md`, `evidence-verifier.md`,
`claim-extractor.md`, `claim-evidence-linker.md`, `claim-strength-calibrator.md`)*

---

## 2. `gap_type` — 7-Taxonomy of Research Gaps

Canonical seven-type taxonomy as implemented in `tools/classify_gap.py`.
**The tool decides the type from signal fields — agents never hand-set `gap_type`.**
Precedence order (first match wins) matches the tool implementation.

| Priority | `gap_type` | One-line definition | Key signal fields |
|---|---|---|---|
| 1 | `transfer_gap` | A cross-domain applicability gap: a method, finding, or result from one domain has not been tested or applied in a target domain. | `source_domain` + `target_hook` |
| 2 | `assumption_gap` | An assumption underlying existing work that has been challenged or remains empirically untested. | `challenged_assumption` |
| 3 | `methodological_gap` | A weakness or missing element in current methodology that limits validity, reproducibility, or scope. | `locus` + `opportunity` |
| 4 | `coverage_gap` | An unexplored region or white space in the research landscape — a question nobody has asked. | `hole` OR `white_space_present` |
| 5 | `evidence_gap` | A claim that is widely cited or assumed but lacks direct empirical evidence. | `under_evidenced` |
| 6 | `empirical_gap` | A condition, dataset, or experimental setting that has never been benchmarked or tested. | `untested_condition` OR `untested_dataset` |
| 7 | `stated_open_problem` | A future-work direction explicitly named by the authors of a source paper (lowest-specificity fallback). | `statement` + `source_ref` (non-empty) |

**Usage discipline:**
- Always call `classify_gap(signal)` — never assign `gap_type` in prose.
- A signal that matches no rule causes the tool to raise `ValueError`; diagnose the missing fields
  rather than soft-assigning a type.
- Low novelty score does not change the type; the type is purely structural (signal-driven).

*(authoritative shared definition — inline copies in: `gap-classifier.md`, `novelty-scorer.md`,
`landscape-mapper.md`, `white-space-mapper.md`, `future-work-miner.md`)*

---

## 3. `severity` — Finding Severity Levels (Review / Audit Agents)

Used by review-panel agents (`methodology-reviewer`, `domain-reviewer`, `scientific-critic`,
`baseline-scout`, `figure-vlm-critic`, `monitor`) to classify the urgency of a finding.

| Value | Meaning | Gate effect |
|---|---|---|
| `BLOCK` | A finding that prevents synthesis from advancing; must be addressed or explicitly rebutted before the review panel can emit APPROVE. Typically a hard invariant violation, a missing crucial proof, or a fatal flaw in the experimental design. | `overall_verdict` = BLOCK (derived, not set by hand). `rebuttal_required: true`. |
| `WARN` | A significant concern that should be addressed but does not categorically prevent APPROVE; the synthesizer may APPROVE with documented caveats if the WARN is acknowledged. | Surfaces in the synthesizer's `addressed_blocks`; does not force BLOCK on its own. |
| `NOTE` | An advisory observation or minor improvement suggestion; does not affect the verdict path. | Informational only; appears in the review output for the director. |

**Usage discipline:**
- Severity is set by the reviewing agent based on domain profile invariants and the evidence;
  it is NEVER softened post-hoc to make synthesis easier (anti-sycophancy guard).
- For `figure-vlm-critic` and `monitor`, severity levels use lowercase (`critical`, `warn`, `info`)
  per their schemas — same conceptual tiers, schema-matched casing.
- A `BLOCK` severity from ANY reviewer in the panel is sufficient for the synthesizer to emit BLOCK
  unless the `scientific-critic` certifies the finding as a duplicate or cross-panel contradiction
  already resolved.

*(authoritative shared definition — inline copies in: `methodology-reviewer.md`, `domain-reviewer.md`,
`scientific-critic.md`, `baseline-scout.md`)*

---

## 4. `evidence_ref` — Citation / Provenance Discipline

`evidence_ref` is a list of non-empty strings, each resolving to a real upstream artifact or source.
`minItems: 1` is enforced by schema on every artifact type that carries it.

| Form | When to use | Example |
|---|---|---|
| Artifact path | When referencing a run artifact produced in this run | `runs/<run>/evidence/DISCOVER/evidence-table.artifact.json` |
| Artifact ID | When the artifact's `artifact_id` field is known | `evidence-table-20260612-abc123` |
| `[[slug]]` + sha | When referencing a DB knowledge page (vault) by its slug | `[[example-ablation-2026]]+sha:a1b2c3` |
| DOI / arXiv ID | When referencing an external paper | `10.1234/example` or `arXiv:2409.04109` |
| URL | Fallback for web sources with no DOI | Full URL, stable if possible |

**Hard rules:**
- An `evidence_ref` that does not resolve to a real, locatable artifact or source is **fabrication**.
  The `citation-integrity-auditor` and `citation_existence.py` gate check this; fabrication is
  structurally blocked.
- `evidence_ref: []` (empty list) violates `minItems: 1` and is schema-rejected.
- Agents MUST NOT leave `evidence_ref` empty to meet a deadline — if a real reference cannot be
  found, the artifact must not be emitted (BLOCK).
- References to vault items use `[[slug]]` syntax; the DB's access model (read-only for the machine)
  and the `tools/recall.py` bridge govern retrieval.

*(authoritative shared definition — inline copies in: `lit-scout.md`, `gap-classifier.md`,
`novelty-scorer.md`, `claim-extractor.md`, `claim-evidence-linker.md`, `evidence-verifier.md`,
`citation-integrity-auditor.md`, `idea-tournament-ranker.md`, `idea-evolver.md`)*
