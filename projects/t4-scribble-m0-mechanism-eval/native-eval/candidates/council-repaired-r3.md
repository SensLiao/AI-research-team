# Council candidate — targeted repair recovery R3

> Status: `DESIGN_ONLY / NON_CITABLE / NO RESULTS`
>
> Recovery work order: `WO-TARGETED-REPAIR-R3`. This document copies the packet-bound R2 candidate and changes only the two PARTIAL contracts named in `repair-packet-r3.json`; it does not reopen R1, R2, the ontology, data split, episode matrix, experiment identifiers, or canonical architecture.

## Truth boundary

This is a preregistration-quality **design repair**, not an execution record. No model was trained or evaluated, no held-out outcome was opened, no server was contacted, and no effectiveness, novelty, publication-readiness, or causal-superiority claim is made. The source bindings used for this repair were SHA-256 verified before authoring: the R2 packet, frozen brief, council candidate, reconciliation report, mapping reveal, original aborted-work-order record, and R2 work order all matched the hashes available in their frozen chain. The reveal maps blind candidate `Y` to `council`; all four repairs below answer findings replicated by all three judges.

The numerical and algorithmic choices below are frozen **prospective design decisions**. They have not been experimentally validated. F0 still has to instantiate the real ordered 17-channel map, exact path inventory, analysis population, paired experiment rows, training order, software/environment record, and the manifests named below; it must write their real SHA-256 values. This document intentionally invents no F0 hash. Fitting and held-out access are forbidden until those files exist, validate, and are hash-bound to the unchanged experiment identifiers.

Required F0 records are:

1. `analysis-contract.json` for the endpoint, aggregation, uncertainty, missingness, multiplicity, and decision rule;
2. `m0-path-manifest.json` for the exhaustive direct-and-derived M0 provenance closure and neutralization rule;
3. `ambiguity-strata-manifest.json` for development-only bin edges, eligible strata, and support counts;
4. `training-schedule-manifest.json` and `training-order-manifest.json` for the shared full/no_M0 schedule and exact patient/episode order; and
5. the already-required deployed-bundle, environment, configuration, coordinate, and ordered-channel manifests.

Until that F0 closure is real and hashed, the only honest state is `DESIGN_ONLY`.

## Frozen hypothesis and mechanism

### Hypothesis

For patient (p) and locked episode (e), conditional on identical non-M0 image/context input (X_{pe}), signed scribble (S_{pe}), cue geometry (G_{pe}), legality constraint, split, and training protocol, the legal PETCT-INTENT-v2.0 joint label

\[
Y_{pe}=(\text{operation},\text{target},\text{scope})
\]

is not conditionally independent of the case-matched patient-excluded OOF state (M0_p). Accordingly, the simple-first 17-channel `full` arm is predicted to have lower held-out patient-averaged six-joint log loss than the exhaustive `no_M0` arm. The distinguishing signal must include target discrimination among `COMPLETE` episodes and/or scope discrimination among `SAME` episodes; operation-only separation is non-distinguishing because signed FN/FP scribbles already expose ADD/REMOVE polarity.

The strongest alternative, (H_{cue}), is that cue polarity, cue-visible geometry/morphology, non-M0 context, the generator, and the legality constraint are sufficient. Under that alternative, `full` and `no_M0` have equivalent patient-level generalization apart from sampling variation, and any apparent difference is explained by polarity, geometry, legality, selection, or difficulty shortcuts.

### Canonical mechanism

The primary remains the frozen simple-first 17-channel state/cue interface. The same backbone processes the ordered tensor; the same state-support and cue-support pooling, geometry MLP, simple concatenation/fusion, and joint/operation/target/scope heads are used in both arms. `full` activates every F0-manifested direct and derived M0 path. `no_M0` retains the identical tensor shapes, modules, parameters, initialization opportunity, and code path but applies the exhaustive normalized-space intervention in Repair R2.

The output joint distribution is restricted to exactly:

- `ADD_SAME_LOCAL`
- `REMOVE_SAME_LOCAL`
- `ADD_SAME_COMPLETE`
- `REMOVE_SAME_COMPLETE`
- `ADD_NEW_COMPLETE`
- `REMOVE_NEW_COMPLETE`

`ADD_NEW_LOCAL` and `REMOVE_NEW_LOCAL` remain structurally illegal: they are not generated, trained, normalized, or emitted as legal joints. Labels, reference masks, FN/FP residual maps, post-edit state, identifiers, filenames, administrative metadata, and arm identity remain unavailable as inference features.

Cross-attention, FiLM, gated fusion, and PET-to-CT modality fusion are not part of this primary mechanism. Cross-attention may be registered only as a future ablation after the simple-first analysis is frozen; it cannot replace, reinterpret, or rescue this comparison.

## Repair R1 exact primary endpoint and decision rule

### Analysis population and exact score

The primary analysis population is every patient in the already-frozen held-out split who has at least one prospectively eligible locked episode. Eligibility is fixed before outcome access. All eligible episodes for a patient are retained, and all pre-existing paired replicate rows in the frozen experiment matrix are retained; no replicate is added, removed, or renamed by this repair.

For arm (a \in \{\text{full},\text{no\_M0}\}), replicate (r), patient (p), and episode (e), compute the six-legal-joint categorical log score in IEEE-754 float64 using stable `log_softmax`:

\[
\ell^{a}_{rpe}=-\log p^{a}_{rpe}(Y_{pe}).
\]

There is no probability clipping. A non-finite logit or loss is an analysis-gate failure, not a missing value to impute. Average first within patient across that patient's (n_p) locked episodes and the same (R) pre-existing replicate rows in each arm:

\[
L_p^a=\frac{1}{R n_p}\sum_{r=1}^{R}\sum_{e=1}^{n_p}\ell^{a}_{rpe}.
\]

Then define the paired patient contribution and the primary endpoint:

\[
\Delta_p=L_p^{\text{no\_M0}}-L_p^{\text{full}},\qquad
\Delta=\frac{1}{N}\sum_{p=1}^{N}\Delta_p.
\]

Positive (Delta) favors explicit M0 access. Patients receive equal weight; cases, episodes, scribbles, lesions, voxels, and replicate rows are never treated as independent inferential units. No macro-F1, balanced accuracy, head loss, or subgroup score is co-primary.

### Uncertainty and fixed margins

Use one paired patient bootstrap. With NumPy `PCG64` seed `20260801`, draw `B = 10,000` bootstrap samples of size (N) by sampling patient IDs with replacement, carrying every selected patient's cases, episodes, and replicate contributions together. Recompute (Delta) for each sample. The two-sided 95% percentile interval is `numpy.quantile(draws, [0.025, 0.975], method="linear")`; the two-sided 90% percentile interval uses `[0.05, 0.95]` with the same draws. The fixed smallest-relevant/equivalence margin is

\[
\delta=0.010\ \text{natural-log units per patient-averaged episode}.
\]

This margin is a prospective design threshold, not an observed effect or a claim of clinical importance.

### One deterministic decision rule

Only after every F0, coverage, lineage, parity, leakage, and completeness gate passes, apply the following order exactly once:

1. `CONTINUE_STATE_MECHANISM` if the 95% lower bound is strictly greater than (+\delta).
2. Otherwise, `FALSIFY_CANONICAL_H_STATE` if the 95% upper bound is less than or equal to `0.000`.
3. Otherwise, `CUE_SUFFICIENCY_COMPATIBLE` if the 90% interval lies strictly inside ([-\delta,+\delta]).
4. Otherwise, `INCONCLUSIVE`.

`CONTINUE_STATE_MECHANISM` means only that the preregistered canonical mechanism merits the already-scoped continuation; it is not an effectiveness or publication claim. The other three states cannot be rescued by a different endpoint, a different margin, a curriculum change, an OOF rerun, or cross-attention.

### Missingness and multiplicity

The endpoint requires a prediction from both arms for every prospectively eligible episode and every pre-existing paired replicate. Any absent arm, absent paired replicate, non-finite output, duplicate prediction, or post-eligibility missing episode invalidates the primary analysis and triggers `STOP_ANALYSIS`; there is no imputation, complete-case deletion, arm-specific exclusion, or patient reweighting. A patient with zero episodes under the eligibility rule established before held-out access is outside the prespecified population and must be counted in the flow table with the pre-outcome reason.

There is exactly one primary endpoint and one ordered decision rule, so no multiplicity adjustment is applied to the primary. Operation, target, scope, macro metrics, geometry-only, polarity-blind, and stratum results are secondary diagnostics; they cannot change the primary state. Any intervals shown for them are explicitly descriptive and unadjusted, and no secondary `p < 0.05` claim is permitted.

## Repair R2 exhaustive no_M0 intervention

### Exhaustive provenance allowlist

At F0, construct a directed provenance graph from every raw episode field and cache entry to every model input, support pool, geometry value, sampler decision, augmentation parameter, normalization statistic, and inference-visible metadata field. Mark raw (M0) as a source. Define (A_{M0}) as **the complete transitive closure of all nodes that depend directly or indirectly on M0**. `m0-path-manifest.json` must contain one ordered row for every member of (A_{M0}), with:

`path`, `parent_paths`, `semantic_class`, `tensor_or_object`, `dtype`, `shape`, `channel_or_field_index`, `normalization_source`, `neutral_value`, `neutralization_stage`, `cache_key_rule`, and `byte_range_or_canonical_serializer`.

The mandatory semantic classes to search and either enumerate or explicitly attest empty are:

| Path class | Required no_M0 treatment |
|---|---|
| Direct M0 slices in the ordered 17-channel tensor | After the shared training-only normalization, replace every element with positive `0.0` in the existing dtype. Do not remove a channel. |
| M0-derived maps and state-support masks | Replace every element with `0`; retain exact dtype, shape, padding, and module calls. |
| State-support pooled inputs and outputs | Feed the all-zero support; the empty-support branch returns an exact all-zero vector of the existing size. The pooling module and downstream parameters remain present. |
| M0-derived geometry fields | Replace only the manifested indices with normalized-space `0.0`; all cue-only geometry indices remain byte-identical. |
| M0-derived transforms, statistics, cache values, or cached features | Use the one shared training-split normalization record, then replace the manifested output with same-shape zeros before model or sampler access. Cache keys may use only the locked episode ID and preprocessing-version hash, never M0 content, arm name, label, or outcome. |
| M0-derived sampler, augmentation, filename, missingness, routing, or administrative paths | These are prohibited rather than encoded. If any such dependency exists, F0 blocks until it is removed; no arm token or missingness sentinel may substitute for M0. |

Normalization parameters are estimated once from the frozen **training split only**, recorded once, and applied identically to both arms. For an M0-dependent continuous path, neutralization occurs after that shared normalization so `0.0` is the normalized-space center. Non-M0 paths use the same statistics and must remain byte-identical. No test patient contributes to a normalization parameter.

The allowlist is also the only permitted full/no_M0 difference list. Any changed field or byte outside (A_{M0}) is a hard failure. Any M0-dependent path absent from the manifest is a hard failure. F0 must serialize and SHA-256 hash the completed manifest; a semantic class marked empty must carry the audited graph query and zero-count result. This document freezes the rule but does not fabricate the still-missing concrete channel indices or hash.

### Shape, capacity, and initialization parity

Both arms use the same ordered 17-channel shape, dtypes, padding, backbone, pooling modules, geometry MLP, heads, legality mask, parameter count, and optimizer state schema. No channel, branch, or parameter is deleted or added in `no_M0`. The initial `state_dict` bytes and their SHA-256 must match across each paired run. The no_M0 constant values are data, not a learned arm embedding; `arm`, `condition`, and path names cannot enter the model.

### Required pre-fit metamorphic checks

For every locked development episode, F0 must pass all of the following before fitting:

1. **Byte-level paired diff:** canonical-serialize the full and no_M0 model inputs, support-pool inputs/outputs, geometry vector, sampler row, and augmentation row. Length, dtype, and shape must match. Every byte outside manifest-declared (A_{M0}) ranges must be identical; every declared no_M0 numeric value must be the exact zero bit pattern for its dtype.
2. **Non-M0 payload parity:** hashes of image/context channels, scribble voxels and polarity, cue geometry, labels, episode IDs, augmentation parameters, order, and all non-M0 caches must match pairwise.
3. **M0 perturbation invariance:** hold the locked episode, scribble, label, and every non-M0 value fixed. Run the no_M0 builder three times with (a) the committed M0, (b) an all-zero raw M0 of the same shape/dtype, and (c) the committed M0 flattened, reversed, and reshaped. Recompute only M0 descendants. The canonical serialized no_M0 inputs, pools, geometry, cache-facing payload, and deterministic-eval logits from the common initial checkpoint must be byte-identical across all three runs.
4. **Capacity parity:** parameter names, shapes, counts, initial bytes, forward-call graph, and loss heads must match. Any mismatch blocks both arms; it is not repaired independently by arm.

These checks establish intervention isolation only. Passing them would not show that M0 is useful.

## Repair R3 ambiguity strata contract

### Development-only definition

Strata are derived only from the frozen training-plus-validation development partition. Held-out patients, predictions, losses, or effect estimates cannot set a covariate, cut point, support threshold, merge, or exclusion.

Use exactly four cue-visible, non-outcome covariates:

1. signed cue `polarity` in `{POSITIVE, NEGATIVE}`;
2. `geometry_family` in `{CENTERLINE, RANDOM, BOUNDARY}`;
3. episode `source_mode` in `{CONTROLLED, NATURAL, MISSING}`; and
4. `cue_size_bin`, obtained from (z=\log_2(1+\text{cue voxel count})).

Compute the 25th, 50th, and 75th percentiles of (z) over development episodes with NumPy `quantile(method="linear")`. Remove duplicate cut points in ascending order. Assign bins with `numpy.searchsorted(cut_points, z, side="right")`, yielding deterministic integer bins from `0` through the number of unique cuts. F0 writes the cut points as float64 decimal strings with 17 significant digits. Polarity, geometry family, and cue voxel count are derivable from the cue and therefore mandatory; missing or non-finite values are a preflight failure. A missing `source_mode` is retained as the literal `MISSING` level and is never imputed.

The immutable stratum key is the exact tuple

`(polarity, geometry_family, source_mode, cue_size_bin)`.

There is no nearest-neighbor matching, learned propensity score, outcome-driven regrouping, or post-held-out merging.

### Canonical stratum-key bytes and bootstrap seed

For serialization and hashing, the tuple above is represented as the JSON array

`[polarity, geometry_family, source_mode, cue_size_bin]`.

The first three elements must be the exact uppercase enum strings frozen above; the fourth must be a JSON integer, not a quoted string or float. Produce the canonical text with Python `json.dumps(array, ensure_ascii=False, separators=(",", ":"))`: there is no indentation, no whitespace between tokens, and no trailing newline. `stratum_key_bytes` is exactly that text encoded once as UTF-8. No locale-dependent encoding, Unicode normalization pass, object-key ordering, tuple representation, or platform newline is permitted.

Let `digest = SHA256(stratum_key_bytes).digest()`. Interpret `digest[0:4]` as one unsigned 32-bit integer in **big-endian** byte order:

`u32 = int.from_bytes(digest[0:4], byteorder="big", signed=False)`.

The descriptive paired-patient bootstrap seed is

`seed = (20260803 XOR u32) mod 2**32`.

Thus `seed` is in the closed range `[0, 2**32 - 1]`, which is passed as a non-negative Python integer to NumPy `PCG64`. This is the only allowed mapping from a stratum key to its bootstrap RNG seed. If the same canonical stratum key is eligible for both diagnostic heads, the same seed value is deliberately reused; each head still resamples its own frozen eligible-patient list.

### Ambiguity and support rules

Two mechanistic diagnostic families are fixed:

- **Target ambiguity:** only `COMPLETE` episodes; a development stratum is eligible only when both `SAME` and `NEW` are each represented by at least `8` distinct development patients and their union contains at least `12` distinct development patients.
- **Scope ambiguity:** only `SAME` episodes; a development stratum is eligible only when both `LOCAL` and `COMPLETE` are each represented by at least `8` distinct development patients and their union contains at least `12` distinct development patients.

The eligible-strata list is frozen and hashed at F0 before held-out access. Sparse development strata remain recorded but are `UNSUPPORTED`; they are not merged. If neither family has at least one eligible development stratum, fitting stops because the proposed distinguishing assay is unavailable.

At held-out reporting, an F0-eligible stratum is estimable only if each relevant label level has at least `5` distinct held-out patients and the union has at least `8`. A sparse held-out stratum is reported as `INSUFFICIENT_SUPPORT` with counts and no effect estimate; it is never pooled or replaced after seeing losses. If no held-out stratum is estimable, the primary endpoint may still receive its prespecified state, but no stronger state-relative mechanistic interpretation is allowed.

### Sampling role, replicate dimension, and exact estimands

The strata are **analysis-only**. They cannot affect the patient sampler, curriculum, augmentation, class weighting, episode eligibility, training order, early stopping, checkpoint choice, or primary patient weights.

Let the existing replicate dimension be the finite, ordered tuple

`\mathcal{R}=(r_1,...,r_R)`,

where the replicate identifiers and their order are exactly the pre-existing paired replicate rows in the frozen experiment matrix, `R = |\mathcal{R}| >= 1`, and the same tuple is required for `full` and `no_M0`. This repair creates, deletes, renames, or reorders no replicate. A diagnostic observation is eligible only when the prospectively eligible episode and both arm predictions exist for every `r` in `\mathcal{R}`. A missing, duplicate, or non-finite arm/replicate prediction blocks that diagnostic family; it is never dropped or imputed.

For diagnostic head `h` in `{target, scope}`, arm `a`, replicate `r`, patient `p`, and eligible episode `e`, compute the two-class natural-log loss directly from that head's two logits in IEEE-754 float64 with stable `log_softmax` and no clipping:

`\ell^a_{rpeh} = -log q^a_{rpeh}(y_{peh})`.

No logits or probabilities are averaged across replicates or episodes. Loss is computed separately for every eligible `(replicate, episode)` pair first.

For an estimable stratum `s`, define `E_{p,s,target}` as patient `p`'s eligible `COMPLETE` episodes in `s`, and define `E_{p,s,scope}` as patient `p`'s eligible `SAME` episodes in `s`. For either head `h`, compute the arm-specific patient contribution by averaging the already-computed binary losses within patient:

`L^a_{p,s,h} = (1 / (R * |E_{p,s,h}|)) * sum_{r in \mathcal{R}} sum_{e in E_{p,s,h}} \ell^a_{rpeh}`.

The patient contrast is `d_{p,s,h} = L^{no_M0}_{p,s,h} - L^{full}_{p,s,h}`. The frozen stratum estimand is

`\Delta^h_s = (1 / N_{s,h}) * sum_p d_{p,s,h}`,

over the `N_{s,h}` distinct held-out patients with at least one eligible episode for that head and stratum. Patients receive equal weight regardless of their numbers of cases, episodes, or replicate rows. Replicates and episodes are repeated measurements within patient, never inferential units.

Each descriptive 95% interval uses `B = 10,000` draws from the PCG64 seed derived above. The bootstrap unit is the **patient** within the fixed `(s,h)` eligible set: each draw samples `N_{s,h}` patient IDs with replacement and carries all selected patients' replicate-level and episode-level losses together, recomputes each selected patient's `L^a_{p,s,h}` from those losses, and then recomputes `\Delta^h_s`. Replicates, episodes, cases, lesions, scribbles, and voxels are never resampled independently. The interval is `numpy.quantile(draws, [0.025, 0.975], method="linear")`.

These diagnostics are not co-primary, have no pass/fail threshold, and cannot override the R1 decision. An operation-only difference, a geometry-determined pattern, or disappearance in these supported strata rejects the stronger state-relative interpretation even if the aggregate primary is positive.

## Repair R4 shared training schedule

The primary uses one **flat patient-first schedule**, shared without alteration by `full` and `no_M0`. No staged easy-to-ambiguous curriculum is used in the primary.

### Pairing, seeds, and infinite patient order

Retain every existing full/no_M0 experiment and replicate identifier. For each pre-existing paired row, F0 records a common `pair_id`. Encode the exact string `"T4-SM0-BLIND-01|" + pair_id` as UTF-8 without a trailing newline, compute SHA-256, parse the first eight hexadecimal characters as one unsigned base-16 integer, and define that value as `base_seed` in `[0, 2**32 - 1]`.

The paired arms use identical 32-bit sub-seeds:

- initialization: `base_seed`;
- patient/episode sampler: `sampler_seed = base_seed XOR 0x9E3779B9`;
- augmentation: `base_seed XOR 0x85EBCA6B`; and
- stochastic model operations: `base_seed XOR 0xC2B2AE35`.

All host-side NumPy sampling uses `PCG64`; framework RNG determinism flags and library versions are F0-manifested. The initial checkpoint is created once and loaded byte-for-byte by both arms.

Let `P` be the frozen set of eligible training-patient IDs, each represented by its exact canonical string and initially ordered by ascending UTF-8 byte sequence. `|P|` must be at least `4`; otherwise F0 stops because no legal four-distinct-patient batch can be formed.

Patient permutation cycles are indexed `k = 0, 1, 2, ...` without an upper bound. For cycle `k`, construct the canonical JSON array `["patient_cycle", sampler_seed, k]` with `ensure_ascii=False`, `separators=(",", ":")`, no whitespace, and no trailing newline, then encode it as UTF-8. Compute SHA-256 and interpret the first `16` digest bytes as an unsigned **big-endian** 128-bit integer in `[0, 2**128 - 1]`; this is the PCG64 seed for cycle `k`. Applying that RNG's permutation to the fixed base order of `P` gives raw permutation `P_k`.

Use the following deterministic infinite batching algorithm:

1. Initialize the carry list `C = []` and cycle index `k = 0`.
2. Generate `P_k`. If `C` is nonempty, stable-partition `P_k` into patients not in `C`, followed by patients in `C`, preserving raw `P_k` order inside both parts. Call the result `P'_k`. If `C` is empty, `P'_k = P_k`.
3. Form `W = C + P'_k`. Emit consecutive four-item batches from the front of `W` while at least four items remain. Retain the final `len(W) mod 4` items, in order, as the next carry `C`.
4. Increment `k` and repeat forever.

Every raw cycle contains every eligible patient exactly once. The stable boundary partition does not discard or duplicate an occurrence; it only moves next-cycle occurrences of carry patients behind all non-carry patients. Therefore, when a cycle boundary leaves one, two, or three patients, the next batch is completed by the earliest next-cycle patients not already in the carry, and every emitted batch contains exactly four distinct patients. No patient occurrence is silently dropped. F0 records each raw `P_k`, adjusted `P'_k`, carry-in, carry-out, and emitted batch. The first `20,000` emitted batches form the immutable training-order prefix for the fixed update budget.

### Per-patient episode permutation and advancement

For each patient `p`, let `E_p` be that patient's nonempty frozen list of locked eligible training-episode IDs, initially ordered by ascending canonical UTF-8 bytes. Maintain an independent zero-based episode-cycle index `c_p`, initialized to `0`, and a cursor into the current episode permutation.

To create episode permutation cycle `c_p`, serialize the exact JSON array `["episode_cycle", patient_id, sampler_seed, c_p]` with `ensure_ascii=False`, `separators=(",", ":")`, no whitespace, and no trailing newline; `patient_id` is the exact canonical string, while `sampler_seed` and `c_p` are JSON integers. Encode once as UTF-8, compute SHA-256, and interpret the first `16` digest bytes as an unsigned big-endian 128-bit integer in `[0, 2**128 - 1]`. Use that integer as the PCG64 seed to permute the fixed base order of `E_p`.

Whenever patient `p` appears in an emitted patient batch, consume exactly the next episode from that patient's current permutation. After the final episode of the permutation is consumed, mark that cycle exhausted; immediately before the next selection of `p`, increment `c_p` by exactly one, generate the new permutation with the rule above, reset the cursor to its first element, and consume from it. A cycle never advances early, episodes never spill between patients, and no label, ambiguity stratum, M0 value, joint rarity, or outcome enters the seed or order. A one-episode patient deterministically yields that episode once per successive cycle.

Before either arm trains, F0 serializes the first `20,000` patient batches, their selected episode IDs, per-patient episode-cycle indices and cursors, and augmentation parameters into one immutable `training-order-manifest.json`. Both arms consume the same rows in the same order.

### Optimizer, exact learning-rate equation, stopping, and checkpoint

- Optimizer: `AdamW`.
- Peak learning rate: `eta_max = 1.0e-4`.
- Minimum learning rate: `eta_min = 1.0e-6`.
- Betas: `(0.9, 0.999)`; epsilon: `1.0e-8`.
- Weight decay: `1.0e-4` on weight tensors; `0.0` on bias and normalization parameters.
- Gradient norm clipping: global L2 norm `1.0` after gradient aggregation and before each optimizer step.
- Batch: `4` patient-distinct episodes per optimizer update. If this exact batch does not fit the closed environment, F0 stops for a prospective amendment; arms may not silently differ.
- Budget: `T = 20,000` optimizer updates.
- Warm-up length: `W = 500` optimizer updates.
- Monitoring checkpoints: every `500` updates, for crash recovery and diagnostics only.
- Early stopping: none.
- Primary checkpoint: the exact post-update-`20,000` checkpoint for both arms. Validation performance cannot choose a different update or arm-specific checkpoint.

Optimizer updates are **one-based**, `u = 1, 2, ..., T`. Define the schedule-only pre-update anchor `eta_0 = 0`; there is no optimizer update at `u = 0`. The learning rate applied to optimizer update `u` is exactly

`eta_u = eta_max * (u / W)` for `1 <= u <= W`,

and

`eta_u = eta_min + 0.5 * (eta_max - eta_min) * (1 + cos(pi * (u - W) / (T - W)))` for `W < u <= T`.

Consequently, `eta_1 = 2.0e-7`, `eta_500 = 1.0e-4`, and `eta_20000 = 1.0e-6`. For each update, after the batch's gradients have been aggregated and clipped and immediately **before** `optimizer.step()` for that one-based update, write `eta_u` to every AdamW parameter group. The update counter advances only after that `optimizer.step()` succeeds. A resume restores the exact next one-based update index and recomputes `eta_u` from this formula; epoch labels or wall-clock time never affect the schedule.

The canonical loss heads, legality mask, augmentation family, and any already-frozen head weights remain unchanged and must be materialized in F0; absence of that canonical configuration is a stop, not permission for this repair to invent a new one. If either arm has a non-finite loss, incomplete order, missing update, or checkpoint/hash mismatch, the pair is invalid and no primary result is computed. Resume is allowed only from the last checkpoint whose update number, optimizer state, RNG state, and manifest prefix hash match in both arms.

Any flat-versus-staged schedule comparison is a separately authorized development-only audit with distinct future identifiers. It cannot inspect held-out outcomes, alter this schedule, select this checkpoint, enter the primary endpoint, or rescue a null, failed, or inconclusive full/no_M0 result.

## Unchanged experiment and scope

- PETCT-INTENT-v2.0 remains factorized as `operation={ADD,REMOVE}`, `target={SAME,NEW}`, and `scope={LOCAL,COMPLETE}`, with only the six legal joints listed above.
- The committed OOF M0 set remains exactly 597 cases and 378 patients with one patient-excluded held-out prediction per eligible case. It is an immutable upstream input, not a result, and is not regenerated, selected, substituted, or rerun.
- The patient-disjoint split, case and episode identities, scribble voxels and polarity, cue geometry, controlled/natural membership, construction seeds, frozen first-paper matrix, and every existing experiment identifier remain unchanged.
- The primary architecture remains the simple-first 17-channel model. The primary comparison remains `full` versus exhaustive `no_M0`. Polarity-blind and geometry-only remain diagnostic arms.
- Evaluation and resampling remain patient-level. Episodes, cases, lesions, scribbles, and voxels are not independent replicates.
- Cross-attention remains future work only. It cannot become the primary or a rescue arm.
- No real endpoint value, manifest hash, training receipt, metric, or scientific result is asserted here.

## Falsifiers and stops

The first operational blocker is unchanged: close and hash the exact deployed downstream bundle, environment, configuration, ordered 17-channel map, and F0 contract after the stale-bundle failure. Do not rerun OOF M0 as a workaround.

Before fitting, stop if any of the following occurs:

- any legal joint misses the separately frozen distinct-patient coverage gate, either illegal `NEW_LOCAL` joint appears, or no development-supported ambiguity family remains;
- an M0 provenance path is absent from (A_{M0}), any no_M0 neutral value is not exact, or byte, perturbation-invariance, shape, capacity, initialization, sampler, or training-order parity fails;
- patient aliases, duplicate/longitudinal exams, cases, episodes, scribbles, atlas derivatives, or resampling contributions cross partitions;
- the case-to-M0 binding, patient-excluded provenance, PET/CT/reference/M0/residual/scribble physical-coordinate chain, label provenance, or episode manifest is missing or inconsistent;
- reference masks, residuals, post-edit states, labels, IDs, filenames, administrative fields, generation order, arm identity, test outcomes, or held-out-derived thresholds can reach model inputs or development decisions; or
- any R1-R4 manifest is absent, unhashed, inconsistent with this document, or changed after held-out access.

After valid evaluation, the canonical state-dependence hypothesis is falsified when the R1 95% upper bound is at or below zero. The stronger state-relative interpretation is also rejected if any aggregate benefit is operation-only, legality- or geometry-determined, confined to coarse difficulty cells, absent in all adequately supported ambiguity strata, or reproduced by geometry-only diagnostics. An interval that satisfies neither continuation, falsification, nor equivalence compatibility is `INCONCLUSIVE`, not affirmative evidence.

No stop or unfavorable state may be repaired by changing the endpoint, margin, strata, sampler, update budget, checkpoint, split, episode set, experiment identifiers, OOF M0, or ontology, or by promoting cross-attention.

## Change ledger

| Repair | Replicated finding | Closed decision in this R3 document | F0 evidence still required | Truth status |
|---|---|---|---|---|
| R1 | `primary_endpoint_not_frozen` (3/3) | One exact six-legal-joint categorical log loss; equal episode/replicate averaging within patient and equal patient averaging; Δ direction fixed as no_M0 minus full; paired 10,000-draw patient bootstrap with fixed seeds and quantile algorithm; fixed `0.010`-nat margin; ordered four-state decision; strict paired completeness; one primary and no co-primary multiplicity. **Unchanged from R2.** | Materialize and hash `analysis-contract.json`, analysis population, paired replicate set, and software numeric settings before held-out access. | Prospective design decision only; no endpoint has been computed. |
| R2 | `no_m0_neutralization_not_frozen` (3/3) | Exhaustive transitive M0 provenance closure; mandatory path classes; normalized-space exact-zero treatment; no sampler/metadata route; identical shape/capacity/init; byte-level difference allowlist; non-M0 parity; three-way M0 perturbation invariance. **Unchanged from R2.** | Generate the real ordered 17-channel/path rows, graph attestations, neutral byte ranges, and SHA-256 for `m0-path-manifest.json` at F0. | Prospective intervention contract only; no parity test has run. |
| R3 | `ambiguity_strata_not_frozen` (3/3; first re-review `PARTIAL`) | Retains the R2 development-only covariates, bins, support rules, missing/sparse handling, and analysis-only role; now defines the exact existing ordered replicate tuple, computes binary natural-log loss separately for every eligible `(replicate, episode)`, averages those losses within patient without averaging logits/probabilities, gives patients equal weight, freezes the patient-cluster bootstrap unit, and canonically serializes the enum/integer stratum-key JSON bytes with an exact SHA-256 big-endian uint32-to-PCG64 seed mapping. | Compute development cut points/support without held-out access, serialize exact eligible strata and counts, bind the existing replicate tuple, and hash `ambiguity-strata-manifest.json` at F0. | Prospective diagnostic contract only; no stratum loss, interval, or result exists. |
| R4 | `curriculum_schedule_not_frozen` (3/3; first re-review `PARTIAL`) | Retains the R2 flat patient-first optimizer/budget/stopping/checkpoint choices; now defines infinite SHA-seeded patient cycles, deterministic carry handling for one-to-three-patient remainders with four distinct patients per batch, canonical per-patient episode-cycle seeds and exhaustion/reshuffle advancement, and one-based warm-up/cosine equations with exact boundary values and pre-`optimizer.step()` application. | Materialize and hash `training-schedule-manifest.json`, the first 20,000 rows of `training-order-manifest.json`, initial checkpoint, RNG/library record, and paired experiment mapping at F0. | Prospective training contract only; no sampler, optimizer update, or training run has occurred. |

R3 iteration delta, and only this delta:

1. In Repair R3, made the pre-existing replicate dimension, loss-before-aggregation order, equal-patient stratum estimand, patient bootstrap unit, canonical JSON bytes, SHA-256 byte order, and legal PCG64 seed reduction explicit.
2. In Repair R4, made the infinite patient permutation, sub-four boundary carry, per-patient episode cycle/exhaustion, canonical UTF-8/SHA-256 seed derivation, and exact one-based learning-rate function explicit.
3. Repair R1 and Repair R2 decisions are unchanged and remain closed. The ontology, simple-first 17-channel comparison, OOF artifact, splits, experiment identifiers, cross-attention boundary, and execution truth are unchanged.

All four consensus defects are closed at the design-decision level. None is represented as experimentally validated, and none permits scientific citation until the real F0 artifacts, execution receipts, patient-level analysis, and independent verification exist.

