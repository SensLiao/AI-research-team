"""Deterministic significance testing for the ANALYZE stage (audit finding H6 fix).

The result-analyzer historically reported only `delta = value - baseline_value` — a raw
subtraction with no notion of whether a difference is *real* or *noise*. This module supplies the
missing statistical layer: a paired permutation test, a percentile bootstrap CI, Holm-Bonferroni
multiple-comparison correction, and a normal-approximation post-hoc power estimate. It also exposes
`enrich_result_summary`, which decorates an existing result_summary payload with these statistics
when per-seed data is available.

Design invariants (mirrors the rest of the machine's tools):
  - Pure stdlib only. NO scipy / NO numpy. The normal CDF uses ``math.erf``.
  - Deterministic. Every randomized routine takes a caller-supplied ``seed`` and uses a private
    ``random.Random(seed)`` instance — NEVER the module-level ``random`` and NEVER a wall clock.
    Same inputs (and same seed) -> byte-identical outputs.
  - Exact where feasible. The permutation test enumerates ALL ``2**n`` sign flips when ``n <= 12``
    (``method:"exact_permutation"``); above that it falls back to seeded Monte Carlo
    (``method:"mc_permutation"``) with the standard ``(count+1)/(n_resamples+1)`` smoothing so a
    reported p-value is never exactly 0.
  - Immutable. ``enrich_result_summary`` returns a NEW dict and never mutates its inputs.

Statistical references:
  - Paired permutation (randomization) test: Good, *Permutation, Parametric, and Bootstrap Tests of
    Hypotheses*, 3rd ed. (sign-flip on paired differences is the exact randomization distribution
    under the sharp null of no treatment effect).
  - Percentile bootstrap CI: Efron & Tibshirani, *An Introduction to the Bootstrap* (1993), §13.3.
  - Holm step-down: Holm (1979), "A Simple Sequentially Rejective Multiple Test Procedure",
    *Scand. J. Statist.* 6:65-70.
  - Post-hoc power (normal approximation): Cohen, *Statistical Power Analysis* (1988); the paired
    z-approximation ``power = Phi(sqrt(n)*|d|/sd - z_{1-alpha/2})``.
"""
from __future__ import annotations

import itertools
import math
import random
from typing import Dict, List


# --------------------------------------------------------------------------- #
#  Normal-distribution helpers (stdlib only)                                   #
# --------------------------------------------------------------------------- #

def _phi(z: float) -> float:
    """Standard-normal CDF Phi(z) via the error function (``math.erf``). Exact, no tables."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _norm_ppf(p: float) -> float:
    """Inverse standard-normal CDF (quantile) via the Acklam rational approximation.

    Source: Peter J. Acklam, "An algorithm for computing the inverse normal cumulative
    distribution function" (2003). Absolute error < 1.15e-9 over the open interval (0, 1),
    which is far tighter than anything this advisory power calculation needs. Exact endpoints
    are clamped to +/- inf for p in {0, 1}.

    For the common case alpha = 0.05 this returns z_{0.975} = 1.9599639845... matching the
    canonical 1.959964 constant to the precision used elsewhere in the literature.
    """
    if p <= 0.0:
        return float("-inf")
    if p >= 1.0:
        return float("inf")

    # Coefficients for the Acklam approximation.
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00,
         -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00,
         3.754408661907416e+00)

    plow = 0.02425
    phigh = 1.0 - plow

    if p < plow:  # lower tail
        q = math.sqrt(-2.0 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
               ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    if p <= phigh:  # central region
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
               (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)
    # upper tail
    q = math.sqrt(-2.0 * math.log(1.0 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / \
            ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)


# --------------------------------------------------------------------------- #
#  1. Paired permutation test                                                  #
# --------------------------------------------------------------------------- #

def paired_permutation_test(
    xs: List[float],
    ys: List[float],
    *,
    seed: int,
    n_resamples: int = 10000,
) -> dict:
    """Two-sided paired permutation (sign-flip) test on the paired differences ``xs[i] - ys[i]``.

    Under the sharp null of "no effect", flipping the sign of any paired difference is
    equiprobable; the test statistic is the absolute mean difference and the p-value is the
    fraction of sign-flip assignments whose absolute mean difference is >= the observed one.

    Exactness:
      - ``n <= 12``  -> enumerate all ``2**n`` sign assignments exactly (``method:"exact_permutation"``).
      - ``n  > 12``  -> seeded Monte Carlo over ``n_resamples`` random sign assignments
        (``method:"mc_permutation"``), with ``(count + 1) / (n_resamples + 1)`` smoothing so the
        reported p-value is never exactly 0 and the observed assignment is always counted.

    Parameters
    ----------
    xs, ys:
        Paired observations (e.g. metric values for the condition and its baseline, paired by seed).
        ``len(xs) == len(ys) == n`` and ``n >= 2`` are required, else ``ValueError``.
    seed:
        Caller-supplied seed for the Monte-Carlo branch. A private ``random.Random(seed)`` instance
        is used; the module-level RNG and the wall clock are never touched. Ignored on the exact
        branch (which is fully deterministic regardless of seed).
    n_resamples:
        Number of Monte-Carlo sign assignments (only used when ``n > 12``).

    Returns
    -------
    dict
        ``{"p_value": float, "mean_diff": float, "n": int, "method": str}``.
        An all-zero difference vector (``xs == ys``) yields ``p_value == 1.0`` (the null is
        trivially true; every sign flip reproduces the same zero statistic).
    """
    n = len(xs)
    if n != len(ys):
        raise ValueError(f"xs and ys must be the same length: got {n} and {len(ys)}")
    if n < 2:
        raise ValueError(f"paired permutation test needs n >= 2 paired observations, got n={n}")

    diffs = [float(x) - float(y) for x, y in zip(xs, ys)]
    observed_sum = math.fsum(diffs)
    mean_diff = observed_sum / n

    # All-zero differences -> no effect to detect; the statistic is 0 for every sign flip.
    if all(d == 0.0 for d in diffs):
        return {"p_value": 1.0, "mean_diff": 0.0, "n": n, "method": "exact_permutation"}

    abs_observed = abs(observed_sum)  # |mean| ordering == |sum| ordering (n is constant)
    # A tiny absolute tolerance guards against float-rounding excluding the observed assignment
    # (and its mirror) from the >= comparison.
    tol = 1e-12 * (1.0 + abs_observed)

    if n <= 12:
        # Exact: enumerate every sign vector in {-1, +1}^n.
        count = 0
        total = 0
        for signs in itertools.product((1.0, -1.0), repeat=n):
            stat = abs(math.fsum(s * d for s, d in zip(signs, diffs)))
            if stat >= abs_observed - tol:
                count += 1
            total += 1
        return {
            "p_value": count / total,
            "mean_diff": mean_diff,
            "n": n,
            "method": "exact_permutation",
        }

    # Monte Carlo: seeded sign flips, +1 smoothing (observed assignment counted in numerator).
    rng = random.Random(seed)
    count = 0
    for _ in range(n_resamples):
        stat = abs(math.fsum((d if rng.random() < 0.5 else -d) for d in diffs))
        if stat >= abs_observed - tol:
            count += 1
    p_value = (count + 1) / (n_resamples + 1)
    return {
        "p_value": p_value,
        "mean_diff": mean_diff,
        "n": n,
        "method": "mc_permutation",
    }


# --------------------------------------------------------------------------- #
#  2. Percentile bootstrap CI                                                  #
# --------------------------------------------------------------------------- #

def bootstrap_ci(
    values: List[float],
    *,
    seed: int,
    n_resamples: int = 10000,
    alpha: float = 0.05,
) -> dict:
    """Percentile bootstrap confidence interval for the mean of ``values``.

    Resamples ``values`` with replacement ``n_resamples`` times, takes the mean of each resample,
    and reports the ``alpha/2`` and ``1 - alpha/2`` percentiles of the bootstrap mean distribution
    as ``low`` / ``high`` (a two-sided ``1 - alpha`` interval).

    Parameters
    ----------
    values:
        Sample to bootstrap (e.g. per-seed metric values for one condition). ``len(values) >= 2``
        is required, else ``ValueError``.
    seed:
        Caller-supplied seed; a private ``random.Random(seed)`` instance drives all resampling.
    n_resamples:
        Number of bootstrap resamples.
    alpha:
        Two-sided significance level; the interval is ``[alpha/2, 1 - alpha/2]`` percentile.

    Returns
    -------
    dict
        ``{"mean": float, "low": float, "high": float, "n": int}`` where ``mean`` is the sample mean
        of the original data and ``low``/``high`` are the percentile-bootstrap interval endpoints.
    """
    n = len(values)
    if n < 2:
        raise ValueError(f"bootstrap_ci needs n >= 2 values, got n={n}")

    vals = [float(v) for v in values]
    sample_mean = math.fsum(vals) / n

    rng = random.Random(seed)
    means: List[float] = []
    for _ in range(n_resamples):
        resample_sum = math.fsum(vals[rng.randrange(n)] for _ in range(n))
        means.append(resample_sum / n)
    means.sort()

    low = _percentile(means, alpha / 2.0)
    high = _percentile(means, 1.0 - alpha / 2.0)
    return {"mean": sample_mean, "low": low, "high": high, "n": n}


def _percentile(sorted_values: List[float], q: float) -> float:
    """Linear-interpolation percentile of an already-sorted list (q in [0, 1]).

    Uses the C = 1 ("linear", a.k.a. numpy default) interpolation convention so endpoints land on
    the min/max and interior quantiles interpolate between neighbours.
    """
    if not sorted_values:
        raise ValueError("cannot take a percentile of an empty list")
    m = len(sorted_values)
    if m == 1:
        return sorted_values[0]
    rank = q * (m - 1)
    lo_idx = int(math.floor(rank))
    hi_idx = int(math.ceil(rank))
    if lo_idx == hi_idx:
        return sorted_values[lo_idx]
    frac = rank - lo_idx
    return sorted_values[lo_idx] * (1.0 - frac) + sorted_values[hi_idx] * frac


# --------------------------------------------------------------------------- #
#  3. Holm-Bonferroni step-down correction                                     #
# --------------------------------------------------------------------------- #

def holm_bonferroni(p_values: List[float], alpha: float = 0.05) -> dict:
    """Holm step-down multiple-comparison correction.

    Standard procedure (Holm 1979): sort the ``m`` p-values ascending; the i-th smallest
    (0-based) is multiplied by ``m - i``; the adjusted sequence is then made monotone
    non-decreasing (each adjusted value is at least the previous one) and capped at 1.0.
    A hypothesis is significant iff its adjusted p-value ``<= alpha``.

    The returned lists are in the SAME ORDER as the input ``p_values`` (not sorted), so each
    position lines up with the caller's original hypothesis.

    Parameters
    ----------
    p_values:
        Raw per-hypothesis p-values. May be empty (returns empty lists).
    alpha:
        Family-wise significance level.

    Returns
    -------
    dict
        ``{"adjusted": list[float], "significant": list[bool]}`` — both in input order. ``adjusted``
        is monotone within the sorted ordering and capped at 1.0.
    """
    m = len(p_values)
    if m == 0:
        return {"adjusted": [], "significant": []}

    # Sort positions by raw p ascending (stable -> deterministic on ties).
    order = sorted(range(m), key=lambda i: p_values[i])

    adjusted_sorted: List[float] = []
    running_max = 0.0
    for rank, idx in enumerate(order):
        raw = float(p_values[idx])
        candidate = (m - rank) * raw          # Holm multiplier for the rank-th smallest
        running_max = max(running_max, candidate)  # enforce monotone non-decreasing
        adjusted_sorted.append(min(running_max, 1.0))  # cap at 1.0

    # Scatter back to input order.
    adjusted = [0.0] * m
    for sorted_pos, idx in enumerate(order):
        adjusted[idx] = adjusted_sorted[sorted_pos]
    significant = [adj <= alpha for adj in adjusted]
    return {"adjusted": adjusted, "significant": significant}


# --------------------------------------------------------------------------- #
#  4. Post-hoc paired power (normal approximation)                             #
# --------------------------------------------------------------------------- #

def approx_paired_power(
    mean_diff: float,
    sd_diff: float,
    n: int,
    alpha: float = 0.05,
) -> float:
    """Normal-approximation post-hoc power for a two-sided paired test.

    Uses the standard z-approximation::

        power = Phi( sqrt(n) * |mean_diff| / sd_diff  -  z_{1 - alpha/2} )

    where ``Phi`` is the standard-normal CDF (``_phi`` / ``math.erf``) and ``z_{1 - alpha/2}`` is the
    two-sided critical value (``_norm_ppf``; for alpha = 0.05 this is 1.959964...). This is the
    paired-test analogue of Cohen's (1988) power formula and is intentionally an *approximation*
    (it ignores the t-distribution's extra tail mass at small ``n``), which is acceptable for the
    advisory power audit it backs.

    Degenerate inputs return ``0.0`` (no usable power signal): ``sd_diff <= 0`` (no variability to
    estimate an effect against) or ``n < 2`` (a single point has no paired distribution).

    Returns
    -------
    float
        Estimated power in ``[0, 1]``.
    """
    if sd_diff <= 0.0 or n < 2:
        return 0.0
    z_crit = _norm_ppf(1.0 - alpha / 2.0)
    ncp = math.sqrt(n) * abs(mean_diff) / sd_diff   # noncentrality (effect) term
    return _phi(ncp - z_crit)


# --------------------------------------------------------------------------- #
#  5. Enrich a result_summary payload with statistics                          #
# --------------------------------------------------------------------------- #

def _sample_sd(values: List[float]) -> float:
    """Sample standard deviation (Bessel-corrected, n-1). Returns 0.0 for fewer than 2 values."""
    n = len(values)
    if n < 2:
        return 0.0
    mean = math.fsum(values) / n
    var = math.fsum((v - mean) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def enrich_result_summary(
    result_summary_payload: dict,
    per_seed: dict,
    *,
    seed: int,
    alpha: float = 0.05,
) -> dict:
    """Return a COPY of ``result_summary_payload`` decorated with per-finding significance stats.

    This function is the H6 fix at the payload level: for every finding that has paired per-seed
    data for BOTH its condition and its baseline, it computes a paired permutation test and a
    bootstrap CI, then applies a Holm-Bonferroni correction across all tested findings, and attaches
    the results to the finding. Findings without pairable per-seed data are left untouched — no
    statistic is ever fabricated.

    Immutability
    ------------
    The input ``result_summary_payload`` is NEVER mutated; a deep-enough copy is built and returned.

    ``per_seed`` shape
    ------------------
    ``{condition_id: {metric_name: [float, ...]}}`` — one value per seed, paired across conditions by
    LIST INDEX (so ``per_seed[cond][metric][k]`` and ``per_seed[baseline][metric][k]`` are the same
    seed ``k``). A finding is "pairable" iff:
      - it carries a ``baseline_condition_id`` (or one is recoverable, see below), AND
      - both the condition's and the baseline's per-seed lists for the finding's metric exist, AND
      - those two lists have equal length ``>= 2``.

    Baseline condition resolution
    -----------------------------
    A finding identifies its condition via ``condition_id`` and its metric via ``metric``. The
    baseline condition is taken from the finding's ``baseline_condition_id`` field when present.
    A finding that merely has a scalar ``baseline_value`` but no identifiable baseline *condition*
    in ``per_seed`` is NOT pairable (there is no per-seed baseline vector to test against) and is
    left unannotated.

    Attached fields (only on pairable findings)
    --------------------------------------------
    ``p_value, ci_low, ci_high, n_seeds, significant_after_correction, stats_method``.

    Top-level ``stats`` block (always added)
    ----------------------------------------
    ``{"alpha", "correction": "holm", "seed", "n_findings_tested"}``; when nothing was testable it
    also carries ``"note": "insufficient per-seed data — no significance computed"``.

    Returns
    -------
    dict
        A new payload dict. The original is unchanged.
    """
    # Deep-ish copy: clone the dict and every finding dict so we never touch the caller's objects.
    enriched: dict = dict(result_summary_payload)
    findings_in = result_summary_payload.get("findings", []) or []
    findings_out: List[dict] = [dict(f) for f in findings_in]

    # First pass: identify pairable findings and compute their permutation p-values + bootstrap CIs.
    # We must defer the significance verdict until after Holm correction across ALL tested p-values.
    pending: List[Dict] = []  # one entry per pairable finding: {idx, p_value, method, ci_low, ci_high, n}
    for idx, finding in enumerate(findings_out):
        condition_id = finding.get("condition_id")
        metric = finding.get("metric")
        baseline_condition_id = finding.get("baseline_condition_id")
        if condition_id is None or metric is None or baseline_condition_id is None:
            continue

        cond_metrics = per_seed.get(condition_id)
        base_metrics = per_seed.get(baseline_condition_id)
        if not isinstance(cond_metrics, dict) or not isinstance(base_metrics, dict):
            continue

        xs = cond_metrics.get(metric)
        ys = base_metrics.get(metric)
        if not isinstance(xs, (list, tuple)) or not isinstance(ys, (list, tuple)):
            continue
        if len(xs) != len(ys) or len(xs) < 2:
            continue

        xs_f = [float(v) for v in xs]
        ys_f = [float(v) for v in ys]

        perm = paired_permutation_test(xs_f, ys_f, seed=seed, n_resamples=10000)
        ci = bootstrap_ci(xs_f, seed=seed, n_resamples=10000, alpha=alpha)
        pending.append({
            "idx": idx,
            "p_value": perm["p_value"],
            "method": perm["method"],
            "ci_low": ci["low"],
            "ci_high": ci["high"],
            "n": ci["n"],
        })

    # Second pass: Holm-Bonferroni across all tested findings, then attach fields.
    if pending:
        holm = holm_bonferroni([p["p_value"] for p in pending], alpha=alpha)
        for slot, sig in zip(pending, holm["significant"]):
            f = findings_out[slot["idx"]]
            f["p_value"] = slot["p_value"]
            f["ci_low"] = slot["ci_low"]
            f["ci_high"] = slot["ci_high"]
            f["n_seeds"] = slot["n"]
            f["significant_after_correction"] = bool(sig)
            f["stats_method"] = slot["method"]

    enriched["findings"] = findings_out
    stats_block: dict = {
        "alpha": alpha,
        "correction": "holm",
        "seed": seed,
        "n_findings_tested": len(pending),
    }
    if not pending:
        stats_block["note"] = "insufficient per-seed data — no significance computed"
    enriched["stats"] = stats_block
    return enriched
