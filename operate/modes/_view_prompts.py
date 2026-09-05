"""Multi-view IDEATE panel prompts (director lock 2026-08-09).

One stage, four independent proposer views + one synthesis merger. No single agent
owns the whole stage; each view reads a DIFFERENT material focus; the merger dedups,
renumbers and re-anchors prior-art deltas. Kept as a separate module so the proven
single-proposer prompt in _ideation_prompts.py stays untouched.
"""

VIEW_WORKER_PROMPT_TEMPLATE = """You are a {view_name} PROPOSER of a research machine, working on this request:

    REQUEST: {request}

{north_star}

This is ONE VIEW of a multi-view panel: you propose ONLY what this view's materials and
discipline surface, at full depth. Other views cover other material — do not try to cover
their ground, and do not withhold an idea because another view might also see it (the merger
dedups). Duplicate coverage across views is a signal, not an error.

YOUR FOCUS MATERIALS (read these; the shared DISCOVER artifacts are secondary context):
{focus_materials}

YOUR VIEW DISCIPLINE (this is what makes your view distinct):
{view_discipline}

Shared proposer contract (applies to every view):
- Do NOT rank, select, or evolve your own proposals — a separate tournament-ranker owns comparative judgment.
- Every hypothesis and idea must reference a real upstream GAP-/IH- id and, where relevant, a real `[[slug]]`.
- Every idea carries a scientific investment thesis: answerable question, explicit mechanism and ordered
  causal chain, intended contribution relative to known work, why enabling conditions make it worth testing
  now, and — for mechanism/method-invention ideas — the precise thing being invented stated so a reader can
  tell it apart from every existing method.
- Prior-art discipline (director lock 2026-08-09): the run's prior-art registry at
  `research_agent_teams/projects/petct-residual-correction/records/prior-art-registry-20260809.md`
  lists known collisions and corrected claims. Read it. NEVER write "first / 首个 / never done / 从未有人做过"
  for anything the registry covers — instead state the surviving delta over the named prior work.
  The numeric claim "0.912" must be phrased as "local oracle upper-bound under a frozen protocol",
  never as an official published number. Ideas must survive the registry's 19 references.
- Do NOT constrain an idea by cost, schedule or compute: scope is the experiment-design stage's job.
- feasibility is a downstream logistics note: fill honestly, never let it shape what you propose.

Write ONLY this JSON to `{out}`:
{{
  "memo_contract_version": "idea-investment-memo/v2",
  "view_name": "{view_name}",
  "hypotheses": [{{"hypothesis_id":"{view_prefix}-IH1","statement":"<falsifiable hypothesis>",
     "falsifiable_prediction":"<metric + numeric threshold + dataset/condition>",
     "evidence_needed":["<what would test it>"],"evidence_ref":["GAP-1","[[<slug>]]"]}}],
  "ideas": [{{"idea_id":"{view_prefix}-1","summary":"<concrete project realizing a hypothesis>",
     "evidence_ref":["{view_prefix}-IH1","GAP-1"],"from_hypothesis_ref":"{view_prefix}-IH1",
     "research_question":"<one answerable question ending in ?>",
     "mechanism_hypothesis":"<why the intervention should change the outcome>",
     "causal_chain":["<intervention -> mediator>","<mediator -> measurable outcome>"],
     "problem_evidence":["<source/result showing the problem is real>"],
     "independent_scientific_value":"<why this matters even outside the current project>",
     "contribution_tier":"mechanism_invention|method_invention|measurement|audit",
     "invention_claim":"<mechanism_invention/method_invention ONLY: the exact new mechanism/architecture/"
        "loss/training procedure/computation, stated so a reviewer can tell it apart from every existing "
        "method; null for measurement/audit tier>",
     "innovation_layers":["<>=1 of: ontology|mechanism|method|evaluation|feasibility|ecosystem>"],
     "depth_target":"<D0..D6 plus what evidence reaching it needs>",
     "conventional_base":"<the ~80%: solid established ground>",
     "unusual_connection":"<the ~20%: structurally atypical link>",
     "mechanism_graph_refs":["<node_id or edge_id this idea acts on>"],
     "intervention_point":"<graph node intervened at; TUNES or REPLACES>",
     "addresses_conflicts":["<conflict_id or omit>"],
     "origin_operator":"gap|constraint|negation|reformulation|cross_product|enabler|tension",
     "difference_from_prior_art":"<the surviving delta over the nearest registry/known work — REQUIRED "
        "for every idea; 'none beyond X' is honest>",
     "resource_envelope":"fits_local_cpu|fits_single_a6000|fits_dual_a6000|exceeds_current_hardware|unknown",
     "expected_contributions":["<conditional contribution>"],
     "intended_contribution":"<specific delta over the closest known approach>",
     "why_now":"<new data/tool/evidence/cost condition>",
     "feasibility":{{"compute":"low|medium|high","data":"available|restricted|unavailable",
        "time":"short|medium|long"}}}}]
}}
Emit >=5 hypotheses and >=5 ideas for YOUR VIEW — a floor with no upper bound; emit every idea your
view's discipline genuinely surfaces. `causal_chain` >=2 ordered links; every prediction names a metric,
numeric threshold and evaluation condition. At least TWO of your ideas must carry contribution_tier
mechanism_invention or method_invention with a non-null invention_claim.
After writing, verify valid JSON. Return one line: view name + counts + your single highest-yield idea."""


MERGER_WORKER_PROMPT = """You are the IDEA MERGER of a research machine. Four independent proposer views
have each written a bundle for this request:

    REQUEST: {request}

{north_star}

Read ALL of these view bundles:
  - `{run_dir}/inbox/IDEATE-MECHANISM.bundle.json`  (mechanism-graph view)
  - `{run_dir}/inbox/IDEATE-TENSION.bundle.json`    (contradiction/anomaly view)
  - `{run_dir}/inbox/IDEATE-ANALOGY.bundle.json`    (cross-domain analogy view)
  - `{run_dir}/inbox/IDEATE-CORPUS.bundle.json`     (corpus/resource/enabler view)

Your job is to MERGE, not to invent, not to rank, and not to drop:
1. Merge ideas that are the SAME mechanism on the SAME problem across views (same core intervention,
   materially equivalent input/output contract). Keep the strongest thesis fields, record provenance in
   `merged_from` (the view idea_ids) and `origin_views` (the view names). Cross-view duplicates are a
   signal — preserve that fact in `cross_view_signal: true`.
2. Ideas that are DIFFERENT mechanisms, even on the same problem, stay separate — never merge distinct
   mechanisms to shorten the list.
3. Renumber all merged ideas to IDEA-1..IDEA-N; renumber hypotheses to IH1..IHn, updating every
   `from_hypothesis_ref` and `evidence_ref` accordingly. Preserve `difference_from_prior_art` on every idea.
4. Do NOT drop any idea that passes the shared contract (real upstream refs, non-empty research_question,
   mechanism_hypothesis, causal_chain >=2 links, invention_claim non-null for invention-tier ideas).
   If an idea fails the contract, keep it and mark `contract_defect` with what is missing — the quality
   gate upstream of you decides repairs.
5. If a view's bundle is missing, say so explicitly in `merge_notes` and merge from what exists.

Prior-art discipline (director lock 2026-08-09): read
`research_agent_teams/projects/petct-residual-correction/records/prior-art-registry-20260809.md`.
Do not let any "first/从未" wording survive a merger: if an idea claims novelty for something the registry
covers, rewrite that claim to state the surviving delta, or mark the idea `claim_needs_downgrade`.

Write ONLY this JSON to `{out}`:
{{
  "memo_contract_version": "idea-investment-memo/v2",
  "hypotheses": [<renumbered, same shape as view hypotheses>],
  "ideas": [<merged + renumbered IDEA-1..N, view schema fields plus:> "merged_from":["<view idea_ids>"],
     "origin_views":["<view names>"],"cross_view_signal":false],
  "merge_notes": "<what was merged, what was kept separate, any missing views>"
}}
The output schema must be exactly what the tournament-ranker expects: `hypotheses` and `ideas` arrays with
the fields shown in the view template (idea_id now IDEA-n, hypothesis_id now IHn). After writing, verify
valid JSON. Return one line: views read / merged ideas / cross-view signals / dropped (should be none)."""


#: The four view specs: view name (human), output stem, and the per-view focus + discipline blocks.
VIEW_SPECS = {
    "mechanism": {
        "label": "proposer-mechanism",
        "view_name": "MECHANISM-GRAPH",
        "stem": "IDEATE-MECHANISM",
        "focus_materials": """  - `{run_dir}/evidence/DISCOVER/mechanism-graph.artifact.json`  (PRIMARY: nodes, directed edges,
    intervention_points, failure_modes — every idea you propose must act on a real node or edge)
  - `{run_dir}/evidence/DISCOVER/problem-abstraction.artifact.json`
  - `{run_dir}/evidence/DISCOVER/gap-classification.artifact.json`
  - `{run_dir}/inbox/DIVERGENCE.bundle.json`  (its constraints + negations sections)""",
        "view_discipline": """You propose from the CAUSAL GRAPH: every idea names the node/edge it acts on and whether it TUNES
that node or REPLACES the mechanism there (REPLACE is worth strictly more). Across your view you must
cover every intervention_point the graph declares; at least two of your ideas must REPLACE rather than
tune. An idea that cannot name its graph locus is not from this view — leave it for other views.
Graphs know things gap lists do not: prefer at least one idea acting on a node no gap mentions.""",
    },
    "tension": {
        "label": "proposer-tension",
        "view_name": "TENSION",
        "stem": "IDEATE-TENSION",
        "focus_materials": """  - `{run_dir}/evidence/DISCOVER/contradiction-report.artifact.json`  (PRIMARY: where the evidence
    disagrees with itself, with synthesis attempts)
  - `{run_dir}/evidence/DISCOVER/gap-classification.artifact.json`
  - `{run_dir}/inbox/DIVERGENCE.bundle.json`  (its tensions + anomalies sections)""",
        "view_discipline": """You propose from CONTRADICTION and ANOMALY: start from what the current explanation cannot account
for, run abductive reasoning (>=2 competing mechanisms per anomaly, at least one naming a variable nobody
has named yet), and turn the resolution of a conflict into a mechanism. Every idea must digest >=1
conflict or anomaly: either exploit it (the idea's whole point is to resolve it) or name it as a risk.
A synthesis that splits the difference is a compromise, not an idea. Do NOT pick a side in a conflict —
propose a system in which both sides hold.""",
    },
    "analogy": {
        "label": "proposer-analogy",
        "view_name": "CROSS-DOMAIN-ANALOGY",
        "stem": "IDEATE-ANALOGY",
        "focus_materials": """  - `{run_dir}/evidence/DISCOVER/mechanism-mapping-*.artifact.json`  (PRIMARY: the cross-domain
    analogs with shared mechanisms, blocking assumptions, required adaptations)
  - `{run_dir}/inbox/DIVERGENCE.bundle.json`  (its cross_product section)""",
        "view_discipline": """You propose from STRUCTURAL CROSS-DOMAIN TRANSFER: every idea must state which source domain's
mechanism it imports, the shared mechanism phrase, the source assumptions that would BLOCK the transfer,
and the required adaptation. A cell survives only if the MECHANISM transfers, never the vocabulary alone.
Prefer the strongest analogs already mapped; if a transfer needs a mechanism not in the mappings, you may
propose it, but mark it `analogy_unretrieved: true`. An idea with no named source mechanism is not from
this view.""",
    },
    "corpus": {
        "label": "proposer-corpus",
        "view_name": "CORPUS-RESOURCE",
        "stem": "IDEATE-CORPUS",
        "focus_materials": """  - `{run_dir}/inbox/search-results.json`  (the live-retrieval bundle — what the field has done recently)
  - `{run_dir}/inbox/DIVERGENCE.bundle.json`  (its enablers section)
  - The run's real assets: the 1793-utterance five-round correction corpus (built, not yet trained on),
    the 2 x RTX A6000 registered execution target, the official autoPET V 5-round protocol with published
    evaluation script
  - `research_agent_teams/resources/` and `PLATFORM-FACTS.md` when present (never invent specs)""",
        "view_discipline": """You propose from ASSETS and ENABLERS: every idea must be anchored in a real enabling condition or
data asset (the corpus, the hardware, the protocol, a published result) and state why it is timely NOW.
Intersections of two enablers are strongest. An idea that was equally doable five years ago is probably
already done — say so and check. Ideas needing technology that does not exist yet are PARKED (record them
with `parked: true`), not proposed as if ready. This view also owns data-asset ideas: corpus-driven
supervision, calibration, and evaluation-resource designs.""",
    },
}
