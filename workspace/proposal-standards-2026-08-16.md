# Proposal Standards for Systematic / Scoping Review Protocols — Verification Report

**Date:** 2026-08-16
**Purpose:** Verifies three claims (V1–V3) and distills four reference documents (D1–D4) for three medical-imaging systematic review proposals being drafted in parallel. Every claim carries its source URL. Prefer primary sources (registry sites, JBI manual, Cochrane Handbook, journal policies) throughout.

---

## V1 — PROSPERO scope: scoping reviews excluded; where to register; methodological reviews

**Verdict: VERIFIED (part 1) · CONDITIONAL (part 2 — "systematic methodological review")**

### V1.1 PROSPERO does not accept scoping reviews — VERIFIED

Primary evidence — PROSPERO's own live registration application (React bundle of the registry form, `static/js/main.2ca48f84.js`, retrieved 2026-08-16 from https://www.crd.york.ac.uk/PROSPERO/):

- The form hard-rejects scoping reviews with the validation message:
  > "PROSPERO does not currently accept scoping reviews"
- The cover-sheet help text "Do not register reviews that are out of scope" states:
  > "PROSPERO only accepts registrations of systematic reviews examining outcomes that are of direct relevance to human health and wellbeing"
  > **"PROSPERO does not register: ... Literature reviews that use only a systematic search and no other systematic review methods; Scoping reviews (these may be incorporated in future)"**
  > "If your review is out of scope there are other places where you can register or lodge your full protocol. This includes the Open Science Framework where registration is free of charge — https://osf.io/registries"
- The risk-of-bias section help text steers borderline cases away: "It is recommended that systematic reviews include assessment of risk of bias or study quality. Not doing so suggests that this might be a scoping review." and "Most systematic reviews will aim to carry out some form of synthesis. Not planning any synthesis suggests that this may be a scoping review."

Secondary confirmation from JBI itself (Peters et al. 2020, the JBI scoping review methodology paper):
> "Currently, scoping reviews are not able to be registered with the International Prospective Register of Systematic Reviews (PROSPERO). However, authors conducting a scoping review should consider publishing, registering, or making their protocol available via platforms such as Figshare, Open Science Framework, ResearchGate, Research Square, or similar so that it is freely available."
— Peters MDJ, Marnie C, Tricco AC, Pollock D, Munn Z, Alexander L, McInerney P, Godfrey CM, Khalil H. Updated methodological guidance for the conduct of scoping reviews. *JBI Evid Synth*. 2020;18(10):2119–2126. doi:10.11124/JBIES-20-00167. https://journals.lww.com/jbisrir/fulltext/2020/10000/Updated_methodological_guidance_for_the_conduct_of.4.aspx

2025 JBI editorial (protocol-rejection guidance) similarly directs scoping review protocols to OSF or Figshare and asks authors to supply the registration number/link at submission:
— "Protocols for systematic and scoping reviews: why is my protocol rejected?" *JBI Evidence Synthesis*, 2025, doi:10.11124/JBIES-25-00208. https://journals.lww.com/jbisrir/fulltext/9900/protocols_for_systematic_and_scoping_reviews__why.0.aspx (also mirrored at Ovid: https://www.ovid.com/jnls/jbisrir/fulltext/10.11124/jbies-25-00208)

**Conclusion:** scoping-review protocols go to OSF Registries (https://osf.io/registries), not PROSPERO.

### V1.2 Is a "systematic methodological review" acceptable for PROSPERO? — CONDITIONAL (effectively NO as a review type today)

Two constraints from the live form (same primary source as V1.1):

1. **Outcome criterion.** The current eligibility rule is outcome-based: reviews must examine "outcomes that are of direct relevance to human health and wellbeing". A methodology/audit-focused review (e.g., auditing reporting quality of imaging AI studies) has a methodological outcome, not a health outcome — it fails this criterion unless it can be framed around a health-relevant outcome.
2. **The review-type selector lists "Methodology" as disabled**, with the label: "Coming soon: Methodology — Examining the evidence on methodological aspects of systematic reviews, trials and other evaluations of health and social care." I.e., PROSPERO has no active methodological template; the form FAQ states that meanwhile "all users should select the intervention review form. New forms will be released in the future."

**Conclusion:** a systematic methodological review is **not currently registrable as such** on PROSPERO (type disabled, "Coming soon"); it can only enter through the standard intervention form and only if it satisfies the health-outcome criterion. Until the methodological template ships, the safe route for a methodology-audit review is OSF Registries, with an optional JBI Evidence Synthesis protocol publication (which does accept methodological/scoping protocol papers).

---

## V2 — AI/LLM use in screening and extraction: disclosure obligations and the "second reviewer" question

**Verdict: VERIFIED (disclosure is now mandatory under the 2025 joint position) · PARTIAL/NUANCED (AI as second reviewer — allowed only as a declared, validated assistant; cannot be a silent replacement)**

### V2.1 The authoritative 2025–2026 disclosure guidance

**Primary: the joint position statement of the four synthesis organisations (published 11 Nov 2025):**
Flemyng E, Noel-Storr A, Macura B, Gartlehner G, Thomas J, Meerpohl JJ, et al. Position statement on artificial intelligence (AI) use in evidence synthesis across Cochrane, the Campbell Collaboration, JBI and the Collaboration for Environmental Evidence 2025. *Environmental Evidence* 14; doi:10.1186/s13750-025-00374-5 (https://link.springer.com/article/10.1186/s13750-025-00374-5); simultaneously in *Cochrane Database Syst Rev* doi:10.1002/14651858.ED000178 (https://www.cochranelibrary.com/cdsr/doi/10.1002/14651858.ED000178/full), *Campbell Syst Rev* doi:10.1002/cl2.70074, and *JBI Evidence Synthesis* (https://journals.lww.com/jbisrir/fulltext/2025/11000/position_statement_on_artificial_intelligence__ai_.1.aspx).

What authors **must declare** (per the statement):
- AI use **whenever AI makes or suggests judgements**: eligibility/study-selection decisions, risk-of-bias appraisals, **extraction** of bibliographic/numerical/qualitative data, synthesis across studies, certainty-of-evidence (GRADE) assessments, and drafting of strength-of-evidence/implications text.
- Purely editorial use (spelling, grammar, structure) generally need not be listed (check journal policy).
- Report in Methods, Acknowledgements, or a dedicated disclosure section, including: **tool name + version + date; purpose and the review stages affected; justification with validation/piloting evidence; public availability of inputs (prompts), outputs, datasets, and code; financial/non-financial interests; limitations and biases with their impact.** Supplementary tables for extensive use.
- AI-use decisions belong in the **protocol** (statement includes a reporting template for protocols).
- Human oversight is mandatory: "Evidence synthesists are ultimately responsible for their evidence synthesis, including the decision to use artificial intelligence"; use "must be justified as methodologically sound and not undermining trustworthiness", aligned with the RAISE (Responsible use of AI in evidence SynthEsis) recommendations.

**Journal-level policy (COPE, adopted by most biomedical publishers):**
COPE Council. COPE position — Authorship and AI. 2024. doi:10.24318/cCVRZBms. https://publicationethics.org/cope-position-statements/ai-author
- AI tools **cannot be authors or peer reviewers** (cannot take responsibility, declare COI, or manage copyright).
- Authors must disclose AI use in the manuscript with a statement of the form: "During the preparation of this work the author(s) used [NAME TOOL / SERVICE] in order to [REASON]. After using this tool/service, the author(s) reviewed and edited the content as needed and take(s) full responsibility for the content of the publication."
- Reviewers must not upload manuscripts to AI tools and must not use AI to generate review reports.

**Reporting-guideline level (PRISMA family):**
- **PRISMA 2020, item 8** (selection process) requires specifying "how many reviewers screened each record and each report retrieved, whether they worked independently, and if applicable, details of automation tools used in the process" (https://resources.equator-network.org/reporting-guidelines/prisma/items/selection-process.html; Page MJ et al. *BMJ* 2021;372:n71, doi:10.1136/bmj.n71). The expanded checklist elaboration requires, for classifiers used "either to eliminate records or to **replace a single screener**": tool/version + reference, how it was used and trained, and "any internal or external validation performed to assess the risk of missed studies or incorrect classifications"; machine-prioritised screening must report software + screening rules; and machine-eliminated records must appear in the flow diagram as "Records marked as ineligible by automation tools".
- **PRISMA-trAIce (2025)** — Holst D, Moenck K, Koch J, Schmedemann O, Schüppstuhl T. Transparent Reporting of AI in Systematic Literature Reviews: Development of the PRISMA-trAIce Checklist. *JMIR AI* 2025;4:e80247. doi:10.2196/80247, PMID 41370833. https://ai.jmir.org/2025/1/e80247. A discipline-agnostic checklist extension of PRISMA 2020 covering AI used **as a tool** in the review (as opposed to PRISMA-AI, which addresses AI **as the subject of research**). Items span: AI tool identification, human–AI interaction, performance evaluation, limitations. Status: published as a **foundational proposal**, open consensus-building invited — not yet formally endorsed by the PRISMA Executive.
- **PRISMA 2026** (see D4): adds **item 8b**, requiring report of AI/ML tool name + version, training data, flagging thresholds, human-checking strategy (full vs. sample re-screen vs. only-AI-rejected items), and quantitative agreement rates; recommends fixing these parameters in the pre-registered protocol. **Caveat:** as of 2026-08-16 this is reported by CASRAI (https://casrai.org/news/prisma-2026-next-generation-systematic-reviews); the official prisma-statement.org site does not yet list PRISMA 2026 (homepage checked 2026-08-16 still presents PRISMA 2020 as current).

### V2.2 Is AI acceptable as the "second reviewer" in dual screening?

Current authoritative positions:
- **Cochrane Handbook v6.5 (2024), Chapter 4:** dual human screening remains the standard — "Ideally, screening of titles and abstracts to remove irrelevant reports should also be done in duplicate by two people working independently (although it is acceptable that this initial screening of titles and abstracts is undertaken by only one person). It is essential, however, that two people working independently are used to make a final determination as to whether each study considered possibly eligible after title/abstract screening meets the eligibility criteria based on the full text" (4.6.4). On automation (4.6.6.2): automation "can reduce the need for manual screening by at least 30% and possibly more than 90%, although sometimes at the cost of up to a 5% reduction in sensitivity"; the Cochrane RCT Classifier and Screen4Me workflow (used in >250 reviews, mean 53% screening workload reduction) are endorsed tools; but **automatic elimination of records via active learning "has not been recommended for use in Cochrane reviews … since more work is needed to develop and validate safe 'stopping rules'"**, and LLM-based screening had "no sufficiently large and valid evaluations" as of the writing (mid-2023). URL: https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04
- **Joint 2025 position statement:** notes single-reviewer screening in rapid reviews carries ~13% risk of falsely excluding a relevant study (Gartlehner et al. 2020) and that "using AI as a second 'reviewer' could help reduce this risk" — i.e., AI-as-second-screener is **contemplated as a risk-reduction measure, not as an equivalent to human review**, and only under the disclosure + validation obligations above.
- **PRISMA 2020 expanded checklist** (above) treats "replace a single screener" as a reportable configuration — permissible *if* the tool, training, and validation are disclosed.
- **COPE/journal policies** forbid AI as a *manuscript peer reviewer* — a different role from a screening assistant, but signals the norm: AI may assist, a human remains accountable.

**Practical bottom line for the proposals:** declare any AI-assisted screening/extraction per the joint statement template (tool, version, stage, prompts/datasets public, validation, human-verification strategy); dual independent human screening for full-text decisions remains the defensible default; AI-assisted title/abstract screening is acceptable if disclosed and validated (report agreement rates); state that AI did not replace human accountability.

---

## V3 — JBI scoping reviews: critical appraisal and evidence maps

**Verdict: VERIFIED (critical appraisal is NOT required — "generally not recommended"; may be included only when the review aim demands it)**

Primary source, JBI's own updated methodology (Peters et al., *JBI Evid Synth* 2020;18(10):2119–2126, doi:10.11124/JBIES-20-00167; URL in V1.1), verbatim:
> "Critical appraisal or risk of bias assessment is generally not recommended in scoping reviews because the aim is to map the available evidence rather than provide a synthesized and clinically meaningful answer to a question. For this reason, an assessment of methodological limitations or risk of bias of the evidence included within a scoping review is generally not performed (unless there is a specific requirement due to the nature of the scoping review aim)."

The current manual chapter (2024 edition) repeats this guidance:
— Peters MDJ, Godfrey C, McInerney P, Munn Z, Tricco AC, Khalil H. **Chapter 10: Scoping Reviews**. In: Aromataris E, Lockwood C, Porritt K, Pilla B, Jordan Z (eds). *JBI Manual for Evidence Synthesis*. JBI; 2024. doi:10.46658/JBIMES-24-09. https://jbi-global-wiki.refined.site/space/MANUAL/355862497/10.+Scoping+reviews (manual home: https://synthesismanual.jbi.global)

Also from the same 2020 paper: analysis in scoping reviews "should not involve anything more than basic descriptive analysis (ie, frequency counts of concepts, populations, or location of studies)… It is difficult to envisage a case where further, in-depth quantitative analysis is required in scoping reviews, such as performing a meta-analysis."

**Evidence maps within scoping reviews** — JBI's statement (same paper, verbatim):
> "Evidence gap maps share similarities to scoping reviews in terms of identifying a research question, conducting a systematic search, and providing descriptive analysis; however, evidence gap maps tend to limit the inclusion of evidence to systematic reviews and primary research studies, but may also include critical appraisal."

So: JBI treats the **evidence (gap) map as a related but distinct product** — a scoping review *may* present descriptive mapping of the evidence (tables, bubble/heat maps of concepts × populations × contexts, frequency counts) but if the product's aim is a formal gap map with critical appraisal and restricted source types, it is closer to an evidence map than a JBI scoping review. Practical rule: keep the scoping review descriptive; if appraisal is wanted, either justify it by the review aim (allowed by the "unless" clause) or reframe as an evidence gap map and say so explicitly.

---

## D1 — PRISMA-P 2015: the 17 checklist items

Source: Moher D, Shamseer L, Clarke M, Ghersi D, Liberati A, Petticrew M, Shekelle P, Stewart LA; PRISMA-P Group. *Syst Rev.* 2015;4:1. doi:10.1186/2046-4053-4-1. https://pmc.ncbi.nlm.nih.gov/articles/PMC4320440/ (BMJ companion: *BMJ* 2015;349:g7647, doi:10.1136/bmj.g7647). Official checklist: https://www.prisma-statement.org/Extensions/Protocols

**Administrative information**
1. **Title** — 1a: identify the report as a protocol of a systematic review; 1b: if an update of a previous review, identify as such.
2. **Registration** — if registered, name the registry (e.g., PROSPERO) and registration number.
3. **Authors** — 3a: contact details of all protocol authors + corresponding author's mailing address; 3b: author contributions and the review guarantor.
4. **Amendments** — if amending an earlier protocol, identify as such and list changes; otherwise state the plan for documenting future amendments.
5. **Support** — 5a: sources of financial/non-financial support; 5b: sponsor name; 5c: sponsor/funder's role in developing the protocol.

**Introduction**
6. **Rationale** — describe the rationale in the context of what is already known.
7. **Objectives** — explicit statement of the question(s) with reference to participants, interventions, comparators, outcomes (PICO).

**Methods**
8. **Eligibility criteria** — study characteristics (PICO, design, setting, time frame) and report characteristics (years, language, publication status).
9. **Information sources** — all intended sources (databases, registers, grey literature, author contact) with planned coverage dates.
10. **Search strategy** — draft strategy for at least one database, with limits, reproducible.
11. **Study records** — 11a: data-management mechanism; 11b: selection process (independent reviewers etc.); 11c: data collection process (piloting, duplicate extraction, obtaining missing data).
12. **Data items** — list and define all variables sought, plus data assumptions and simplifications.
13. **Outcomes and prioritization** — list and define all outcomes, prioritizing main vs. additional.
14. **Risk of bias in individual studies** — planned RoB assessment methods and how they inform synthesis.
15. **Data synthesis** — 15a: criteria for quantitative synthesis; 15b: summary measures and methods of combining data, consistency exploration (I², tau); 15c: additional analyses (sensitivity, subgroup, meta-regression); 15d: if no quantitative synthesis, the type of summary planned.
16. **Meta-bias(es)** — planned assessment of publication bias / selective reporting.
17. **Confidence in cumulative evidence** — how strength of the body of evidence will be assessed (e.g., GRADE).

---

## D2 — PROSPERO registration form: main sections/fields

Source: the live PROSPERO registration form (crd.york.ac.uk/PROSPERO), reconstructed from the form's own application schema (templates in `static/js/main.2ca48f84.js`, retrieved 2026-08-16). PROSPERO v2.0.x (2025), including the 2024 Living Systematic Review (LSR) template additions. ~40 fields:

1. **Review title** (English) + original-language title.
2. **Review timeline** — anticipated/actual start date; anticipated completion date.
3. **Stage of review at time of submission** (not yet started / started / completed).
4. **Named contact** — title, name, email, address, phone; organisational affiliation.
5. **Review team members** — all authors + ORCID (ORCID now required for record creation).
6. **Funding sources / sponsors**.
7. **Conflicts of interest** (per person).
8. **Collaborators** — other organisations contributing expertise without authorship.
9. **Review question** — explicit objective(s)/question(s).
10. **Condition or domain being studied**.
11. **Participants / population** (inclusion + exclusion).
12. **Intervention(s) / exposure(s)** (with PICO tags from the Cochrane ontology).
13. **Comparator(s) / control**.
14. **Context** — setting and other eligibility-relevant characteristics.
15. **Study designs to be included**.
16. **Other eligibility criteria** — date restrictions, language, publication status.
17. **Search strategy** — text of the strategy + database list (TemplateSearchDatabases) + MeSH terms.
18. **Search strategy PDF upload** and/or **URL to search strategy**.
19. **Types of study to be included** (also under designs).
20. **Main outcome(s)**.
21. **Additional outcomes**.
22. **Data extraction** — selection process (independent reviewers), coding/extraction procedure.
23. **Risk of bias (quality) assessment** — tool + number of assessors (RoB-2, ROBINS, QUADAS, PROBAST, Newcastle–Ottawa, Downs & Black etc.).
24. **Strategy for data synthesis** — quantitative (meta-analysis details) / qualitative (narrative) branches.
25. **Analysis of subgroups or subsets**.
26. **Certainty of the evidence** — planned certainty assessment (e.g., GRADE) — newer form section.
27. **Reporting bias** — planned assessment of meta-biases.
28. **Type of review** — standard vs. living systematic review (LSR); "Methodology" type currently disabled ("Coming soon").
29. **Living systematic review methods** (LSR only) — update frequency, stage-wise updating, analytical methods due to living mode, retirement triggers.
30. **Language** and **country/countries** of the review team.
31. **Other registration details** — e.g., Campbell/JBI registration numbers, data repositories (SRDR).
32. **Reference and/or URL for the published protocol** / **published protocol DOI**.
33. **Dissemination plans** / anticipated first publication.
34. **Keywords** (indexing).
35. **Details of any existing review of the same topic by the same authors** (update/redundancy check).
36. **Current review status per stage** — pilot / searching / screening / extraction / RoB / synthesis (Not started / Started / Completed tags).
37. **Any additional information**.
38. **Revision notes** — amendments are versioned; every version requires all-team approval before publication.
39. **Peer-review status** of the registration record (checking workflow).
40. **Submission guardrails** — English only; complete protocol required (no speculative registrations); scoping reviews rejected (see V1).

---

## D3 — OSF registration for scoping reviews: template fields

Sources: OSF Registries — https://osf.io/registries; template wiki — https://osf.io/zab38/wiki/home/; COS announcement (20 Apr 2023) — https://www.cos.io/blog/generalized-systematic-review-template-joins-osf-registries; field-by-field specification (R package `preregr`, `form_genSysRev_v1`) — https://preregr.opens.science/articles/form_genSysRev_v1.html; COS template guide — https://www.cos.io/blog/choosing-preregistration-template-guide-for-researchers; practical scoping-review walkthrough — https://musc.libguides.com/c.php?g=1362580&p=10063992

Two workable routes:
- **Route A — Generalized Systematic Review Registration (structured, recommended):** discipline- and review-type-agnostic (explicitly usable for scoping reviews and evidence maps), PRISMA 2020-aligned. Mark "scoping review" in the title and "N/A" for not-applicable sections (e.g., publication-bias analysis).
- **Route B — Open-Ended Registration:** paste a full protocol (written against PRISMA-ScR) into the narrative field; attach the protocol PDF (up to 5 supplements, auto-archived).

Main sections/fields of the Generalized template (from the field spec):
1. **Metadata (all OSF registrations):** title, description, contributors, category, licence, subjects, tags.
2. **Review methods:** type of review (meta-analysis / evidence map / scoping / qualitative), review stages, current stage at freezing, start/end dates, background, **primary research question(s)** (PICOS/PCC framing suggested), secondary research questions, expectations/hypotheses, dependent variables / outcomes.
3. **Search:** databases and interfaces searched, search strings/query syntax, supplementary search methods (grey literature, reference checking), search-date window.
4. **Screening:** screening procedure, number of screeners per round, independence, **reconciliation procedure for disagreements**, screening justification, screening data management and sharing (export formats BibTeX/RIS/CSV/XLSX, repository, embargos).
5. **Extraction:** entities to extract per source (variables, effect sizes, qualitative fragments, method descriptions, RoB indicators — mapped to PRISMA 2020 items 10a/10b/12), extractor training/reliability rounds, extractor instructions, extractor blinding, number of extractors and agreement tests, extraction reconciliation, extracted-data sharing (CSV/XLSX/RData, FAIR/open-data plans).
6. **Synthesis and quality assessment:** planned data transformations, synthesis methods, quality/appraisal approach (if any), publication-bias assessment (mark N/A for scoping reviews).
7. **Deviations:** deviations from the preregistered plan must be reported; updates upload as new time-stamped files in the registration; registrations can be public or embargoed.

No PROSPERO-style eligibility gate exists: OSF accepts all review types and disciplines; moderation is spam-only; registration is free, time-stamped, and immutable.

---

## D4 — 2025–2026 updates in the PRISMA family relevant to these reviews

1. **PRISMA 2026 (next-generation revision)** — reported by CASRAI as drafted 2024–2025, finalised end of 2025, to be published simultaneously in *BMJ*, *PLOS Medicine*, *Journal of Clinical Epidemiology*, and *Systematic Reviews*; coordinated with EQUATOR. Changes: three existing items extended; **four new items** — notably **item 8b (AI/ML in identification/screening/extraction: tool + version, training data, flagging thresholds, human-checking strategy, quantitative agreement rates)**, a living-review checklist, and a machine-readable (JSON) flow diagram regeneratable from structured records; backward-compatible with PRISMA 2020. https://casrai.org/news/prisma-2026-next-generation-systematic-reviews
   **Caveat:** not yet announced on prisma-statement.org as of 2026-08-16 (https://www.prisma-statement.org/ still presents PRISMA 2020 as the current guideline). Treat as imminent-but-pending; the proposals may cite PRISMA 2020 + declare AI use per item 8b's logic without citing PRISMA 2026 itself.
2. **PRISMA-trAIce (Dec 2025)** — checklist extension for transparent reporting of AI used *as a tool* in evidence synthesis (see V2.1 for citation). Status: published foundational proposal awaiting consensus endorsement.
3. **PRISMA-AI** — extension for systematic reviews *of AI interventions* (AI as subject), listed as under development on EQUATOR's registry of guidelines under development for systematic reviews (https://www.equator-network.org/library/reporting-guidelines-under-development/reporting-guidelines-under-development-for-systematic-reviews/). Not for AI-as-tool disclosure.
4. **Joint position statement on AI in evidence synthesis (11 Nov 2025)** — Cochrane + Campbell + JBI + CEE (see V2.1): mandatory disclosure of AI that makes/suggests judgements; human oversight and ultimate human responsibility; aligned with RAISE.
5. **COPE position — Authorship and AI (2024, current in 2025–2026 policies)** — see V2.1.
6. **PRISMA-ScR** — unchanged, still the 2018 statement: Tricco AC, Lillie E, Zarin W, et al. *Ann Intern Med.* 2018;169(7):467–473. doi:10.7326/M18-0850. https://www.prisma-statement.org/Extensions/ScopingReviews
7. **PRISMA-P** — unchanged, still the 2015 statement (see D1). No 2025–2026 protocol checklist update exists yet.
8. **PROSPERO form updates (2024–2025)** — new Living Systematic Review template; ORCID required for all record creators; record versioning with all-team approval; review-type selector now includes a disabled "Methodology — Coming soon" option (see V1.2); scoping reviews still rejected (see V1.1).

---

## One-line replacement sentences (LaTeX-ready, drop into Methods)

- **V1:** "The protocol was prospectively registered on the Open Science Framework (OSF Registries) because PROSPERO does not currently accept registrations of scoping reviews, and restricts registrations to systematic reviews examining outcomes of direct relevance to human health and wellbeing."
- **V2:** "Any use of AI/LLM tools in screening or data extraction is declared in accordance with the 2025 joint Cochrane–Campbell–JBI–CEE position statement, including the tool's name and version, the review stages affected, and the human verification and validation strategy; all inclusion decisions were confirmed by independent human reviewers, who retain full responsibility for the synthesis."
- **V3:** "In line with current JBI guidance for scoping reviews, critical appraisal (risk of bias assessment) of included sources was not undertaken, because the aim of the review is to map the available evidence rather than to answer a clinically meaningful question; results are presented as descriptive frequency mapping following the JBI scoping review methodology."
