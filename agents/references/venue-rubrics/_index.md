# Venue Rubric KB — Index

> Part of the CLUSTER D1 rubric knowledge base. `venue-selector` loads this index first,
> then fetches the per-tier file on demand. Kept thin so context stays bounded.

## How to use

1. Identify `tier` and `paper_type` for the target venue.
2. Load the corresponding per-tier file.
3. Load `rubric-7d.md` for the full 7-dimension anchor table.
4. Load `reject-triggers.md` + `anti-bias-suppressors.md` always.

---

## Venue → Tier + Default Paper-Type + Rubric File

| Venue              | Tier      | Default paper_type       | Rubric file           | Login-state re-check needed? |
|--------------------|-----------|-------------------------|-----------------------|------------------------------|
| NeurIPS            | `conf`    | `methodological`        | `tier1-conf-ml.md`    | No (public review guidelines) |
| ICML               | `conf`    | `methodological`        | `tier1-conf-ml.md`    | No |
| ICLR               | `conf`    | `methodological`        | `tier1-conf-ml.md`    | No (OpenReview public) |
| CVPR               | `conf`    | `methodological`        | `tier1-conf-ml.md`    | No |
| ICCV               | `conf`    | `methodological`        | `tier1-conf-ml.md`    | No |
| ECCV               | `conf`    | `methodological`        | `tier1-conf-ml.md`    | No |
| MICCAI             | `med`     | `methodological`        | `tier2-med-imaging.md`| **YES — MICCAI CMT review form changes annually; re-check before submission** |
| TMI                | `med`     | `methodological`        | `tier2-med-imaging.md`| **YES — IEEE TMI reviewer guidelines are login-gated** |
| MedIA              | `med`     | `methodological`        | `tier2-med-imaging.md`| **YES — Elsevier MedIA guide-to-referees is login-gated** |
| Nature             | `journal` | `methodological`        | `tier3-journal.md`    | **YES — Nature guide-to-referees requires login; verify verbatim before citing** |
| Nature Methods     | `journal` | `methodological`        | `tier3-journal.md`    | **YES — login-gated; unfair-benchmark clause especially needs re-check** |
| Nature Medicine    | `journal` | `application-clinical`  | `tier3-journal.md`    | **YES — login-gated; human-evidence requirement must be re-confirmed** |
| TPAMI              | `journal` | `methodological`        | `tier3-journal.md`    | **YES — IEEE TPAMI maturity/extension standard from second-hand guide; re-check** |

---

## Notes on confidence

- `tier1-conf-ml.md` anchors: **HIGH** confidence — sourced from public review guidelines
  (NeurIPS Reviewer Guide, ICML Reviewer Guidelines, ICLR public OpenReview rubric,
  CVPR/ICCV/ECCV reviewer instructions). Verbatim where possible.
- `tier2-med-imaging.md` MICCAI section: **MEDIUM** confidence — MICCAI review form
  changes year-to-year; login-state verification recommended before submission.
- `tier2-med-imaging.md` TMI/MedIA sections: **MEDIUM** confidence — reconstructed from
  scope pages + SIER framework + parity with public sources; login-gated originals
  should be consulted.
- `tier3-journal.md` Nature-family: **HIGH** for referee-7-questions structure (canonical
  reconstruction); **MEDIUM-HIGH** for specific numeric thresholds. Login-state verbatim
  check REQUIRED before citing in `venue_profile`.
- `tier3-journal.md` TPAMI: **MEDIUM** — maturity/extension standard from second-hand
  reviewer guides; re-check against current IEEE author instructions.

---

## Quick decision table: paper_type rocker

| paper_type             | D7 active? | D3 scope gate? | Validation bar |
|------------------------|-----------|----------------|----------------|
| `methodological`       | OFF (N/A) | venue-specific | Small sample / PoC acceptable for conf; higher for journal |
| `application-clinical` | ON (gating for med/Nature Medicine) | Strict (no method advance → reject at TMI/MedIA) | Multi-center / external validation required for application papers |

---

## Files in this KB

| File                      | Content |
|---------------------------|---------|
| `_index.md`               | This file — venue routing table |
| `tier1-conf-ml.md`        | NeurIPS / ICML / ICLR / CVPR-ICCV-ECCV anchors |
| `tier2-med-imaging.md`    | MICCAI / TMI / MedIA — paper_type two-track + hard scope gate |
| `tier3-journal.md`        | Nature-family / TPAMI — D5 forced, D2 gating, maturity |
| `reject-triggers.md`      | 7 reject-triggers + empirical top-reject causes |
| `anti-bias-suppressors.md`| 6 not-valid-grounds for rejection (all tiers) |
| `rubric-7d.md`            | 7 dimensions + 1-4 anchors + ACCEPT/STRONG-ACCEPT derivation |
