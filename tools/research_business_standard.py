"""Inject the shared scientific-quality contract into every operated worker.

Mode prompts own their exact JSON/bundle shape. This shared block owns the
quality of the reasoning inside that shape, so a long compliance prompt cannot
crowd out the research job the worker was hired to do.
"""
from __future__ import annotations

from typing import Optional


MARKER = "BUSINESS QUALITY CONTRACT (shared, stage-specific)"

_COMMON = """
- Optimize for the decision or scientific product a senior researcher needs; process narration,
  safety boilerplate, and schema commentary are not substitutes for analysis.
- Bind important judgments to concrete input evidence. Separate observed fact, inference, and
  proposal. Surface the strongest plausible alternative explanation, not only supporting evidence.
- Produce the complete bundle shape requested above, but spend detail on the scientific content.
""".strip()

_STAGE = {
    "DISCOVER": """
- Use a decomposed search/reading question, grade source relevance and evidential strength, and seek
  disconfirming as well as supporting evidence. Explain coverage gaps and what would change the view.
- End with a usable bottom line: what the evidence changes for this project, the main uncertainty,
  and the next highest-value source or measurement to obtain.
""",
    "IDEATE": """
- Every serious idea needs a precise research question, a mechanism or causal chain, and a stated
  delta from prior art with novelty uncertainty made explicit.
- Make the idea investable: give a minimum falsification experiment, baselines/controls, success and
  failure thresholds, kill criteria, data/resource feasibility, main risks, and execution order.
""",
    "DESIGN": """
- Define the estimand or target claim, hypothesis, studied/controlled/frozen variables, matched
  baselines and controls, data/split protocol, metrics with direction and unit, and statistical plan.
- Include power or uncertainty logic, success/failure thresholds, kill criteria, expected failure
  analysis, and exact next run commands. A matrix without a decision rule is not a finished design.
""",
    "EXECUTE": """
- Deliver runnable, inspectable scripts/configs with exact dependencies, inputs, outputs, seeds,
  smoke checks, expected artifacts, and recovery steps. Preserve condition parity.
- Distinguish clearly between scripts prepared, smoke-tested, submitted, and actually completed.
  Report useful execution blockers and the next exact command, not generic status prose.
""",
    "ANALYZE": """
- Interpret effect sizes against matched baselines with uncertainty, metric direction/units, and
  multiple-comparison discipline. Include per-case or subgroup failures where the domain requires it.
- Test alternative explanations, identify where the result fails, and state the narrowest claim the
  evidence supports plus the next experiment that would most change confidence.
""",
    "VERIFY": """
- Review from independent methodology, domain, and adversarial lenses. State the strongest rejection argument,
  distinguish fatal blockers from optional polish, and tie every required fix to evidence.
- Convert criticism into a prioritized repair plan and a clear claim/venue boundary; do not merely
  average reviewer scores or repeat their prose.
""",
    "REPORT": """
- The primary product is human-readable Markdown: bottom line first, then decisive evidence,
  disagreements, uncertainty, decision implication, and concrete next actions.
- JSON paths and audit metadata belong in a short technical appendix. The report must stand alone for
  a researcher who has not read the machine artifacts.
""",
}


def stage_quality_block(stage: str) -> str:
    stage_upper = str(stage or "").upper()
    stage_text = _STAGE.get(stage_upper, _STAGE["REPORT"]).strip()
    return f"\n\n---\n{MARKER}\n{_COMMON}\n{stage_text}\n"


def decorate_worker_quality(worker: Optional[dict], stage: str) -> Optional[dict]:
    """Append the business contract to a single worker or every child in a panel."""
    if not worker:
        return worker
    if "workers" in worker:
        for child in worker.get("workers") or []:
            decorate_worker_quality(child, stage)
        return worker
    prompt = worker.get("prompt")
    if not isinstance(prompt, str) or MARKER in prompt:
        return worker
    worker["prompt"] = prompt.rstrip() + stage_quality_block(stage)
    return worker


__all__ = ["MARKER", "decorate_worker_quality", "stage_quality_block"]
