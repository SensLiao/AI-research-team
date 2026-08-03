# Frozen Scientific Brief — SM0-01

## Decision request

Produce a design-only continuation decision for the current PET/CT project. Convert the intuition
“scribble intent depends on the current segmentation state” into an explicit hypothesis, implementable
mechanism, and falsifiable experiment without changing the frozen first-paper experiment matrix.

## Frozen facts

1. The current ontology is `PETCT-INTENT-v2.0`, not the retired ADD-only v1 ontology.
2. The three independent slots are:
   - `operation = ADD | REMOVE`
   - `target = SAME | NEW`
   - `scope = LOCAL | COMPLETE`
3. The six legal joints are `ADD_SAME_LOCAL`, `REMOVE_SAME_LOCAL`, `ADD_SAME_COMPLETE`,
   `REMOVE_SAME_COMPLETE`, `ADD_NEW_COMPLETE`, and `REMOVE_NEW_COMPLETE`. Both `NEW_LOCAL` joints
   are illegal.
4. Scribble construction precedes intent. FN residuals produce positive ADD scribbles; FP residuals
   produce negative REMOVE scribbles. AutoPET V geometry supports centerline, random, and boundary.
5. The OOF M0 set is already committed: 597 cases, 378 patients, exactly one patient-excluded held-out
   prediction per eligible case. It is an upstream input, not a citable result, and must not be rerun.
6. The enclosing downstream run failed before M0 evaluation because the deployed software bundle was
   stale. The next valid step is exact downstream bundle/F0 closure, then M0 evaluation, FN/FP atlas,
   signed scribble generation, controlled/natural episodes, P2T, editor, external comparators, and
   patient-level statistics.
7. The first-paper P2T primary is frozen as a simple 17-channel state/cue model with state/cue-support
   pooling plus a geometry MLP and heads for joint/operation/target/scope.
8. The first-paper primary contrast is `full` versus `no_M0`. Polarity-blind and geometry-only are
   diagnostic arms.
9. Cross-attention, FiLM, gated fusion, and PET↔CT modality fusion are deferred ablations/future work.
   They must not silently replace the simple-first primary.
10. No v2 six-class P2T/editor training, inference, metric, effect estimate, external-comparator result,
    or publication-level conclusion exists.

## Required output

- State one hypothesis and its strongest alternative.
- Define the mechanism at the interface level: inputs, representation, transformation, output, and
  distinguishing signal.
- Specify the minimum comparison that tests state dependence while holding split, scribble, backbone,
  optimizer, and training budget fixed.
- Use patient-level analysis and name leakage checks, a concrete falsifier, and a stop condition.
- Identify the first operational blocker without proposing an OOF rerun.
- State where cross-attention belongs after respecting the current canonical.

## Forbidden claims

- Do not claim state-relative intent is effective or novel.
- Do not claim the six classes are empirically feasible before the FN/FP atlas coverage gate.
- Do not claim cross-attention is the current primary model.
- Do not claim a server is idle, healthy, or running a task from this frozen local brief.
- Do not turn scripts, checkpoints, OOF readiness, or a design review into a scientific result.

