"""Build SHA-bound document-admission candidates from a reviewed Markdown staging tree.

This helper does not write the vault and does not authorize admission.  It only converts
frontmatter-bearing final Markdown into the strict untrusted candidate format consumed by
``promote_gate --document-batch``.  The director-command gate still performs path, SHA,
project, schema and page-contract verification before any vault write.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict

import yaml

from research_agent_teams.tools.validate_artifact import validate_payload


TYPE_METADATA = {
    "paper": ("authors", "year", "venue", "doi", "url", "reading-status", "relevance",
              "paper-type", "read-purpose", "reading-objective", "key-claims", "serves-claim"),
    "synthesis": ("covers", "for-chapter", "claim-chain", "required-evidence-status"),
    "idea": ("idea-status", "rationale", "evidence-for", "evidence-against", "blockers", "decided-by"),
    "source": ("source-type", "maintained-by", "canonical"),
    "method": ("category", "first-seen", "applied-in", "mathematical-form"),
    "model": ("family", "native-dim", "params", "prompt-modes", "training-data", "license",
              "official-repo", "paper"),
    "dataset": ("size", "modality", "classes", "split-policy", "preprocessing", "source-url",
                "license", "local-path", "version", "data-hash"),
    "protocol": ("protocol-type", "protocol-version", "applies-to", "superseded-by", "rationale-doc"),
    "experiment": ("experiment-id", "model", "dataset", "protocol", "serves-rq", "serves-contrib",
                   "expected-outputs", "stop-conditions", "runs", "result-pages"),
}


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _frontmatter(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError(f"missing frontmatter: {path}")
    try:
        end = next(i for i, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError(f"unterminated frontmatter: {path}") from exc
    data = yaml.safe_load("\n".join(lines[1:end]))
    if not isinstance(data, dict):
        raise ValueError(f"frontmatter is not a mapping: {path}")
    return data


def build_candidate(path: Path, *, workspace: Path, admission_id: str, status: str) -> dict:
    fm = _frontmatter(path)
    vault_type = str(fm.get("type", ""))
    if vault_type not in TYPE_METADATA:
        raise ValueError(f"unsupported type {vault_type!r}: {path}")
    try:
        source_rel = path.resolve().relative_to(workspace.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError(f"source escapes workspace: {path}") from exc
    metadata = {key: fm[key] for key in TYPE_METADATA[vault_type] if key in fm}
    candidate = {
        "admission_id": admission_id,
        "slug": path.stem,
        "vault_type": vault_type,
        "project": str(fm["project"]),
        "title": str(fm["title"]),
        "source_ref": {"path": source_rel, "sha256": _sha(path)},
        "status": status,
        "confidence": str(fm.get("confidence", "unverified")),
        "evidence_class": str(fm.get("evidence-class", "ASSUMPTION")),
        "metadata": metadata,
    }
    for key in ("rq", "contrib", "domain", "tags", "related", "aliases"):
        if key in fm:
            candidate[key] = fm[key]
    errors = validate_payload("document_promotion_candidate", candidate)
    if errors:
        raise ValueError(f"candidate schema failed for {path}: {'; '.join(errors)}")
    return candidate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-root", default=".")
    parser.add_argument("--staging-root", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--admission-id", required=True)
    parser.add_argument("--status", choices=("draft", "active", "parked", "deprecated"), default="active")
    parser.add_argument("--lifecycle-manifest", help="optional JSON mapping target_slug to redirects/supersessions")
    args = parser.parse_args()

    workspace = Path(args.workspace_root).resolve()
    staging = (workspace / args.staging_root).resolve()
    output = (workspace / args.output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    existing = sorted(output.glob("*.document-promotion-candidate.json"))
    if existing:
        raise SystemExit(f"output directory already contains {len(existing)} candidate files: {output}")

    lifecycle: Dict[str, Any] = {}
    if args.lifecycle_manifest:
        lifecycle_path = (workspace / args.lifecycle_manifest).resolve()
        lifecycle = json.loads(lifecycle_path.read_text(encoding="utf-8"))
        if not isinstance(lifecycle, dict):
            raise SystemExit("lifecycle manifest must be an object keyed by target slug")

    count = 0
    for path in sorted(staging.rglob("*.md")):
        candidate = build_candidate(
            path, workspace=workspace, admission_id=args.admission_id, status=args.status
        )
        policy = lifecycle.get(candidate["slug"], {})
        if policy:
            if not isinstance(policy, dict):
                raise SystemExit(f"lifecycle entry for {candidate['slug']} must be an object")
            for key in ("canonical_redirects", "supersede_pages"):
                if key in policy:
                    candidate[key] = policy[key]
            errors = validate_payload("document_promotion_candidate", candidate)
            if errors:
                raise SystemExit(
                    f"candidate schema failed after lifecycle policy for {candidate['slug']}: "
                    + "; ".join(errors)
                )
        target = output / f"{candidate['slug']}.document-promotion-candidate.json"
        target.write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        count += 1

    print(json.dumps({"admission_id": args.admission_id, "candidates": count, "output": str(output)},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
