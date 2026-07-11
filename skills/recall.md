---
name: recall
kind: machine-skill
stage: RECALL
reads: System D (PhD-Research-OS/) by reference
writes: recall_note (runs/<run>/evidence/RECALL/)
---

# /recall — machine-side, by-reference (the M⇐D seam, read side)

Targeted retrieval from System D **for the machine**, by reference only. Distinct from the DB-internal
`recall` skill (which lives in the DB repo and serves vault QUERY): this one runs from the machine side,
resolves a topic to `[[slug]] + content-sha + section` citations, and emits a **`recall_note`** artifact
into the run-store. It **never inlines System-D content** into the run-store (blueprint §5) — the
run-store holds pointers, not copied knowledge.

## Procedure (deterministic core = `tools/recall.py`)

1. Read System D `00-system/index.md`; collect the known slugs.
2. Match the topic to slugs by shared token (`recall.recall(query, vault_root=<DB>)`).
3. For each match, resolve `02-wiki/**/<slug>.md`, hash its content (the by-reference sha), record the
   first heading as the section.
4. Emit a `recall_note`: `{query, citations[{slug, sha256, section, supports}], confidence, vault_silent}`.
5. If System D is silent on the topic, set `vault_silent: true` and (optionally) a `closest` pointer —
   never fabricate a slug (evidence-contract clause 4).

## Rules

- **By reference, never inline.** The `recall_note` carries slug + sha + a short `supports` pointer.
  It MUST NOT contain the DB page body — the run-store never accumulates copied knowledge.
- **Never invent a slug.** Only cite slugs present in `00-system/index.md`.
- **Cite with a hash.** Every citation carries the page content-sha at recall time, so a later change to
  the DB page is detectable (the seam is tamper-evident on the read side too).
- The artifact is schema-validated (`recall_note.schema.json`) like every other run artifact.
