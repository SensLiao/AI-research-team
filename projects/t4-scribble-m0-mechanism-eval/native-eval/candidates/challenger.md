# Independent Challenger Candidate — SM0-01

**Work order:** `WO-CHALLENGER`  
**Run:** `t4-sm0-native-20260801`  
**Role:** independent challenger  
**Input:** `frozen-brief.md`, SHA-256 `2b8e88194456c8277df08bdf3e021854c031ee7f61d67c43961f37c05db56470` (verified before drafting)  
**Status:** design only; no experiment, result, novelty assessment, or server observation is claimed

## 1. Challenger position

The first paper should test a deliberately narrow mechanism claim:

> On episodes that have already been generated from errors in an out-of-fold current segmentation, explicit access to that current segmentation provides incremental information for predicting the legal PETCT-INTENT-v2.0 joint, beyond the PET/CT image, signed scribble, and cue-only geometry.

This is narrower than saying that “human intent is caused by segmentation state.” The episodes themselves are selected from M0 residuals, so even `no_M0` receives an M0-conditioned sample through the location and polarity of its scribble. The proposed experiment can establish the incremental predictive value of **explicit M0 access within this episode generator**. It cannot, by itself, establish a causal account of unconstrained clinical user intent.

The simple-first 17-channel P2T remains the canonical primary. Cross-attention would add both capacity and an interaction prior, making a positive result harder to attribute to state access. It therefore remains future work and must not be used to rescue or replace the frozen primary contrast.

## 2. Hypothesis, strongest alternative, and estimand

### 2.1 Primary hypothesis

Let `J` be the six-way legal joint label, `I` the PET/CT image inputs, `C` the signed scribble and cue support, `G_C` the cue-only geometry, and `M` the pre-existing OOF M0 state. The hypothesis is:

\[
H_1:\quad \mathcal{L}(J\mid I,C,G_C,M) < \mathcal{L}(J\mid I,C,G_C)
\]

on previously unseen patients under a locked, patient-balanced evaluation, where `L` is six-way joint negative log-likelihood. The expected mechanistic signature is improvement in `target` and/or `scope`; `operation` is a sanity endpoint because scribble sign already exposes a strong ADD/REMOVE cue.

### 2.2 Strongest alternative

The strongest alternative is not merely “the model is weak.” It is:

> PET/CT appearance, scribble polarity, scribble location, and cue geometry already contain all practically recoverable intent information in these residual-derived episodes. M0 adds no conditional signal. Any apparent `full` advantage arises from leakage, an arm-specific preprocessing path, unequal capacity or optimization, patient duplication, class imbalance, or a shortcut in episode construction.

The design below therefore pairs every episode across arms, removes both direct and derived M0 access from `no_M0`, audits patient separation, and includes a cue-matched controlled panel in addition to a natural panel.

### 2.3 Primary estimand

For held-out patient `p`, let `E_p` be that patient's locked controlled episodes and let `ell_a(e)` be the seed-aggregated joint log loss for arm `a`. Define

\[
D_p = \frac{1}{|E_p|}\sum_{e\in E_p}\left[\ell_{no\_M0}(e)-\ell_{full}(e)\right],
\qquad
\Delta = \frac{1}{|P|}\sum_{p\in P}D_p.
\]

Positive `Delta` favors explicit state access. The patient, not the case or episode, is the resampling and inference unit.

## 3. Variables and the six legal joints

### 3.1 Observed and protected variables

| Symbol | Meaning | Permitted model access |
|---|---|---|
| `p` | patient identifier | split/grouping only; never a feature |
| `k` | case/scan identifier | provenance only; never a feature |
| `I` | frozen PET/CT image representation | both primary arms |
| `M` | exactly one pre-existing patient-excluded OOF M0 prediction for an eligible case | `full` only |
| `T` | reference segmentation | episode construction and evaluation only; never a model input |
| `R+ = T \\ M` | false-negative residual | positive-scribble construction only |
| `R- = M \\ T` | false-positive residual | negative-scribble construction only |
| `C` | scribble coordinates, sign, support, generator family, and seed | both primary arms |
| `G_C` | cue-only geometry, such as normalized extent and spatial moments | both primary arms |
| `G_M` | any geometry computed relative to M0, including overlap, distance, component identity, or state-support features | `full` only; neutralized in `no_M0` |
| `Y` | PETCT-INTENT-v2.0 label | training target/evaluation only |

`T`, `R+`, `R-`, and post-scribble ontology intermediates must be absent from the serialized model batch. Their presence in a batch, cache key, augmentation channel, support mask, or metadata embedding is a leakage failure.

### 3.2 Ontology contract

The model predicts the legal set

\[
\mathcal{J}=\{\text{ADD_SAME_LOCAL},\text{REMOVE_SAME_LOCAL},
\text{ADD_SAME_COMPLETE},\text{REMOVE_SAME_COMPLETE},
\text{ADD_NEW_COMPLETE},\text{REMOVE_NEW_COMPLETE}\}.
\]

The three slots are:

- `operation`: `ADD | REMOVE`;
- `target`: `SAME | NEW`;
- `scope`: `LOCAL | COMPLETE`.

`ADD_NEW_LOCAL` and `REMOVE_NEW_LOCAL` are illegal. They must have no joint output index and must never be created by balancing, augmentation, relabeling, or missing-value fallback. A direct six-way joint head is the primary output. Separate operation, target, and scope heads are auxiliary diagnostics; their predictions do not override the legal joint head.

The operational intuition is that positive FN cues map to ADD and negative FP cues map to REMOVE; `SAME` versus `NEW` depends on the cue-target relationship to the current state; and `LOCAL` versus `COMPLETE` depends on the requested correction extent. The authoritative label assignment must be the versioned `PETCT-INTENT-v2.0` mapper frozen at F0. This candidate does not invent substitute component thresholds or silently reinterpret the ontology.

## 4. Data and episode protocol

### 4.1 Source pool and split

The only M0 source is the already committed set of 597 cases from 378 patients, with exactly one patient-excluded held-out prediction per eligible case. It is an upstream input. It is not rerun and is not treated as a result.

Before deriving any downstream episode, freeze a patient-grouped development/validation/test assignment. If an authoritative downstream split already exists at F0, adopt it unchanged. Otherwise create it once from patient identifiers, stratifying only with development-available metadata. Every scan, M0 file, episode, augmentation, and repeat belonging to one patient stays in one split. Hyperparameter choice, threshold choice, calibration, early stopping, and atlas-driven sampler adjustment use development/validation patients only. Final test labels remain unopened until all manifests and checkpoints are locked.

The numbers 597 and 378 define the available upstream pool, not the number of downstream-eligible observations and not evidence that all six joints are feasible.

### 4.2 Ordered construction

For each eligible case, execute the following order exactly:

1. **Bind the existing M0.** Verify the M0 content hash, case/patient mapping, and the recorded patient-exclusion provenance. Do not regenerate, fine-tune, repair, or select among M0 predictions.
2. **Evaluate M0 only to build residuals.** Using the protected reference `T`, form FN residuals `R+` and FP residuals `R-`. This is downstream input preparation, not a citable M0 result.
3. **Select a residual component without an intent label.** Apply one locked eligibility rule and a deterministic random seed. Record rejected components and the reason so the atlas denominator is auditable.
4. **Construct the scribble before intent.** For `R+`, generate a positive ADD scribble; for `R-`, generate a negative REMOVE scribble. Use the already allowed AutoPET V families—centerline, random, and boundary—under frozen parameters. The generator receives residual geometry and its seed, not a requested joint class.
5. **Assign PETCT-INTENT-v2.0 after the scribble exists.** Apply the frozen ontology mapper to the completed cue, current M0, and protected construction data. Reject any output outside the six legal joints; never coerce an illegal joint into a legal one.
6. **Serialize a model-safe episode.** Store the allowed image/state/cue tensors separately from protected construction fields. Create a stable `episode_id` from input content hashes, M0 hash, cue coordinates/sign, generator version, and seed. Both P2T arms and every comparator consume the same episode IDs.
7. **Lock the episode manifest before training.** Record patient, case, split, generator, legal joint, and construction provenance. The manifest is immutable for the primary run; failures produce a new version rather than in-place repair.

This ordering prevents an intended class from choosing a particularly revealing scribble shape. It does not erase the unavoidable fact that every cue originates from an M0 residual, which remains an inferential limitation.

### 4.3 FN/FP atlas and feasibility gate

Build the atlas on development/validation patients first. At minimum it must report, by **distinct patient** rather than episode count:

- eligible FN and FP components;
- all six legal joints;
- centerline, random, and boundary cue feasibility;
- target and scope marginals within each operation;
- failures of component association, ontology assignment, or cue generation;
- the number of patients that can enter cue-matched controlled strata.

Before opening the held-out test set, freeze a minimum scientifically meaningful primary effect and run a patient-level power simulation using development/validation variability. The atlas gate passes only if every legal joint has independent-patient support across the required splits and the controlled matcher can construct the predeclared panel without copying patients or synthesizing illegal joints. If that is not possible, stop and report that six-joint feasibility was not established. Do not merge labels, manufacture episodes, move patients across splits, or use test prevalence to rescue the design.

### 4.4 Natural and controlled episode panels

Use one training manifest for both primary arms and two locked held-out views:

**Natural panel.** Sample from eligible residuals according to the predeclared operational generator, with an identical per-patient cap in every arm. Preserve the resulting class prevalence. This panel estimates transport to the generator's ordinary episode distribution.

**Controlled panel.** After scribble construction and legal labeling, match or subsample episodes using only cue-visible variables: operation/sign, scribble family, normalized cue extent, point/voxel count, bounding-box shape, and cue-only spatial moments. Match the cue-only distributions across target/scope strata as far as atlas support permits. Do not match on post-outcome metrics, M0-relative geometry, or test predictions. The controlled panel is the primary mechanism test because it makes polarity and simple cue geometry less able to explain a difference between `full` and `no_M0`.

The same held-out episode is evaluated by every arm. Natural and controlled panels must be distinguished in reporting; one cannot be substituted for the other after results are known.

## 5. Implementable simple-first P2T

### 5.1 Interface

```text
p2t(
    x17: [B, 17, D, H, W],
    cue_support: [B, 1, D, H, W],
    state_support: [B, 1, D, H, W],
    geometry: [B, G],
) -> {
    joint_logits: [B, 6],
    operation_logits: [B, 2],
    target_logits: [B, 2],
    scope_logits: [B, 2],
}
```

The exact ordered meanings, normalization, and neutral values of the 17 channels must come from the exact downstream bundle/F0 channel manifest. They must not be reconstructed from memory or guessed from this brief. That manifest must explicitly partition channels and geometry fields into image/cue-native inputs versus direct or derived M0 inputs.

### 5.2 Representation and transformation

1. A single frozen spatial backbone transforms `x17` into a feature map `F`.
2. Cue-support masked mean/max pooling produces `z_cue`.
3. State-support masked mean/max pooling produces `z_state`.
4. A small MLP transforms the frozen geometry vector into `z_geom`.
5. Concatenation followed by a fixed shallow MLP produces one shared representation.
6. Four linear heads produce six-way joint logits and the three two-way slot logits.

Training minimizes the six-way cross-entropy plus fixed-weight auxiliary cross-entropies for operation, target, and scope. All loss weights, class weights, calibration, regularization, and model-selection rules are frozen before test evaluation. The six-way head is the primary endpoint; auxiliary heads are not combined after the fact to create illegal joints.

There is no cross-attention, FiLM, gated fusion, or PET↔CT modality-fusion module in this primary. Concatenation and pooling are intentionally low-capacity so the experiment asks whether M0 contains useful information before asking how sophisticated interaction modeling should be.

### 5.3 Exact `full` versus `no_M0` intervention

Create an F0-signed allowlist `A_M0` containing every direct M0 channel and every feature derived from M0, including state support, M0-relative distance/overlap/component features, and cached transforms. Then:

- `full` receives the complete frozen 17-channel input, state support, and full geometry vector.
- `no_M0` keeps the identical tensor shapes and parameter count but replaces every item in `A_M0` with its predeclared neutral constant. Its state-support pool is neutral, and any M0-relative geometry coordinate is neutralized. Image, signed cue, cue support, and cue-only geometry are unchanged.

Neutral constants are defined in the normalized feature space from development data; they are not selected from held-out outcomes. The two arms use identical episode IDs, split, augmentations, architecture, initialization seed list, optimizer, learning-rate schedule, stopping rule, number of update steps, class weighting, hyperparameter-search budget, calibration, and model-selection rule. Training compute is paired by seed. The only permitted difference is explicit access to `A_M0`.

An automated metamorphic check must show that changing the source M0 cannot change the serialized `no_M0` batch or its prediction after the ablation transform. A second tensor-diff check must show that paired `full` and `no_M0` examples differ only at F0-declared M0-derived fields. Failure of either check invalidates the comparison.

### 5.4 Frozen diagnostic arms

- **Polarity-blind:** use the exact frozen definition to remove sign/polarity while retaining its other allowed inputs. It diagnoses the operation shortcut and is not a replacement primary.
- **Geometry-only:** use the exact frozen cue-geometry representation without image/state features. It diagnoses how much of the ontology can be recovered from scribble shape/location alone and is not a capacity-matched efficacy comparator.

Their definitions, budgets, and report positions are fixed at F0. They must not be promoted to primary based on favorable held-out behavior.

## 6. Editor and external comparator plan

P2T prediction and editing utility are separate questions. The P2T `full` versus `no_M0` classification contrast is primary and cannot be rescued by a downstream editor result.

### 6.1 Editor interface

Use one frozen editor interface:

```text
editor(I, M, C, q_joint) -> corrected_segmentation
```

where `q_joint` is a six-way probability vector. To isolate P2T information, prefer one editor checkpoint trained only on development patients using legal reference intent, with a frozen intent-corruption/dropout schedule so it can accept imperfect probability vectors. Freeze the editor before generating held-out P2T predictions. At test time, run the same editor checkpoint and the same episode through:

1. `q_full` from the simple full P2T;
2. `q_no_M0` from the simple no-M0 P2T;
3. legal oracle intent as a diagnostic ceiling;
4. a fixed no-intent/uniform input as a diagnostic floor.

If the pre-existing frozen editor contract instead mandates paired editor training, preserve that contract, but enforce identical data, seeds, architecture, and budget and report the added training variance. In neither case may editor tuning see the held-out test set.

Editor outcomes are patient-level secondary endpoints: change from M0 in segmentation overlap, surface error, FN residual burden for ADD episodes, FP residual burden for REMOVE episodes, and lesion/object-level correction where the frozen metric contract supports it. Report both beneficial and harmful changes. Do not summarize an editor as successful merely because a global overlap metric rises while the signed target residual worsens.

### 6.2 External comparators

Freeze comparator names, versions/checkpoint hashes, adapters, input permissions, and inference budgets at F0. Each comparator receives the same image, M0, signed scribble, interaction count, and held-out episode manifest that its published interface legitimately supports. It receives neither protected reference data nor hidden ontology fields. A comparator that cannot consume intent is compared only on the editing endpoint; it is not presented as a P2T competitor. Comparator adaptation is development-only and budget-matched. Interface mismatches and unavailable outputs are reported, not imputed.

## 7. Statistical analysis

### 7.1 Primary analysis

- **Endpoint:** six-way joint negative log-likelihood on the controlled held-out panel.
- **Contrast:** paired `full - no_M0`, expressed as `Delta = NLL(no_M0) - NLL(full)` so positive favors `full`.
- **Unit:** patient. Average all eligible episodes and the predeclared paired seed set within patient before population aggregation.
- **Interval/test:** a paired hierarchical bootstrap that resamples patients and paired training seeds, with the bootstrap count and confidence level frozen at F0. A paired patient-level randomization test is a sensitivity analysis.
- **Decision:** continuation support requires the confidence interval for `Delta` to exclude zero in the favorable direction. A crossing interval is inconclusive, not positive.

The natural panel repeats the same locked analysis as a transport check. A positive controlled estimate that reverses materially on the natural panel must be reported as distribution-sensitive rather than generalized.

### 7.2 Secondary analyses

Report patient-balanced exact joint accuracy, macro recall, per-joint recall/precision, calibration error, and the operation/target/scope log losses. Adjust the family of slot-head tests using a method frozen before evaluation. The intended signature is target and/or scope information; an isolated operation gain is not persuasive because polarity should already identify operation.

For editor and comparator outcomes, compute paired patient-level differences on identical episodes and bootstrap patients. Report ADD and REMOVE separately as well as the aggregate. Generator-family, joint-class, lesion-size, and centerline/random/boundary analyses are heterogeneity analyses with uncertainty, not independent discoveries. Do not treat episode count as sample size or let patients with more residuals receive more inferential weight.

Training-seed dispersion, calibration failure, missing eligible episodes, and every exclusion are reported. No test patient is dropped because an arm predicts poorly.

## 8. Leakage and integrity defenses

The run is invalid if any of the following controls fails:

1. **OOF provenance:** each M0 hash maps to exactly one eligible case and documents exclusion of that patient's data from the upstream predictor. No OOF rerun is allowed.
2. **Patient grouping:** no patient, repeat scan, derived crop, cached tensor, or episode crosses downstream splits.
3. **Construct-before-label:** the scribble generator cannot read the intended target/scope class; the ontology mapper runs only after cue construction.
4. **Ground-truth firewall:** references and residual maps are unavailable to P2T/editor/comparator dataloaders, transforms, support masks, normalization, and metadata embeddings.
5. **Ablation closure:** `no_M0` removes direct channels and all M0-derived geometry, supports, caches, filenames, and precomputed embeddings—not merely the visible mask channel.
6. **Paired episode manifest:** arm-specific sampling, resampling, augmentation counts, or rejected-example handling is prohibited.
7. **Train-only fitting:** normalization, component thresholds, class weights, matching bins, calibration, and early stopping are fit without held-out test labels.
8. **No patient-frequency shortcut:** per-patient caps and patient-level statistics prevent a residual-rich patient from dominating.
9. **Legal-joint assertion:** loaders and heads reject both NEW_LOCAL combinations; no balancing code can synthesize them.
10. **Blind final evaluation:** test predictions are written once from locked checkpoints and scored by a separate evaluator; model selection cannot be reopened afterward.
11. **Comparator parity:** comparator adapters cannot see extra clicks, reference masks, ontology labels, or test-time tuning unavailable to the proposed editor.
12. **Artifact binding:** source, environment, input, episode, checkpoint, and metric-code hashes are recorded so stale software cannot be mistaken for the intended run.

A useful negative-control audit is to replace the raw M0 object before the `no_M0` ablation transform and assert byte-identical serialized model inputs. This is an integrity test, not a new scientific arm.

## 9. Falsifier and stop rules

### 9.1 Concrete falsifier

The state-dependence hypothesis is falsified for this model and episode generator if the upper confidence bound of the patient-level controlled-panel `Delta` is at or below zero: all effects compatible with the interval are non-beneficial for `full`. A nominal natural-panel advantage that vanishes or reverses under cue-matched control also supports the strongest alternative that cue/polarity shortcuts, rather than explicit state, explain performance.

If the interval crosses zero, the result is **inconclusive**, not evidence for either effectiveness or equivalence. Equivalence may be claimed only if an equivalence margin was scientifically justified and frozen before held-out evaluation.

### 9.2 Operational hard stops

Stop before training if:

- the exact downstream bundle/F0 closure is missing;
- any M0 cannot be bound to its patient-excluded provenance without rerunning it;
- the FN/FP atlas cannot support all six legal joints across independent patients;
- controlled matching requires patient duplication, illegal joints, or test-informed rules;
- the `full`/`no_M0` tensor-diff or no-M0 invariance audit fails;
- protected reference/residual information reaches a model input; or
- a stale bundle, nondeterministic episode manifest, or metric mismatch prevents artifact binding.

### 9.3 Scientific escalation stop

Do not escalate to cross-attention or make a first-paper mechanism claim unless the locked primary comparison clears its prospective continuation criterion and the target/scope diagnostics are compatible with the proposed mechanism. A negative or inconclusive simple-primary result cannot be “rescued” by selecting a more complex fusion model on the same held-out set. Any already frozen cells may be completed for audit completeness, but they do not reverse the stop decision.

## 10. First operational blocker

The first blocker is **exact downstream software-bundle/F0 closure**, because the enclosing downstream run failed before M0 evaluation under a stale deployed bundle. This must be resolved locally and artifact-first before any M0 evaluation or episode generation. Closure requires at least:

- content-addressed source revision and dependency/container lock;
- exact `PETCT-INTENT-v2.0` mapper and legality assertions;
- authoritative ordered 17-channel manifest;
- explicit `A_M0` direct/derived-state allowlist and neutralization contract;
- hashes and patient-exclusion mapping for the existing OOF M0 inputs;
- patient split, episode schema, generator versions/seeds, and atlas gate;
- P2T/editor architectures, losses, optimization budgets, seed list, and selection rules;
- metric implementations, comparator adapters, and blind-evaluation command;
- fixture tests proving six legal outputs, protected-field exclusion, paired-arm tensor differences, and no-M0 invariance.

This blocker must not be addressed by rerunning M0. No claim about current server availability, health, or activity is needed or permitted to close it.

## 11. Where cross-attention belongs

Cross-attention is a **future, separately preregistered ablation** after the simple-first matrix is completed and interpreted. It may be scientifically motivated if the simple full model contains a stable state signal but fails specifically where localized cue–state correspondence is needed. It may also test a new representational hypothesis after a null simple model, but then it is a new experiment—not evidence that the original simple mechanism worked.

Any future cross-attention study must reuse the locked patient splits and episode manifests, keep `full` versus `no_M0`, add a capacity-matched simple control, and avoid selecting architecture or hyperparameters on the first-paper test set. FiLM, gated fusion, and PET↔CT modality fusion remain in the same deferred category. None may silently become the current primary.

## 12. Truth boundary and proposed continuation decision

This document is an implementable candidate, not an execution record. It does not show that:

- the six classes have adequate patient support;
- the 17-channel P2T can be trained or calibrated successfully;
- explicit M0 improves intent prediction;
- an editor improves segmentation;
- any external comparator was run;
- the mechanism is novel, clinically useful, or publication-ready; or
- any server is available or executing work.

The OOF M0 set is an upstream, non-citable input. Scripts, manifests, checkpoints, and F0 closure are also not scientific results. Only receipt-bound execution, protected held-out evaluation, patient-level statistics, leakage audits, and independent review could support a result claim.

The proposed continuation is therefore staged: **close the exact bundle/F0 first; audit the existing M0 inputs without rerunning them; build the FN/FP atlas and apply the six-joint feasibility gate; then run the frozen simple-first `full` versus `no_M0` design with its diagnostic arms, editor, comparators, and patient-level analysis.** Cross-attention stays future regardless of convenience.
