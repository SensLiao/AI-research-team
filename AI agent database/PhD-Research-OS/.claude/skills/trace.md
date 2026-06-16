---
name: trace
description: "Walk a claim back to its raw evidence — wiki → raw"
when_to_use: "When verifying where a claim or number came from. Useful before citing in thesis."
usage: "/trace <claim-or-slug>"
---

# /trace

Reverse traversal: claim → wiki page(s) → raw source(s).

## Procedure

1. Identify the claim's wiki page (a `[[claim-slug]]` or `[[result-slug]]` or `[[paper-slug]]`).
2. For a `result`: walk `experiment` → `run` → `metrics-file` and `evidence-artifact`. Open the actual JSON / log on disk.
3. For a `claim`: walk `evidence-for` → each evidence page → repeat (recurse).
4. For a `paper`: walk `source:` → the raw PDF or extracted text file.
5. Stop at `01-raw/` or at an external citation.

## Output

```
Claim: <restated>

Trace:
[[claim-slug]]
  ├─ supports-contrib: C1
  ├─ evidence-for:
  │   ├─ [[result-slug]]
  │   │   └─ run: [[run-slug]]
  │   │       ├─ metrics-file: <path>
  │   │       │   └─ value: 0.491
  │   │       └─ git-commit: <SHA>
  │   └─ [[paper-slug]]
  │       └─ source: 01-raw/papers/<file>.pdf §3.2
  └─ audit:
      ├─ leakage: pass — see [[run-slug]] §audit
      ├─ fairness: pass — see <audit-doc>
      └─ reproducibility: pass — env-lock matches

Verdict: claim is <citable | not-citable>
Reason: <if not citable, what's blocking>
```

## Rules

- Open every cited file in this session — don't trust memory.
- If a step is missing (e.g., `run.metrics-file` is empty), surface that as a blocker.
- For results, gate through `00-system/AGENTS.md` §2 (citation gate).
