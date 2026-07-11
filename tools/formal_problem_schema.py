"""Deterministic formal-problem classifier for the UPSTREAM mathematical-formalizer agent.

This module turns a set of domain-NEUTRAL mechanism primitives into a single
``formal_form`` class, and assembles a typed ``problem_abstraction`` payload around it.
It is the typed counterpart of the (string-only) ``cross_domain_query.abstract_problem()``:
that function strips a problem's domain nouns to a mechanism PHRASE; this module names the
mechanism PRIMITIVES + the formal CLASS as a structured artifact.

Honest scope: this module decides nothing about novelty, feasibility, or solutions. It only
NAMES the mathematical class a problem belongs to from its mechanism primitives, via a fixed,
documented rule table. The classification is purely structural (priority-ordered first match),
so the same primitive set always yields the same form (no network, no clock, no randomness).

Domain-general by construction: the primitive vocabulary and the rule table are field-agnostic
(thin_structure / graph_connectivity / energy_minimization / …) — they hold for vision, NLP, RL,
graphs, control, etc. No single research domain is hardcoded.

----------------------------------------------------------------------------------------------
formal_form RULE TABLE (priority-ordered; FIRST matching group wins; documented + deterministic)
----------------------------------------------------------------------------------------------
  Priority  formal_form     Triggering primitives (form is chosen if ANY of these is present)
  1         graph           graph_connectivity, topology_preservation
  2         dynamical       dynamical_stability, long_range_dependency
  3         variational     energy_minimization, boundary_uncertainty
  4         manifold        anisotropic_geometry, multi_scale_structure, thin_structure
  5         optimization    constraint_satisfaction
  6         statistical     class_imbalance, noise_robustness, partial_observability
  7         none            (empty primitive set, OR no known primitive present)

Priority order is what resolves a primitive set that triggers several forms: the lowest-numbered
group that matches wins (e.g. {topology_preservation, class_imbalance} -> graph, because graph is
priority 1 and statistical is priority 6). Every formal_form branch is reachable from at least one
primitive (or, for ``none``, the empty/unknown set).

Public API:
    KNOWN_PRIMITIVES   -> frozenset[str]   (the closed primitive vocabulary)
    FORMAL_FORMS       -> tuple[str, ...]  (the closed formal_form enum, including "none")
    classify_form(mechanism_primitives) -> str
    build_problem_abstraction(problem, mechanism_primitives, ...) -> dict
"""
from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

from research_agent_teams.tools.cross_domain_query import abstract_problem

# ---------------------------------------------------------------------------- closed vocabularies

# The closed mechanism-primitive vocabulary (MUST match problem_abstraction.schema.json
# mechanism_primitives.items.enum). Domain-neutral; field-agnostic.
KNOWN_PRIMITIVES: frozenset = frozenset({
    "thin_structure",
    "topology_preservation",
    "boundary_uncertainty",
    "anisotropic_geometry",
    "long_range_dependency",
    "class_imbalance",
    "partial_observability",
    "noise_robustness",
    "constraint_satisfaction",
    "multi_scale_structure",
    "graph_connectivity",
    "energy_minimization",
    "dynamical_stability",
})

# The closed formal_form vocabulary (MUST match problem_abstraction.schema.json formal_form.enum).
FORMAL_FORMS: Tuple[str, ...] = (
    "graph",
    "manifold",
    "variational",
    "dynamical",
    "statistical",
    "optimization",
    "none",
)

# Priority-ordered rule table: (formal_form, trigger primitives). FIRST group with any matching
# primitive wins. Ordered most-structural -> most-statistical so a structural mechanism (a graph /
# a dynamical system) is named before a merely statistical descriptor (imbalance / noise). Tuple of
# tuples = immutable; iteration order IS the priority. ``none`` is the documented default below.
_FORM_RULES: Tuple[Tuple[str, frozenset], ...] = (
    ("graph", frozenset({"graph_connectivity", "topology_preservation"})),
    ("dynamical", frozenset({"dynamical_stability", "long_range_dependency"})),
    ("variational", frozenset({"energy_minimization", "boundary_uncertainty"})),
    ("manifold", frozenset({"anisotropic_geometry", "multi_scale_structure", "thin_structure"})),
    ("optimization", frozenset({"constraint_satisfaction"})),
    ("statistical", frozenset({"class_imbalance", "noise_robustness", "partial_observability"})),
)


def classify_form(mechanism_primitives: Sequence[str]) -> str:
    """Map a set of mechanism primitives to a single ``formal_form`` enum value.

    Deterministic and pure: walks the documented priority rule table (see module docstring)
    and returns the FIRST formal_form whose trigger set intersects the given primitives. An
    empty list, or a list containing only primitives outside :data:`KNOWN_PRIMITIVES`, yields
    ``"none"``. Unknown primitives are ignored (they never match a rule); they do not raise,
    so a caller cannot crash classification by passing a stray token — but note that
    :func:`build_problem_abstraction` DOES reject unknown primitives at assembly time, because
    the schema enum forbids them in the persisted artifact.

    Args:
        mechanism_primitives: an ordered sequence of primitive name strings (any iterable of
            str). Order does not affect the result — priority is fixed by the rule table.

    Returns:
        One of :data:`FORMAL_FORMS`. ``"none"`` when no known primitive maps to a form.
    """
    present = set(mechanism_primitives)
    for form, triggers in _FORM_RULES:
        if present & triggers:
            return form
    return "none"


def build_problem_abstraction(
    problem: str,
    mechanism_primitives: Sequence[str],
    *,
    problem_id: str,
    failure_modes: Optional[Sequence[str]] = None,
    constraints: Optional[Sequence[str]] = None,
    success_metrics: Optional[Sequence[str]] = None,
    abstraction_confidence: float = 0.5,
    notes: Optional[str] = None,
) -> dict:
    """Assemble a ``problem_abstraction`` payload from a problem + its mechanism primitives.

    The original ``problem`` string is recorded verbatim as ``domain_surface`` (the surface,
    pre-abstraction phrasing). The mechanism-level phrasing of that surface is produced by REUSING
    :func:`cross_domain_query.abstract_problem` (this module never reimplements that abstraction);
    when ``notes`` is not supplied, the derived mechanism phrase is recorded in ``notes`` so the
    surface->mechanism reduction is captured in the artifact. ``formal_form`` is computed from the
    primitives via :func:`classify_form`.

    The result conforms to problem_abstraction.schema.json (required fields populated; optional
    ``notes`` included). Pure and deterministic: no network, no clock, no randomness.

    Args:
        problem: the concrete, domain-specific problem statement (becomes ``domain_surface``).
        mechanism_primitives: the domain-neutral primitives describing the problem's mechanisms.
            Must all be in :data:`KNOWN_PRIMITIVES` (the schema enum is closed); an unknown
            primitive raises ``ValueError`` rather than producing a schema-invalid artifact.
        problem_id: short unique id for this abstraction (e.g. ``PA-001``); must be non-blank.
        failure_modes: optional known failure modes (defaults to ``[]``).
        constraints: optional hard constraints (defaults to ``[]``).
        success_metrics: optional mechanism-level success metrics (defaults to ``[]``).
        abstraction_confidence: advisory confidence in [0, 1] (defaults to 0.5). Clamped-checked:
            a value outside [0, 1] raises ``ValueError`` (the schema would reject it anyway).
        notes: optional notes; when omitted, the derived mechanism phrase from
            :func:`abstract_problem` is used so the surface->mechanism reduction is recorded.

    Returns:
        A dict conforming to problem_abstraction.schema.json.

    Raises:
        ValueError: if ``problem`` is blank, ``problem_id`` is blank, a primitive is unknown,
            or ``abstraction_confidence`` is outside [0, 1].
    """
    if not (problem or "").strip():
        raise ValueError("build_problem_abstraction requires a non-empty problem string")
    if not (problem_id or "").strip():
        raise ValueError("build_problem_abstraction requires a non-empty problem_id")
    if not (0.0 <= abstraction_confidence <= 1.0):
        raise ValueError(
            f"abstraction_confidence must be in [0, 1], got {abstraction_confidence!r}"
        )

    primitives = list(mechanism_primitives)
    unknown = [p for p in primitives if p not in KNOWN_PRIMITIVES]
    if unknown:
        raise ValueError(
            f"build_problem_abstraction: unknown mechanism primitive(s) {unknown!r}; "
            f"allowed primitives are {sorted(KNOWN_PRIMITIVES)}"
        )

    # REUSE abstract_problem for the surface->mechanism reduction (never reimplemented here).
    mechanism_phrase = abstract_problem(problem)
    resolved_notes = notes if notes is not None else f"mechanism phrase: {mechanism_phrase}"

    abstraction: dict = {
        "problem_id": str(problem_id),
        "domain_surface": problem,
        "mechanism_primitives": primitives,
        "failure_modes": list(failure_modes) if failure_modes is not None else [],
        "constraints": list(constraints) if constraints is not None else [],
        "success_metrics": list(success_metrics) if success_metrics is not None else [],
        "formal_form": classify_form(primitives),
        "abstraction_confidence": float(abstraction_confidence),
        "notes": resolved_notes,
    }
    return abstraction


def forms_for_primitive(primitive: str) -> List[str]:
    """Return the formal_form(s) a single primitive can trigger (helper / introspection).

    Useful for tests and for the agent to explain WHY a primitive set resolved to a form. Pure.
    Returns an empty list for an unknown primitive (it triggers no rule).
    """
    return [form for form, triggers in _FORM_RULES if primitive in triggers]


__all__ = [
    "KNOWN_PRIMITIVES",
    "FORMAL_FORMS",
    "classify_form",
    "build_problem_abstraction",
    "forms_for_primitive",
]
