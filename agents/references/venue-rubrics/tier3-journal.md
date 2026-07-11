# Tier 3 — Archival Journals Rubric

> Venues: **Nature · Nature Methods · Nature Medicine · TPAMI (IEEE Trans. Pattern Analysis & Machine Intelligence)**
> Confidence: HIGH for Nature-family structure; MEDIUM for TPAMI maturity standard.
> **Login-state re-check REQUIRED for all venues in this tier** (see _index.md).

---

## 1. Journal-tier characteristics (vs conf/med)

Journals differ from conferences in three critical ways:
1. **D2 is gating** (not just high-weight): a conceptually correct but incremental paper that does not
   advance the field's thinking gets a Major Revision or Reject regardless of D1/D4.
2. **D5 is a mandatory gate**: code/data must be publicly available or reproducible from the manuscript.
   "Available upon request" is no longer acceptable at Nature-family or TPAMI.
3. **Maturity bar** (TPAMI): a journal paper must be a **substantial extension** of any prior conference
   version — typically 30%+ new material; purely same work repackaged is out of scope.

---

## 2. Nature (Nature, Nature Methods, Nature Medicine)

### Nature — referee 7 questions (canonical reconstruction)

> Confidence: HIGH for structure. Individual wording: MEDIUM-HIGH. Verify verbatim at login.

The Nature referee process is structured around 7 implicit questions:

1. **Significance** (D2): "Does this work address an important question? Will it influence how
   others think about or approach the problem?"
2. **Novelty** (D3): "Is this a substantial conceptual advance? Is the work clearly differentiated
   from prior work?"
3. **Evidence strength** (D1): "Are the conclusions justified by the data? Are claims made beyond
   what the data support?"
4. **Methodological rigor** (D4): "Are the methods appropriate and correctly applied? Are
   comparisons fair? Are controls adequate?"
5. **Reproducibility** (D5): "Is there sufficient methodological detail for reproduction? Is code/data
   publicly available?"
6. **Clarity** (D6): "Is the paper clearly written and well-organized? Are figures informative?"
7. **Ethics / Registration** (non-scoring): "Are ethics approvals documented? Is clinical trial
   registration present where required?"

### Nature dimension calibration

```
D1: weight=0.18, gating=true
D2: weight=0.22, gating=true   ← conceptual advance required; incremental → reject
D3: weight=0.20, gating=true   ← strong novelty required; not just "new data"
D4: weight=0.18, gating=false
D5: weight=0.12, gating=true   ← code/data mandatory gate
D6: weight=0.10, gating=false
D7: weight=0.00, gating=false  ← OFF for general Nature
```

---

### Nature Methods

- Core question: "Does this method enable something not previously possible, or substantially improve
  on existing methods in a reproducible way?"
- **D4 unfair-benchmark emphasis** (the #1 reject cause): "Are comparisons to existing methods fair?
  Are methods run under identical conditions? Are existing methods used at their published hyperparameters
  or properly re-optimized?" — unfair benchmark is explicitly named as top reject cause.
- **D5 mandatory**: Code + data required. "Method papers must provide source code deposited in a
  public repository. Requests for code on demand are not acceptable."
- **D3**: "Is this a genuinely new capability? Incremental parameter tuning of an existing method is
  not sufficient."

### Nature Methods dimension calibration

```
D1: weight=0.17, gating=true
D2: weight=0.18, gating=true
D3: weight=0.20, gating=true
D4: weight=0.25, gating=false  ← unfair-benchmark is #1 reject; highest weight
D5: weight=0.14, gating=true   ← mandatory gate
D6: weight=0.06, gating=false
D7: weight=0.00, gating=false  ← OFF (unless Nature Medicine route)
```

---

### Nature Medicine

- **paper_type = `application-clinical` is the norm** — basic science papers exist but clinical
  translation is the editorial priority.
- **D7 mandatory human evidence**: "Papers must present human subject data where the question is
  clinically relevant. Animal models alone are insufficient for clinical-facing conclusions."
  This is the defining Nature Medicine rule.
- **D2 clinical significance**: "Does this address a clinically important question? Will it change
  clinical practice or understanding?"
- **D5**: Same Nature mandatory code/data standard.

### Nature Medicine dimension calibration

```
D1: weight=0.17, gating=true
D2: weight=0.20, gating=true   ← clinical significance gating
D3: weight=0.15, gating=false  ← novelty important but secondary to clinical translation
D4: weight=0.18, gating=false
D5: weight=0.12, gating=true   ← mandatory
D6: weight=0.08, gating=false
D7: weight=0.10, gating=true   ← human evidence mandatory for application-clinical
```

---

## 3. TPAMI (IEEE Transactions on Pattern Analysis and Machine Intelligence)

> Confidence: MEDIUM — maturity/extension standard derived from second-hand reviewer guide.
> Verify against current IEEE TPAMI author instructions before citing.

- **Maturity bar**: A TPAMI submission that extends a conference paper must have "a substantial
  body of new material" — typically ≥30% new content (new experiments, new theory, or new tasks).
  Essentially same conference paper repackaged is rejected.
- **D5 (Reproducibility)**: Strong expectation. IEEE TPAMI expects code/data availability.
- **D3**: "Does the paper advance the state of the art in a significant way? Is the contribution
  sufficiently beyond an incremental improvement?"
- **D2 significance**: "Is the problem important to the pattern analysis and machine intelligence
  community? Does the result have lasting impact?"
- **D4**: Standard rigor requirements plus journal-level: more thorough ablation expected than
  conference version.

### TPAMI dimension calibration

```
D1: weight=0.17, gating=true
D2: weight=0.18, gating=false  ← weighted but not strict gate
D3: weight=0.20, gating=true   ← substantial novelty beyond conf version required
D4: weight=0.22, gating=false
D5: weight=0.13, gating=false  ← strong expectation; not strict gate but notable deficiency
D6: weight=0.10, gating=false
D7: weight=0.00, gating=false  ← OFF for TPAMI
```

---

## 4. Reject-triggers active at tier 3 (journal)

All 7 standard triggers apply. Most commonly fired at journal venues:
- **RT-D2-INCR** — incremental without conceptual advance (gating; most distinctive journal trigger)
- **RT-D5-REPRO** — code not publicly available (hard gate at Nature-family)
- **RT-D4-BASELINE** — unfair baselines (Nature Methods #1 reject cause)
- **RT-D1-OVERCLAIM** — conclusion beyond data
- **RT-D7-CLINICAL** — no human evidence (Nature Medicine; application-clinical papers)
- **RT-TPAMI-MATURITY** — conference extension without substantial new content (TPAMI-specific)

---

## 5. Anti-bias suppressors in force at tier 3

All 6 standard suppressors apply. Additional journal-tier notes:
- Do NOT treat "did not beat SOTA on all benchmarks" as fatal if the conceptual contribution is clear.
- At TPAMI: do NOT reject a conference extension solely because it overlaps with the conference
  version — overlap is expected; ask "is there ≥30% new, not just expanded intro/related work?"
