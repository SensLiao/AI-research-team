---
title: "Evidence Contract (anti-hallucination 9-clause spec)"
type: routing
status: active
confidence: high
created: 2026-05-01
updated: 2026-05-01
canonical: true
aliases:
  - anti-hallucination
  - evidence-contract
  - citation-discipline
---

# Evidence Contract

> **Premise.** Hallucination is most expensive at three points: (a) inventing a function / module / attribute name during a code edit, (b) citing a metric value when writing thesis text, (c) recommending an action based on a stale memory.
>
> **Contract.** Before any code change, any metric claim, or any recommendation, the agent must declare the **evidence class** for every fact it relies on, and run the inspection commands the contract requires.
>
> This contract is enforceable by the user — at any point the user can ask "show me the evidence for X" and the agent must paste it from this session, not reconstruct it.

---

## Part 1 — Evidence classes (label every fact you cite)

Every claim in tool-call commentary or final response must be traceable to one of:

| Class | Source | Example | When to use |
|---|---|---|---|
| **CODE-LIVE** | A file actually `Read` in this session, with line citation | `train_lora.py:579 says "memory_attention"` | Whenever you cite a function / class / attribute / module / file / parameter / config-key name |
| **VAULT-CITE** | A page in `02-wiki/` actually `Read` this session | `[[claim-prompt-bridges-gap]] §"Evidence chain"` | Whenever you cite a project rule, prior decision, or canonical synthesis |
| **EXP-RESULT** | A `metrics.json` / numpy array / log file actually opened this session, with path | `runs/run-003/metrics.json: dice=0.4912` | Whenever you cite a benchmark / training / inference number |
| **PAPER-CITE** | A paper page in `02-wiki/papers/` actually `Read` this session | `[[ravi-2024-sam-2]] §3.2 — memory bank size = 6` | Whenever you cite an external claim |
| **DATA-CITE** | A dataset page in `02-wiki/datasets/` actually `Read` this session | `[[example-dataset]] §"Split" — 800/100/100` | Whenever you cite a dataset size, label set, or split |
| **MEETING-CITE** | A meeting page actually `Read` this session | `[[meeting-2026-04-29-supervisor]] §"Decisions"` | Whenever you cite a supervisor instruction or team decision |
| **DECISION-CITE** | A `02-wiki/decisions/dec-*.md` page actually `Read` this session | `[[dec-0007-fixed-split]] §"Rationale"` | Whenever you cite a prior locked decision |
| **ASSUMPTION** | An inference NOT backed by any of the above | "I assume detector LoRA is frozen during inference" | Whenever none of the above applies |

**The default for any unlabeled claim is `ASSUMPTION`.** Never let a CODE-LIVE / VAULT-CITE / EXP-RESULT / PAPER-CITE / DATA-CITE / MEETING-CITE / DECISION-CITE claim go un-cited — that is silent hallucination.

---

## Part 2 — The 9-clause contract

### Clause 1 — Cite exact paths

Every CODE-LIVE claim cites `<absolute_path>:<line_range>`. Every VAULT-CITE / PAPER-CITE / etc. claim cites `[[slug]] §<heading>`. Every EXP-RESULT cites `<absolute_path>` (file) or `<absolute_path>:<key>` (JSON).

❌ "The wrapper loads detector LoRA"
✅ "`run_inference.py:482-490` loads detector LoRA from `weights/best_lora.pt` (CODE-LIVE)"

### Clause 2 — Label evidence class

Every paragraph that mixes evidence classes labels each. End any non-trivial claim with the class tag.

❌ "Dual-LoRA is the canonical inference graph since PM16."
✅ "Dual-LoRA is the canonical inference graph since PM16 (VAULT-CITE [[pm-0016-dual-lora]])."

### Clause 3 — Assumptions are labeled, not hidden

If an assumption is load-bearing, it goes on its own line prefixed `ASSUMPTION:`, with what would invalidate it.

❌ "The wrapper should also work for model B."
✅ "ASSUMPTION: the wrapper should also work for model B because both share the tracker module. Invalidated by: any model-B-specific carve-out in the upstream repo — verify before generalizing."

### Clause 4 — No invented identifiers

Never write a function / class / attribute / module / file / parameter / config-key name without grepping for it in the live code first. If grep returns 0 hits, the name does not exist.

Mandatory pre-action: for any name about to be referenced in a code edit OR in a recommendation, grep the actual file. Paste the grep result.

❌ "Add `model.tracker.memory_attention.lora` to the inject list" (the attribute may not exist)
✅ "Confirmed via `grep -rn 'self\\.transformer' model/tracker.py` → match at L90 `self.transformer = transformer` (CODE-LIVE). Add `model.tracker.transformer.lora`."

### Clause 5 — Inspect before you patch

Before making a code edit or recommending one, the agent runs at least one inspection command on the actual current state.

| About to … | Required inspection first |
|---|---|
| Add a LoRA inject target | `grep` for the target attribute path in the live model class file |
| Change a checkpoint loader | `python -c "import torch; ck = torch.load('<path>'); print(list(ck.keys())[:20])"` |
| Modify a yaml config | `Read` the yaml file fully, paste the keys you are about to touch |
| Fix a "metric is too low" | `Read` the actual `metrics.json` and the actual data on disk |
| Edit an aug pipeline | `Read` the matching upstream `data_utils.py` augmentation section |
| Patch a remote file | SFTP `get` the current file BEFORE the patch, diff against local mirror, paste the diff |

Skipping inspection because "the code probably looks like X" is the entry point for hallucination.

### Clause 6 — Before recommending from memory, verify

The agent's training-data memory of how a library, model, or codebase works may be wrong, stale, or generic. Before recommending an action based on remembered API knowledge:

1. **Check the actual installed version.** `pip show <pkg>` or `import <pkg>; print(<pkg>.__version__)`.
2. **Open the actual library code** in the env's site-packages if the API is non-obvious.
3. **Cite it as CODE-LIVE**, not as ASSUMPTION-from-memory.

Special case: **before recommending a function / file / flag mentioned in a vault PM**, verify it still exists. PM rules can become stale — the vault page might cite a function that has since been renamed. "Memory says X exists" is not the same as "X exists now".

### Clause 7 — Confidence labels are mandatory for any recommendation

Every recommendation ends with one of:

| Label | Meaning | Allowed when |
|---|---|---|
| **HIGH** | Verified by direct inspection this session + matching VAULT-CITE for the rule | Default for canonical-rule recommendations |
| **MEDIUM** | Either inspection OR vault rule, not both | Use when one half is missing and you note which |
| **LOW** | ASSUMPTION-based; no direct evidence yet | Use when you are sketching a hypothesis the user will validate |

If the recommendation triggers an irreversible action (overwrite a file, kill a process, push to remote, drop a result), the label MUST be HIGH and the user MUST confirm before execution.

### Clause 8 — Result-validity discipline

Before quoting any number from `02-wiki/results/`:

1. Confirm which run produced it (run-id from the result page).
2. Confirm the result has not been invalidated by a later PM.
3. Confirm `result-status: frozen` AND `can-cite-thesis: true`.
4. Confirm the result is from the canonical eval frame (not in-training metrics).

If any check fails, do not quote the number; flag it and route to the canonical replacement.

This clause delegates to the citation gate in `00-system/AGENTS.md` §2.

### Clause 9 — Uncertain → inspect, never guess

If at any point the agent is about to write "I think" / "probably" / "should" / "可能" / "应该是" about a fact that an inspection command could resolve in < 30 seconds, the agent **must run that command first**.

This is the single highest-yield anti-hallucination behavior. Most fabrications happen because the agent guessed when grep would have answered.

---

## Part 3 — Self-check before sending any user-visible response

Before the response leaves the agent, scan it once for:

- [ ] Every CODE-LIVE / VAULT-CITE / EXP-RESULT / PAPER-CITE / DATA-CITE / MEETING-CITE / DECISION-CITE claim carries an explicit citation
- [ ] Every ASSUMPTION is labeled
- [ ] No invented function / module / attribute / file name
- [ ] Every recommendation has a confidence label
- [ ] Every quoted metric passes Clause 8 invalidation check
- [ ] Any "I think" / "probably" wording was either resolved by inspection or relabeled as ASSUMPTION

Failing any check = redraft the response, do not send.

---

## Part 4 — User-facing escape hatches

The user can invoke any of these at any time, and the agent must comply:

| User says | Agent must |
|---|---|
| "show me the evidence for X" | Paste the exact evidence artifact, not paraphrase |
| "did you actually read that page?" | If no Read happened this session, admit it and Read the page now before re-answering |
| "did you actually run that command?" | If no Bash / inspection happened, admit it and run it now |
| "how confident are you?" | Apply Clause 7 labels with explicit reasoning |
| "what could invalidate this?" | List the conditions under which the recommendation would flip |
| "ignore memory" | Apply Clause 6 inverse — disregard remembered facts, verify everything from current files |

---

## Part 5 — Anti-pattern catalog

Concrete patterns that violate the contract. If the agent catches itself doing one of these, halt and re-route.

| Anti-pattern | Why it violates | Fix |
|---|---|---|
| "Based on standard PyTorch behavior, …" | Memory-from-training-data without verifying installed version (Clause 6) | `python -c "import torch; print(torch.__version__); help(torch.<thing>)"` |
| "Model X typically loads weights via …" | Generic memory of "what models like this do" | Grep the actual loader code |
| "The metric is around 0.5" | Unsourced approximate quote (Clause 1 + 8) | Open the metrics file, paste the exact value |
| "I'll just remove the assert and re-run" | Loosening a check to make a test pass | Identify root cause first |
| "The loader should handle this" | Unverified assumption about loader behavior (Clause 5) | Run the loader on the actual file and inspect output |
| Recommending a slug `[[foo]]` without checking `index.md` | Invented slug (Clause 4) | Grep `index.md` for the slug |
| "PM<N> says X" without re-reading PM<N> this session | Memory of a vault rule (Clause 6) | Re-Read the PM page before citing |
| Pasting code with `model.tracker.<invented_attr>` | Invented attribute (Clause 4) | Grep the live class file; cite the actual attribute |
| "This should fix it; let me know if it works" | Recommending an irreversible action with LOW confidence (Clause 7) | Run smoke first, then recommend HIGH |

Update Part 5 whenever a new hallucination class is observed in practice. The catalog grows; the 9 clauses stay short and stable.
