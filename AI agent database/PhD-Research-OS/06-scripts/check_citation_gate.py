"""
check_citation_gate.py — Standalone check for the citation gate on result pages.

Runs only the CITATION_GATE check from lint_vault.py. Useful as a fast
pre-commit hook on PRs that touch wiki/results/.

Exit code: 1 if any result page has an inconsistent `can-cite-thesis` flag.
"""
from __future__ import annotations
import sys
from pathlib import Path

try:
    import frontmatter  # type: ignore
except ImportError:
    print("ERROR: install python-frontmatter: pip install python-frontmatter", file=sys.stderr)
    sys.exit(2)

VAULT_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = VAULT_ROOT / "02-wiki" / "results"

META_TYPES = {"readme", "index", "schema", "registry", "log", "hot", "routing", "manifest", "plan", "view"}


def _gate_requires_reproducibility() -> bool:
    """Reproducibility folds into the gate only when reproducibility_level: full was set
    at bootstrap (see 00-system/AGENTS.md §2). No yaml dependency."""
    intake = VAULT_ROOT / "bootstrap-intake.yml"
    if not intake.exists():
        return False
    try:
        for line in intake.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("reproducibility_level:"):
                return s.split(":", 1)[1].strip().strip('"').strip("'") == "full"
    except OSError:
        return False
    return False


REQUIRE_REPRO = _gate_requires_reproducibility()


def main() -> int:
    if not RESULTS_DIR.exists():
        print(f"No {RESULTS_DIR} found — vault not yet bootstrapped.")
        return 0

    errors: list[str] = []
    for path in sorted(RESULTS_DIR.glob("*.md")):
        try:
            meta = dict(frontmatter.loads(path.read_text(encoding="utf-8-sig")).metadata)
        except Exception as e:
            errors.append(f"{path.name}: parse error ({e})")
            continue
        t = meta.get("type")
        if t in META_TYPES:
            continue
        if t != "result":
            # A file in results/ that is not type==result silently bypasses the gate. Flag it.
            errors.append(
                f"{path.name}: lives in results/ but type='{t}' != 'result' — the citation gate "
                f"only governs type==result; fix the type so the gate applies."
            )
            continue
        rs = meta.get("result-status")
        leak = meta.get("leakage-audit")
        fair = meta.get("fairness-audit")
        repro = meta.get("reproducibility-audit")
        declared = meta.get("can-cite-thesis")
        derived = (rs == "frozen") and (leak == "pass") and (fair == "pass")
        if REQUIRE_REPRO:
            derived = derived and (repro == "pass")
        if declared is None:
            errors.append(f"{path.name}: missing can-cite-thesis")
        elif bool(declared) != bool(derived):
            repro_note = f", reproducibility={repro}" if REQUIRE_REPRO else ""
            errors.append(
                f"{path.name}: can-cite-thesis={declared} but derived={derived} "
                f"(result-status={rs}, leakage={leak}, fairness={fair}{repro_note})"
            )

    if errors:
        print(f"\n=== Citation gate violations ({len(errors)}) ===\n")
        for e in errors:
            print(f"  {e}")
        print("\nFix: change the underlying audit fields, NOT the derived flag.\n")
        return 1
    print("Citation gate: all result pages consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
