---
title: ""
type: negative-result
status: active
confidence: high
created: YYYY-MM-DD
updated: YYYY-MM-DD
project: <project-slug>
rq: []
contrib: []
domain: []
tags: []
related: []
source:
aliases: []
evidence-class: EXP-RESULT
owner: <agent-id-or-name>
reviewed:
review-cycle: 180

# Negative-result specific
tried-method: ""              # [[method-slug]] that was attempted
failure-mode: ""              # short label: "did not converge" | "metric collapsed" | "OOM" | etc.
would-have-served-rq: []
cost-gpu-hours: 0.0
re-tryable-when: []           # conditions under which re-attempt would be reasonable
related-pm: ""                # [[pm-slug]] if this discovery led to a PM entry
---

# Negative result: {Method tried for what purpose}

> A documented failure. Worth keeping so future agents (and future you) don't repeat the experiment.

## What was tried

<brief description of the method, the experiment, the run>

- Method: [[method-slug]]
- Experiment: [[experiment-slug]]
- Run(s): [[run-slug-1]], [[run-slug-2]]
- Cost: {cost-gpu-hours} GPU-hours

## What was expected

<the prediction that motivated the experiment>

## What actually happened

<observed behavior; metrics; failure mode>

| Metric | Expected | Actual |
|---|---|---|
| | | |

## Why it failed (and why that matters)

<best understanding of the failure cause; cite EXP-RESULT and CODE-LIVE evidence. Distinguish: attribution error (wrong method), data issue, hyperparameter issue, fundamental incompatibility.>

## Conditions & caveats

<be precise about the conditions under which this failure was observed — dataset, scale, hyperparameters, environment. Avoid over-generalizing: "failed on X" ≠ "will always fail". What specific preconditions made this outcome likely?>

- Dataset / distribution:
- Scale / hardware:
- Key hyperparameters that were fixed:
- Other constraints:

## What this rules out

<what hypothesis is now considered weakened or refuted; which RQ sub-question can be deprioritized>

## What this does NOT rule out

<close variants that might still work; conditions where the method might apply; what would need to change for a revisit to be justified>

## Do-not-retry-unless

**Decision gate:** do NOT re-run this experiment unless ALL of the following conditions hold:

- [ ] <condition 1 — e.g., new dataset with characteristic X>
- [ ] <condition 2 — e.g., compute budget ≥ N GPU-hours>
- [ ] <condition 3 — e.g., related PM-NNNN resolved>

<If no plausible change would make a retry justified, write: "No known change would justify a retry — mark as permanently falsified for this project scope.">

## Related PM (if discovery created a permanent rule)

- [[pm-NNNN-...]]

## Links
- [[method-slug]] — the method tried
- [[claim-slug]] — claim this would have served (if applicable)
- [[dec-NNNN-...]] — decision recorded after this failure
