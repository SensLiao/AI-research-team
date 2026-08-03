# Anonymous design candidate

> Status: `DESIGN_ONLY / NON_CITABLE / NO RESULTS`. This candidate may not claim novelty, effectiveness, execution, or publication readiness.

## Hypothesis

H_state (protocol-bounded): for patient p and locked episode e, conditional on the identical non-M0 image/context inputs X_pe, signed scribble S_pe, cue geometry G_pe, and frozen episode/training protocol, the legal PETCT-INTENT-v2.0 label Y_pe=(operation,target,scope) is not conditionally independent of the case-matched patient-excluded OOF state M0_p. Therefore explicit access to M0 in the frozen simple-first 17-channel full arm is predicted to lower patient-averaged held-out six-joint risk relative to the exhaustive no_M0 arm, with the distinguishing information expressed in target and identifiable scope rather than operation alone.

### Strongest alternative

H_cue: Y_pe is conditionally independent of explicit M0_p once the identical signed polarity, cue geometry and morphology, non-M0 context, episode-construction protocol, and legality constraint are known. Cue and generator regularities are then sufficient, so matched full and no_M0 have equivalent patient-level generalization apart from sampling variation; any apparent separation confined to operation, geometry-determined cells, legality masking, or coarse difficulty does not support state-relative interpretation.

### Observable prediction

For arm a, define L_p^a as the mean preregistered proper six-joint loss across all eligible locked episodes belonging to patient p, Delta_p=L_p^no_M0-L_p^full, and Delta as the mean of Delta_p across held-out patients. H_state predicts positive Delta plus coherent target separation among COMPLETE episodes and scope separation among SAME episodes, especially in adequately supported polarity-and-geometry-matched ambiguity strata. H_cue predicts Delta=0 or prospective patient-level equivalence. An operation-only difference is non-distinguishing because FN-derived positive cues encode ADD and FP-derived negative cues encode REMOVE.

## Implementable mechanism

### Inputs

- The frozen simple-first 17-channel episode tensor with an ordered channel/provenance manifest closed at downstream bundle/F0, including the case-matched committed patient-excluded OOF M0 state and every declared direct or derived M0 path
- The identical signed scribble in both arms, constructed before intent assignment from an FN residual for positive ADD or an FP residual for negative REMOVE, together with cue support and centerline, random, or boundary geometry descriptors
- The identical non-M0 image/context channels, state-support and cue-support masks, and geometry vector required by the canonical interface
- Training-only PETCT-INTENT-v2.0 supervision factorized as operation ADD or REMOVE, target SAME or NEW, and scope LOCAL or COMPLETE, restricted to the six legal joints

### Representation

Keep preceding segmentation state M0, signed cue polarity, cue geometry/morphology, support masks, and non-M0 context as distinct interface objects. The canonical simple representation is the frozen 17-channel state/cue tensor processed by one unchanged backbone, state-support and cue-support pooling, and a geometry MLP. Its legal joint space is exactly {ADD_SAME_LOCAL, REMOVE_SAME_LOCAL, ADD_SAME_COMPLETE, REMOVE_SAME_COMPLETE, ADD_NEW_COMPLETE, REMOVE_NEW_COMPLETE}; ADD_NEW_LOCAL and REMOVE_NEW_LOCAL are structurally illegal and must not be generated, trained, normalized, or emitted as legal joints.

### Transformation

Apply the unchanged simple-first backbone to the canonical 17-channel tensor, pool the resulting features over the declared state and cue supports, transform the geometry vector with the frozen geometry MLP, concatenate through the canonical simple-fusion interface, and feed the frozen joint/operation/target/scope heads. In full, all manifest-declared M0 paths are active. In no_M0, exhaustively neutralize only those direct and derived M0 paths under one prospectively frozen rule while preserving tensor shape, non-M0 bytes, code path, parameter-opportunity policy, initialization, episode order, optimizer, stopping, and budget. The exact neutralization rule remains an OPEN preflight decision. Cross-attention is excluded from this current transformation and may only be a separately registered deferred future ablation after the canonical analysis is frozen; it cannot replace full or rescue a failed, null, or inconclusive primary.

### Output

One probability distribution over the six legal joints plus two-way operation, target, and scope heads. The joint constraint cannot synthesize either NEW_LOCAL combination. Labels, reference masks, FN/FP residual maps, post-edit states, patient/case identifiers, filenames, and administrative metadata are unavailable as inference features.

### Distinguishing signal

The distinguishing signal is a positive paired patient-level full-versus-no_M0 difference on the preregistered six-joint estimand, coherent with target among COMPLETE episodes and scope among SAME episodes and persisting in adequately supported cue-matched ambiguity strata. Operation-only separation, geometry-only reproduction of the pattern, gains confined to legality-determined or difficulty-separated strata, or episode-level gains that disappear after patient aggregation do not distinguish state-relative interpretation from polarity, generator, selection, or difficulty shortcuts.

### Failure modes

- The synthetic episode construction itself induces dependence because reference labels and M0 create FN/FP residuals, residual type creates signed scribbles and eligibility, and the builder assigns labels; a contrast can therefore measure protocol decoding rather than relational interpretation.
- no_M0 remains exposed to M0 through state-support masks, cached features, normalization statistics, sampling strata, filenames, padding, transforms, or episode metadata, or the neutralization changes scale, missingness, effective capacity, or optimization.
- The arms differ in patients, episode identities, scribbles, geometry, non-M0 inputs, sampling, augmentation, minibatch order, initialization, optimizer, schedule, stopping, checkpoint selection, or total training budget.
- Patients, aliases, duplicate or longitudinal exams, cases, or episode derivatives cross partitions, or repeated episodes and cases are treated as independent observations instead of being aggregated and resampled by patient.
- Any legal joint lacks prospectively required distinct-patient support, either illegal NEW_LOCAL joint appears, or polarity, geometry, morphology, legality, or an administrative field deterministically exposes target or scope.
- Case-to-M0 binding, patient-excluded provenance, PET/CT/reference/M0/residual/scribble physical-coordinate alignment, label provenance, acquisition provenance, or missingness handling is absent or fails.
- The protocol-generated scribble task is extrapolated to the latent intent or cognition of real human annotators; this design has no human-interaction evidence for that claim.

## Falsifiable experiment

### Intervention

Within the frozen first-paper matrix, change only explicit access to M0: the canonical simple-first 17-channel full arm receives every declared case-matched OOF M0 channel/support path, while the paired no_M0 arm exhaustively neutralizes exactly those manifest-declared paths under a rule frozen before outcome access. Polarity-blind and geometry-only remain diagnostic arms and do not replace this intervention; cross-attention is absent.

### Comparator

The exhaustive no_M0 ablation using the same canonical simple-first interface, identical locked episodes and non-M0 payloads, and the same training and analysis contract as full. It must preserve shape and training opportunity without carrying an arm token or residual M0 information.

### Held constant

- The committed 597-case, 378-patient OOF M0 set with exactly one patient-excluded held-out prediction per eligible case; it is an immutable upstream input and is not rerun, regenerated, selected, or substituted
- The patient-disjoint split and exact case/episode identities, signed scribble voxels and polarity, cue geometry and morphology, legal labels, controlled/natural membership, construction seeds, sampling weights, and episode ordering
- The canonical 17-channel contract except for prospectively registered M0-path neutralization in no_M0, including identical non-M0 bytes, preprocessing, normalization, supports, padding conventions, caches, and augmentations
- The simple-first backbone, state/cue-support pooling, geometry MLP, six-joint and operation/target/scope heads, legality handling, multi-head-loss configuration, and parameter-opportunity policy
- The full and no_M0 training contract: initialization and seed policy, patient-first sampler or other prospectively chosen shared schedule, minibatch order, optimizer, learning-rate schedule, regularization, update/epoch budget, paired stopping rule, and checkpoint-selection rule
- The analysis contract: patient aggregation, primary endpoint, uncertainty procedure, missing-data and multiplicity rules, identifiable target/scope strata, ambiguity definitions, and any smallest-relevant-effect or equivalence margin, all frozen before held-out outcomes are opened

### Independent analysis unit

The independent unit is patient p. All cases and episodes from one patient remain in one split and one resampling or permutation unit. Compute L_p^a as that patient's mean locked-episode joint loss under arm a, Delta_p=L_p^no_M0-L_p^full, and estimate Delta by averaging Delta_p across held-out patients with patient-level uncertainty; episodes, lesions, scribbles, cases, and voxels are not independent replicates.

### Primary outcome

The paired held-out patient-level Delta for one prospectively frozen proper six-joint loss, summarized with a patient-level 95% confidence interval. Target among COMPLETE episodes and scope among SAME episodes are mechanistic diagnostics, and operation is a polarity-shortcut check. The exact proper scoring rule, any macro classification co-primary, and the nonzero smallest-relevant-effect or equivalence margin remain OPEN and must be fixed before outcome access.

### Leakage checks

- Verify zero patient, normalized alias, duplicate-exam, or longitudinal-study overlap across train, validation, and test, and keep every case, episode, scribble, atlas derivative, and resampling contribution from one patient in the same partition.
- Verify exactly one case-matched committed OOF M0 artifact per eligible case, its generating fold excludes that patient, and no in-sample, alternative, or outcome-selected M0 is substituted.
- Hash-compare full and no_M0 episode manifests and every non-M0 payload; episode IDs, scribbles, geometry, labels, sampler decisions, augmentations, minibatch order, and training exposure must be identical.
- Audit an exhaustive manifest of direct and derived M0 paths and prove no_M0 contains none through tensor channels, state-support masks, pooled supports, caches, transforms, normalization statistics, sampler strata, metadata, filenames, padding, or missingness tokens.
- Prove reference masks, FN/FP residual maps or magnitudes, post-edit states, intent labels, patient/case identifiers, filenames, administrative fields, generation order, and arm identity cannot reach inference features.
- Prove final-test patients and outcomes do not set atlas/coverage thresholds, class balance, eligibility, ambiguity bins, hyperparameters, stopping, checkpoint selection, metric choice, uncertainty method, or effect/equivalence margins.
- Verify PET, CT, reference segmentation, OOF M0, residual, and scribble grids, orientation, spacing, and transform chains agree in physical coordinates for every consumed episode.
- Before fitting, audit distinct-patient support for all six legal joints, zero NEW_LOCAL episodes, polarity-by-operation invariants, geometry/morphology predictability of target/scope, and adequately supported ambiguity strata.

### Falsifier

After bundle/F0, coverage, provenance, coordinate, arm-parity, and leakage gates pass, falsify H_state for this canonical interface if the preregistered patient-level 95% upper confidence bound for Delta is at or below zero. Also reject the stronger state-relative interpretation if an aggregate difference is confined to operation, geometry- or legality-determined cells, or coarse difficulty strata while no_M0 matches full in adequately supported polarity-and-geometry-matched ambiguity strata. An interval spanning beneficial and null values is inconclusive, not affirmative evidence; accepted prospective equivalence favors H_cue. Do not introduce cross-attention or alter the curriculum as a rescue.

### Stop condition

The first operational stop is failure to close and hash the exact downstream deployed bundle, environment, configuration, ordered 17-channel map, and F0 contract after the stale-bundle failure; the committed OOF M0 remains unchanged and must not be rerun. After closure, stop before fitting if any legal joint misses its prospectively frozen distinct-patient support threshold, either NEW_LOCAL joint appears, no adequately supported ambiguity stratum remains, target/scope is deterministically exposed by unintended cues, the exact no_M0 neutralization and shared analysis/training contracts are not frozen, or any lineage, physical-coordinate, leakage, or arm-parity check fails. Stop claim escalation when the falsifier fires, and do not repair a null, failed, or inconclusive primary by rerunning OOF M0 or promoting cross-attention.

## Open and resolved conflicts

### OPEN-PRIMARY-ENDPOINT-AND-DECISION-RULE — OPEN

The mathematical contribution centers a proper six-joint loss and an upper-confidence-bound falsifier; the cognitive contribution suggests macro-F1 or balanced accuracy plus equivalence analysis; the domain contribution also states a point-difference rule; and the remaining contributions require but do not establish a meaningful-effect or equivalence margin. No supplied fact selects the exact proper scoring rule, whether a macro classification metric is co-primary, the uncertainty procedure, or the nonzero decision margin. These must be prospectively frozen before held-out outcome access.

### OPEN-NO-M0-NEUTRALIZATION-CONTRACT — OPEN

All roles require exhaustive removal of direct and derived M0 information, but the supplied facts do not define whether each path is zeroed, masked, removed, or replaced by another noninformative value, nor how state-support pooling, normalization, scale, and parameter opportunity remain matched. The exact path-wise rule must be closed at bundle/F0 and frozen before fitting; it cannot be chosen after outcomes.

### OPEN-SHARED-TRAINING-SCHEDULE — OPEN

The curriculum contribution proposes a patient-first staged simple-to-ambiguous schedule but also recognizes that a budget-matched flat sampler may be equivalent or better. The other contributions require identical schedule and minibatch exposure across full and no_M0 but provide no evidence selecting staged versus flat training. One shared schedule must be chosen prospectively; any staged-versus-flat comparison remains a separately registered development audit and cannot change the frozen primary after held-out inspection.

### OPEN-AMBIGUITY-STRATA-DEFINITION — OPEN

The contributions agree that cue-matched ambiguity strata are load-bearing but do not establish their definitions, support thresholds, or covariate set. Suggestions differ across polarity, geometry family, cue morphology, controlled versus natural source, and coarse state/error burden, while M0- or residual-derived variables are prohibited from curriculum ordering. Strata and their use in analysis versus sampling must therefore be prospectively separated and frozen before outcome access.

## Truth boundary

- Execution status: `DESIGN_ONLY`
- Result claims allowed: `false`
- Novelty claims allowed: `false`
- Producer identities and internal receipts are intentionally omitted from this blind-review rendering.
