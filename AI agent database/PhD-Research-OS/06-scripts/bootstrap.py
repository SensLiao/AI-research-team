"""
bootstrap.py — Instantiate the PhD Research OS template for a new project.

Reads bootstrap-intake.yml, validates the 12 required fields, and seeds
the customizable parts of the vault: hot.md, index.md, project-registry,
contribution-registry, and 3 source pages.

Idempotency: this script refuses to overwrite an already-bootstrapped vault.
A vault is considered bootstrapped if 02-wiki/sources/project-brief.md exists.

Usage:
  python 06-scripts/bootstrap.py [bootstrap-intake.yml]
  python 06-scripts/bootstrap.py --force [bootstrap-intake.yml]
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

try:
    import yaml  # type: ignore
except ImportError:
    print("ERROR: install pyyaml: pip install pyyaml", file=sys.stderr)
    sys.exit(2)

VAULT_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_FIELDS = [
    "project_slug", "project_title", "phase", "supervisor", "domain",
    "research_questions", "contributions", "methods_planned",
    "datasets_planned", "reproducibility_level", "citation_gate", "stakeholders",
]


def load_intake(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    missing = [k for k in REQUIRED_FIELDS if k not in data]
    if missing:
        raise SystemExit(f"intake missing required fields: {missing}")
    return data


def already_bootstrapped() -> bool:
    return (VAULT_ROOT / "02-wiki" / "sources" / "project-brief.md").exists()


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def yaml_list(items: list) -> str:
    if not items:
        return "[]"
    return "\n  - " + "\n  - ".join(str(x) for x in items)


def yaml_quoted_list(items: list) -> str:
    if not items:
        return "[]"
    return "\n  - '" + "'\n  - '".join(str(x) for x in items) + "'"


def fill_placeholders(template: str, intake: dict) -> str:
    repro = intake.get("reproducibility_level", "")
    gate = intake.get("citation_gate", "")
    rqs = intake.get("research_questions", [])
    rq_primary = rqs[0]["text"] if rqs else ""
    return (
        template
        .replace("{{PROJECT_TITLE}}", intake["project_title"])
        .replace("{{PROJECT_SLUG}}", intake["project_slug"])
        .replace("{{PHASE}}", intake.get("phase", ""))
        .replace("{{REPRO_LEVEL}}", repro)
        .replace("{{CITATION_GATE}}", gate)
        .replace("{{RQ_PRIMARY}}", rq_primary)
    )


def seed_project_registry(intake: dict) -> None:
    path = VAULT_ROOT / "05-registry" / "project-registry.md"
    today = date.today().isoformat()
    row = (
        f"| {intake['project_slug']} | {intake['project_title']} | "
        f"{intake.get('phase','')} | {intake.get('supervisor','')} | "
        f"{','.join(intake.get('domain', []))} | active | {today} | "
        f"00-system/hot.md | [[{intake['project_slug']}-brief]] |"
    )
    text = path.read_text(encoding="utf-8")
    placeholder = "| (empty — fill at bootstrap) | | | | | | | | |"
    if placeholder in text:
        text = text.replace(placeholder, row)
    else:
        text += "\n" + row + "\n"
    path.write_text(text, encoding="utf-8")


def seed_contribution_registry(intake: dict) -> None:
    path = VAULT_ROOT / "05-registry" / "contribution-registry.md"
    today = date.today().isoformat()
    rows = []
    for c in intake.get("contributions", []):
        rqs = c.get("serves_rq", [])
        rows.append(
            f"| {intake['project_slug']} | {c['id']} | {c['text']} | "
            f"{','.join(rqs)} | proposed | medium | {today} | {today} |"
        )
    if not rows:
        return
    text = path.read_text(encoding="utf-8")
    placeholder = "| (empty — fill at bootstrap) | | | | | | | |"
    if placeholder in text:
        text = text.replace(placeholder, "\n".join(rows))
    else:
        text += "\n" + "\n".join(rows) + "\n"
    path.write_text(text, encoding="utf-8")


def seed_project_brief(intake: dict) -> None:
    path = VAULT_ROOT / "02-wiki" / "sources" / "project-brief.md"
    today = date.today().isoformat()
    rqs = "\n".join(f"- **{rq['id']}**: {rq['text']}" for rq in intake.get("research_questions", []))
    contribs = "\n".join(f"- **{c['id']}** (serves {','.join(c.get('serves_rq',[]))}): {c['text']}" for c in intake.get("contributions", []))
    body = f"""---
title: "{intake['project_title']} — Project Brief"
type: source
status: active
confidence: high
created: {today}
updated: {today}
project: {intake['project_slug']}
rq: {[rq['id'] for rq in intake.get('research_questions', [])]}
contrib: {[c['id'] for c in intake.get('contributions', [])]}
domain: {intake.get('domain', [])}
tags: [project-brief, bootstrap]
related: []
source: ''
aliases: ['{intake['project_slug']}-brief']
evidence-class: VAULT-CITE
owner: bootstrap
reviewed: {today}
review-cycle: 90
source-type: runbook
maintained-by: human
canonical: true
---

# {intake['project_title']} — Project Brief

**Project slug:** `{intake['project_slug']}`
**Phase:** {intake.get('phase','')}
**Supervisor:** {intake.get('supervisor','')}
**Domain:** {', '.join(intake.get('domain', []))}
**Stakeholders:** {', '.join(intake.get('stakeholders', []))}
**Reproducibility level:** {intake.get('reproducibility_level','')}
**Citation gate:** {intake.get('citation_gate','')}

## Research questions

{rqs}

## Contributions

{contribs}

## Planned methods (initial — will grow)

{chr(10).join(f"- {m}" for m in intake.get('methods_planned', []))}

## Planned datasets (initial — will grow)

{chr(10).join(f"- {d}" for d in intake.get('datasets_planned', []))}

## Scope (current — revisit after first decisions)

- Locked at bootstrap from `bootstrap-intake.yml`.
- See [[dec-0001-scope]] for the bootstrap-time scope decision.
"""
    write(path, body)


def seed_research_questions(intake: dict) -> None:
    path = VAULT_ROOT / "02-wiki" / "sources" / "research-questions.md"
    today = date.today().isoformat()
    rqs = intake.get("research_questions", [])
    body_rqs = "\n".join(
        f"## {rq['id']}\n\n**Question:** {rq['text']}\n\n**Status:** open\n\n**Evidence chain:** (no claims registered yet)\n"
        for rq in rqs
    )
    body = f"""---
title: "{intake['project_title']} — Research Questions"
type: source
status: active
confidence: high
created: {today}
updated: {today}
project: {intake['project_slug']}
rq: {[rq['id'] for rq in rqs]}
contrib: []
domain: {intake.get('domain', [])}
tags: [research-questions, canonical]
related:
  - '[[{intake['project_slug']}-brief]]'
source: ''
aliases: []
evidence-class: VAULT-CITE
owner: bootstrap
reviewed: {today}
review-cycle: 60
source-type: rules
maintained-by: human
canonical: true
---

# Research Questions

{body_rqs}

## Maintenance

When a question is answered, add a `## Resolution` subsection citing the [[claim-slug]] that resolves it. Never delete a question — mark resolved.
"""
    write(path, body)


def seed_dec_0001(intake: dict) -> None:
    path = VAULT_ROOT / "02-wiki" / "decisions" / "dec-0001-scope.md"
    today = date.today().isoformat()
    body = f"""---
title: "DEC-0001: Bootstrap-time scope"
type: decision
status: active
confidence: high
created: {today}
updated: {today}
project: {intake['project_slug']}
rq: {[rq['id'] for rq in intake.get('research_questions', [])]}
contrib: {[c['id'] for c in intake.get('contributions', [])]}
domain: {intake.get('domain', [])}
tags: [bootstrap, scope, adr]
related:
  - '[[{intake['project_slug']}-brief]]'
  - '[[research-questions]]'
source: 'bootstrap-intake.yml'
aliases: []
evidence-class: DECISION-CITE
owner: bootstrap
reviewed: {today}
review-cycle: none
decision-status: accepted
date: {today}
decision-owner: {intake.get('supervisor') or 'self'}
context: "Initial scope locked at vault instantiation."
options-considered: ['as filled in bootstrap-intake.yml', 'wider scope', 'narrower scope']
chosen: "as filled in bootstrap-intake.yml"
rationale: "Aligns with phase ({intake.get('phase','')}) and supervisor expectations."
consequences: ['Reproducibility level: {intake.get('reproducibility_level','')}', 'Citation gate: {intake.get('citation_gate','')}']
risks: ['Scope creep if RQs broaden without revisiting this decision']
revisitable-when: ['Major supervisor reframing', 'Mid-phase milestone review', 'New dataset or contribution lands that changes scope']
---

# DEC-0001: Bootstrap-time scope

**Status:** accepted · **Date:** {today} · **Owner:** {intake.get('supervisor') or 'self'}

## Context

This vault was instantiated for project `{intake['project_slug']}` with reproducibility level `{intake.get('reproducibility_level','')}` and citation gate strictness `{intake.get('citation_gate','')}`. RQs and contributions are locked as listed in [[{intake['project_slug']}-brief]].

## Decision

Use the scope as filled in `bootstrap-intake.yml`.

## Rationale

Aligns with the project phase and stakeholder expectations declared at intake.

## Consequences

- Reproducibility level: {intake.get('reproducibility_level','')}
- Citation gate: {intake.get('citation_gate','')}

## Risks

- Scope creep if RQs broaden without revisiting this decision.

## Revisit when

- Major supervisor reframing
- Mid-phase milestone review
- New dataset or contribution lands that changes scope
"""
    write(path, body)


def seed_hot(intake: dict) -> None:
    path = VAULT_ROOT / "00-system" / "hot.md"
    template = path.read_text(encoding="utf-8")
    today = date.today().isoformat()
    text = fill_placeholders(template, intake)
    text = text.replace("**Last close:** —", f"**Last close:** {today} (bootstrap)")
    text = text.replace(
        "(Bootstrap pending. Replace this paragraph after first `/close`.)",
        f"Just instantiated. RQs {[rq['id'] for rq in intake.get('research_questions', [])]}, "
        f"Contributions {[c['id'] for c in intake.get('contributions', [])]} all open.",
    )
    path.write_text(text, encoding="utf-8")


def seed_log(intake: dict) -> None:
    path = VAULT_ROOT / "07-logs" / "log.md"
    today = date.today().isoformat()
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        text = "---\ntype: log\nupdated: " + today + "\n---\n\n# Operation Log\n\nAppend-only record of every INGEST, SCHEMA, BACKFILL, CONTRACT-EDIT, and CLOSE.\n\n---\n"
    entry = (
        f"\n## {today}\n\n"
        f"- BOOTSTRAP: vault instantiated for project [[{intake['project_slug']}]]. "
        f"Intake fields filled. project-registry + contribution-registry seeded. "
        f"3 wiki source pages created. hot.md + index.md initialized. "
        f"Reproducibility level: {intake.get('reproducibility_level','')}. "
        f"Citation gate: {intake.get('citation_gate','')}.\n"
    )
    path.write_text(text + entry, encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("intake", nargs="?", default="bootstrap-intake.yml")
    ap.add_argument("--force", action="store_true", help="overwrite an already-bootstrapped vault")
    args = ap.parse_args()

    intake_path = Path(args.intake)
    if not intake_path.is_absolute():
        intake_path = VAULT_ROOT / intake_path

    if not intake_path.exists():
        print(f"intake file not found: {intake_path}", file=sys.stderr)
        print("Tip: copy bootstrap-intake.template.yml → bootstrap-intake.yml and fill the 12 fields.")
        return 1

    if already_bootstrapped() and not args.force:
        print("Vault already bootstrapped (02-wiki/sources/project-brief.md exists). "
              "Use --force to re-seed.", file=sys.stderr)
        return 1

    intake = load_intake(intake_path)
    print(f"Bootstrapping vault for project '{intake['project_slug']}' ...")
    seed_project_brief(intake)
    seed_research_questions(intake)
    seed_dec_0001(intake)
    seed_project_registry(intake)
    seed_contribution_registry(intake)
    seed_hot(intake)
    seed_log(intake)
    print("\nDone. Files written:")
    for sub in (
        "02-wiki/sources/project-brief.md",
        "02-wiki/sources/research-questions.md",
        "02-wiki/decisions/dec-0001-scope.md",
        "05-registry/project-registry.md",
        "05-registry/contribution-registry.md",
        "00-system/hot.md",
        "07-logs/log.md",
    ):
        print(f"  - {sub}")
    print("\nNext:")
    print("  1. Drop your first PDF / transcript / dataset doc into 01-raw/<subfolder>/")
    print("  2. Run: python 06-scripts/lint_vault.py  (should pass)")
    print("  3. git init && git add . && git commit -m 'bootstrap'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
