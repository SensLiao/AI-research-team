"""Deterministic failure classifier for EXECUTE-stage triage.

Maps a raw stack-trace string to an ``error_class`` string via regex/keyword
matching. This turns the failure-triager agent's golden test into a guarantee:
the agent calls this function; the test proves the correct class is returned
for crafted traces.

Error classes (aligned with triage_report.schema.json enum):
  - "shape"          CUDA/tensor shape or size mismatch
  - "oom"            Out-of-memory (GPU or CPU)
  - "device_assert"  CUDA device-side assertion
  - "nan_loss"       NaN or Inf in loss / gradient
  - "import_error"   Missing module / ImportError / ModuleNotFoundError
  - "file_not_found" Missing file or checkpoint (FileNotFoundError / No such file)
  - "timeout"        Process timeout / watchdog / SIGTERM
  - "permission"     Permission denied
  - "unknown"        None of the above matched (safe fallback)

Rules are checked in priority order (most-specific first).  A trace can match
multiple rules in principle, but only the FIRST match is returned — so ordering
matters.  Rule order is documented inline.

Pure function: no I/O, no network, no LLM.  Deterministic on the same input.
"""
from __future__ import annotations

import re
from typing import List, Tuple

# ---------------------------------------------------------------------------
# Rule table: (error_class, list-of-patterns)
# Patterns are matched case-insensitively against the full trace string.
# First matching rule wins (priority order).
# ---------------------------------------------------------------------------
_RULES: List[Tuple[str, List[str]]] = [
    # 1. CUDA device-side assert — more specific than generic CUDA, check first
    (
        "device_assert",
        [
            r"device-side assert triggered",
            r"device_assert",
            r"CUDA error: device-side assert",
        ],
    ),
    # 2. Shape / size mismatch — "CUDA error" is often present, but the
    #    distinguishing signal is shape/size language
    (
        "shape",
        [
            r"size mismatch",
            r"shape mismatch",
            r"shapes.*mismatch",
            r"mismatch.*shape",
            r"Expected.*shape",
            r"shape.*expected",
            r"mat1 and mat2",
            r"RuntimeError.*sizes of tensors must match",
            r"RuntimeError.*size of tensor",
            r"dimension out of range",
        ],
    ),
    # 3. Out-of-memory — GPU or CPU
    (
        "oom",
        [
            r"out of memory",
            r"CUDA out of memory",
            r"OutOfMemoryError",
            r"OOM",
            r"Cannot allocate memory",
        ],
    ),
    # 4. NaN / Inf in loss or gradient
    (
        "nan_loss",
        [
            r"nan.*loss",
            r"loss.*nan",
            r"inf.*loss",
            r"loss.*inf",
            r"nan.*gradient",
            r"gradient.*nan",
            r"FloatingPointError",
            r"invalid value encountered",
        ],
    ),
    # 5. Import / missing module
    (
        "import_error",
        [
            r"ImportError",
            r"ModuleNotFoundError",
            r"No module named",
            r"cannot import name",
        ],
    ),
    # 6. File not found / missing checkpoint
    (
        "file_not_found",
        [
            r"FileNotFoundError",
            r"No such file or directory",
            r"checkpoint.*not found",
            r"not found.*checkpoint",
            r"path.*does not exist",
        ],
    ),
    # 7. Timeout / watchdog
    (
        "timeout",
        [
            r"TimeoutError",
            r"timed out",
            r"SIGTERM",
            r"watchdog",
            r"timeout expired",
        ],
    ),
    # 8. Permission denied
    (
        "permission",
        [
            r"PermissionError",
            r"Permission denied",
            r"EACCES",
        ],
    ),
]


def classify_trace(trace: str) -> str:
    """Classify a stack-trace string into an error_class.

    Args:
        trace: The raw stack trace / error output string (may be multi-line).

    Returns:
        One of the error_class enum values defined in triage_report.schema.json.
        Returns ``"unknown"`` if no rule matches (safe fallback — never raises).
    """
    if not isinstance(trace, str):
        return "unknown"

    for error_class, patterns in _RULES:
        for pattern in patterns:
            if re.search(pattern, trace, re.IGNORECASE):
                return error_class

    return "unknown"


def build_triage(condition_id: str, trace: str) -> dict:
    """Build a minimal triage_report payload (verdict derived from classifier).

    The agent should enrich this with ``remediation_hint`` and ``notes`` before
    writing the artifact.  This helper ensures ``error_class`` is always
    machine-derived.

    Args:
        condition_id: The experiment condition that produced the failure.
        trace: The raw stack trace or error output string.

    Returns:
        A dict conforming to triage_report.schema.json (required fields only).
    """
    return {
        "condition_id": condition_id,
        "error_class": classify_trace(trace),
        "stack_trace_excerpt": trace,
    }
