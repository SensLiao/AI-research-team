# P6 provenance audit - 2026-06-26

Scope: the 66-paper P6 set captured at the start of this audit from `git -C "AI agent database/PhD-Research-OS" diff --name-only` under `02-wiki/papers/`. A later Git index refresh showed only the 12 metadata corrections from this corrective pass as active file diffs, so this note preserves the captured 66-paper provenance ledger explicitly.

Purpose: make the P6 backfill quality account explicit after the director asked whether the original PDFs had actually been read.

Definitions:
- `PDF-confirmed`: prior P6 worker explicitly reported raw-PDF/PDF-anchored reading, or the page itself carried PDF-anchored evidence before this pass.
- `extracted-fulltext-confirmed`: a local extracted fulltext markdown was available and used as the source basis, but this is not counted as original-PDF reading.
- `wiki-only / uncertain`: the P6 card was previously based on existing wiki/web notes, or had missing/web-only source metadata, and therefore required a corrective PDF spot-check.

## Initial three-bucket ledger

### PDF-confirmed (8)

| Slug | Evidence basis |
|---|---|
| `ma-2023-medsam` | Prior worker explicitly reported raw PDF use. |
| `medsam2-2025` | Prior worker explicitly reported raw PDF use. |
| `medsam3-2025` | Prior worker explicitly reported raw PDF use. |
| `chen-2025-sam3-adapter` | Prior worker explicitly reported raw PDF use. |
| `tejero-2025-sam-da` | Prior worker explicitly reported raw PDF use. |
| `cheng-2024-h-sam` | Local `01-raw` PDF source plus current page PDF-anchored evidence. |
| `zhang-2023-samed` | Local `01-raw` PDF source plus current page PDF-anchored evidence. |
| `chen-2023-sam-adapter` | Local PDF source plus current page states raw-PDF basis. |

### Extracted-fulltext-confirmed (46)

| Slug | Evidence basis |
|---|---|
| `alignsam-2024` | Local extracted fulltext `raw/papers/alignsam-2024.md`. |
| `biomedparse-zhao-2025` | Local extracted fulltext `raw/papers/biomedparse-zhao-2025.md`. |
| `bolya-2025-perception-encoder` | Local extracted fulltext `raw/papers/bolya-2025-perception-encoder.md`. |
| `canal-net-2022` | Local extracted fulltext `raw/papers/canal-net-2022.md`. |
| `chen-2021-transunet` | Local extracted fulltext `raw/papers/chen-2021-transunet.md`. |
| `chen-2022-adaptformer` | Local extracted fulltext `raw/papers/chen-2022-adaptformer.md`. |
| `dong-2025-xgrammar` | Local extracted fulltext `raw/papers/dong-2025-xgrammar.md`. |
| `du-2023-segvol` | Local extracted fulltext `raw/papers/du-2023-segvol.md`. |
| `flans-2024` | Local extracted fulltext `raw/papers/flans-2024.md`. |
| `hatamizadeh-2021-unetr` | Local extracted fulltext `raw/papers/hatamizadeh-2021-unetr.md`. |
| `hdilemma-2024` | Local extracted fulltext `raw/papers/hdilemma-2024.md`. |
| `he-2024-vista3d` | Local extracted fulltext `raw/papers/he-2024-vista3d.md`. |
| `hu-2021-lora` | Local extracted fulltext `raw/papers/hu-2021-lora.md`. |
| `khanal-2025-gut-vlm-hallucination` | Local extracted fulltext `raw/papers/khanal-2025-gut-vlm-hallucination.md`. |
| `kirillov-2023-segment-anything` | Local extracted fulltext `raw/papers/kirillov-2023-segment-anything.md`. |
| `koleilat-2025-biomedcoop` | Local extracted fulltext `raw/papers/koleilat-2025-biomedcoop.md`. |
| `li-2022-lseg` | Local extracted fulltext `raw/papers/li-2022-lseg.md`. |
| `luddecke-2021-clipseg` | Local extracted fulltext `raw/papers/luddecke-2021-clipseg.md`. |
| `maier-hein-2022-metrics-guideline` | Local extracted fulltext `raw/papers/maier-hein-2022-metrics-guideline.md`. |
| `medical-sam-survey-2023` | Local extracted fulltext `raw/papers/medical-sam-survey-2023.md`. |
| `oquab-2023-dinov2` | Local extracted fulltext `raw/papers/oquab-2023-dinov2.md`. |
| `pmcanalseg-2026` | Local extracted fulltext `raw/papers/pmcanalseg-2026.md`. |
| `pospadunet3d-2023` | Local extracted fulltext `raw/papers/pospadunet3d-2023.md`. |
| `radford-2021-clip` | Local extracted fulltext `raw/papers/radford-2021-clip.md`. |
| `ravi-2024-sam-2` | Local extracted fulltext `raw/papers/ravi-2024-sam-2.md`. |
| `rfmedsam2-2025` | Local extracted fulltext `raw/papers/rfmedsam2-2025.md`. |
| `sam-med3d-eccv-paper` | Local extracted fulltext `raw/papers/sam-med3d-eccv-paper.md`. |
| `sam-med3d-eccv-supplementary` | Local extracted fulltext `raw/papers/sam-med3d-eccv-supplementary.md`. |
| `shao-2026-vmfcoop` | Local extracted fulltext `raw/papers/shao-2026-vmfcoop.md`. |
| `shit-2021-cldice` | Local extracted fulltext `raw/papers/shit-2021-cldice.md`. |
| `sofiiuk-2021-ritm` | Local extracted fulltext `raw/papers/sofiiuk-2021-ritm.md`. |
| `taha-2015-3d-metrics` | Local extracted fulltext `raw/papers/taha-2015-3d-metrics.md`. |
| `toothfairy-challenge-2025` | Local extracted fulltext `raw/papers/toothfairy-challenge-2025.md`. |
| `toothfairy2-challenge-2024` | Local extracted fulltext `raw/papers/toothfairy2-challenge-2024.md`. |
| `u-mamba2-2025` | Local extracted fulltext `raw/papers/u-mamba2-2025.md`. |
| `wang-2019-deepigeos` | Local extracted fulltext `raw/papers/wang-2019-deepigeos.md`. |
| `wang-2023-sam-med3d` | Local extracted fulltext `raw/papers/wang-2023-sam-med3d.md`. |
| `wu-2023-medical-sam-adapter` | Local extracted fulltext `raw/papers/wu-2023-medical-sam-adapter.md`. |
| `wu-2024-zero-shot-prompt-transfer` | Local extracted fulltext `raw/papers/wu-2024-zero-shot-prompt-transfer.md`. |
| `zhou-2021-coop` | Local extracted fulltext `raw/papers/zhou-2021-coop.md`. |
| `carion-2025-sam-3` | Alias extracted fulltext `raw/papers/sam-3-with-concepts-2025.md`. |
| `chen-2025-mimo` | Alias extracted fulltext `raw/papers/mimo-chen-2025.md`. |
| `koleilat-2025-medclip-samv2` | Alias extracted fulltext `raw/papers/medclip-samv2-koleilat-2025.md`. |
| `yuan-2025-tgsam2` | Alias extracted fulltext `raw/papers/tgsam2-yuan-2025.md`. |
| `zhao-2025-biomedparse` | Alias extracted fulltext `raw/papers/biomedparse-zhao-2025.md`. |
| `zhao-2025-sat` | Alias extracted fulltext `raw/papers/sat-zhao-2025.md`. |

### Wiki-only / uncertain before corrective pass (12)

| Slug | Why it was not proven before this pass |
|---|---|
| `gabeur-2026-vision-banana` | Web-ingested page; no local raw PDF. |
| `chen-2024-cat` | `source: ''`; page explicitly said metadata was not yet PDF-verified. |
| `esica-2026` | `source: ''`; arXiv only in metadata. |
| `marinov-2023-guiding-the-guidance` | `source: ''`; web-verified note only. |
| `isegformer-2022` | `source: ''`; deep-read pending. |
| `isensee-2025-nninteractive` | `source: ''`; method/exposure audit pending. |
| `medical-sam3-2026` | arXiv abs only; `arxiv-id` typo in metadata. |
| `prism-2024` | `source: ''`; method pending. |
| `voxtell-2025` | `source: ''`; arXiv metadata only. |
| `zhang-2026-descriptormedsam` | `source: ''`; shorthand title, web note basis. |
| `kirchhoff-2024-skeleton-recall` | Local PDF existed, but there was no prior proof it had been opened. |
| `shi-2024-cbdice` | Local PDF existed, but there was no prior proof it had been opened. |

Count check: 8 + 46 + 12 = 66.

## Corrective PDF spot-check for wiki-only / uncertain pages

During triage, a wider suspected set was source-checked before final classification. The 12 pages below are the final `wiki-only / uncertain` set and the only pages that received metadata corrections in this pass. The check was title/abstract/core-mechanism level for `skimmed` pages; it was not treated as a new deep read.

| Slug | PDF/fulltext opened on 2026-06-26 | Spot-check anchor | Result |
|---|---|---|---|
| `gabeur-2026-vision-banana` | `https://arxiv.org/pdf/2604.20329` | PDF title page: "Image Generators are Generalist Vision Learners"; 30 pages extracted. | Source metadata fixed; no content conflict found. |
| `chen-2024-cat` | `https://arxiv.org/pdf/2406.07085` | PDF title page: "CAT: Coordinating Anatomical-Textual Prompts for Multi-Organ and Tumor Segmentation"; 23 pages extracted. | Source metadata fixed; banner changed from "not PDF verified" to "PDF spot-checked; deep-read pending". |
| `esica-2026` | `https://arxiv.org/pdf/2604.24876` | PDF title page: "ESICA: A Scalable Framework for Text-Guided 3D Medical Image"; 11 pages extracted. | Source metadata fixed; no content conflict found. |
| `marinov-2023-guiding-the-guidance` | `https://arxiv.org/pdf/2303.06942` | PDF title page: "Guiding the Guidance: A Comparative Analysis of User Guidance Signals for Interactive Segmentation of Volumetric Images"; 10 pages extracted. | Source metadata fixed; no content conflict found. |
| `isegformer-2022` | `https://arxiv.org/pdf/2112.11325` | PDF title page: "iSegFormer: Interactive Segmentation via Transformers with Application to 3D Knee MR Images"; 11 pages extracted. | Source metadata fixed; title shorthand remains acceptable. |
| `isensee-2025-nninteractive` | `https://arxiv.org/pdf/2503.08373` | PDF title page: "nnInteractive: Redefining 3D Promptable Segmentation"; 26 pages extracted. | Source metadata fixed; no content conflict found. |
| `medical-sam3-2026` | `https://arxiv.org/pdf/2601.10880` | PDF title page: "Medical SAM3: A Foundation Model for Universal Prompt-Driven Medical Image"; 20 pages extracted. | Source metadata fixed; `arxiv-id` corrected to `2601.10880`. |
| `prism-2024` | `https://arxiv.org/pdf/2404.15028` | PDF title page: "PRISM: A Promptable and Robust Interactive Segmentation Model with Visual Prompts"; 13 pages extracted. | Source metadata fixed; no content conflict found. |
| `voxtell-2025` | `https://arxiv.org/pdf/2511.11450` | PDF title page: "VoxTell: Free-Text Promptable Universal 3D Medical Image Segmentation"; 42 pages extracted. | Source metadata fixed; no content conflict found. |
| `zhang-2026-descriptormedsam` | `https://www.nature.com/articles/s41598-025-33843-5.pdf` and `https://arxiv.org/pdf/2503.13806` | Nature/arXiv title: "DescriptorMedSAM: language-image fusion with multi-aspect text guidance for medical image segmentation". | Source metadata fixed; shorthand vault title remains acceptable. |
| `kirchhoff-2024-skeleton-recall` | `01-raw/papers/continuity and topology/2024_Skeleton_Recall_Loss_for_Connectivity_Conserving_and_Resource_Efficient_Segmentation_of_Thin_Tubular_Structures.pdf` | PDF p.1 abstract confirms Skeleton Recall Loss and connectivity focus; p.3 confirms Tubed Skeleton / ToothFairy benchmark details. | Source path changed from stale `Honor degree/...` to local `01-raw/...`; no content conflict found. |
| `shi-2024-cbdice` | `01-raw/papers/continuity and topology/2024_cbDice_Centerline_Boundary_Dice_Loss_for_Vascular_Segmentation.pdf` | PDF p.1 abstract confirms cbDice; p.2 Fig. 1 names DRIVE, Parse 2022, and TopCoW 2023. | Source path changed from stale `Honor degree/...` to local `01-raw/...`; no content conflict found. |

Post-pass verdict: no page remains `wiki-only` for the P6 provenance audit. The 12 uncertain pages are now PDF spot-check resolved, but they keep their existing reading depth unless separately deep-read later.

## Page metadata changed by this pass

- Added or corrected `source:` for the 12 wiki-only / uncertain pages.
- Corrected `medical-sam3-2026` `arxiv-id` from `2601.1088` to `2601.10880`.
- Updated the CAT warning banner to say PDF spot-checked, while preserving `deep-read pending`.
- No reading-status was inflated.
- No non-paper vault content was changed by the page patch; this audit note lives in the P6 design folder.
