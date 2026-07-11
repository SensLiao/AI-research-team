"""Real tests for the failure_triage deterministic classifier (EXECUTE-stage).

Proves that:
  - a CUDA shape/size mismatch trace -> "shape"
  - a CUDA OOM trace -> "oom"
  - a device-side assert trace -> "device_assert"
  - a NaN loss trace -> "nan_loss"
  - an ImportError trace -> "import_error"
  - a FileNotFoundError trace -> "file_not_found"
  - a timeout trace -> "timeout"
  - a permission denied trace -> "permission"
  - an unrecognised trace -> "unknown" (safe fallback)
  - device_assert is not misclassified as shape (priority order matters)
  - the build_triage helper produces a minimal conformant payload
"""
from __future__ import annotations

import pytest

from research_agent_teams.tools.failure_triage import build_triage, classify_trace


# ---------------------------------------------------------------------------
# Crafted traces -- each is a realistic excerpt from a real failure scenario
# ---------------------------------------------------------------------------

_SHAPE_TRACE = """\
Traceback (most recent call last):
  File "train.py", line 142, in forward
    out = self.fc(x)
  File "/opt/conda/lib/python3.10/site-packages/torch/nn/modules/linear.py", line 114, in forward
    return F.linear(input, self.weight, self.bias)
RuntimeError: mat1 and mat2 shapes cannot be multiplied (32x512 and 256x10)
"""

_SHAPE_TRACE_2 = """\
RuntimeError: sizes of tensors must match except in dimension 0. Got 128 and 64 in dimension 1
"""

_OOM_TRACE = """\
Traceback (most recent call last):
  File "train.py", line 98, in train_epoch
    loss.backward()
torch.cuda.OutOfMemoryError: CUDA out of memory. Tried to allocate 1.95 GiB
(GPU 0; 23.69 GiB total capacity; 21.12 GiB already allocated)
"""

_DEVICE_ASSERT_TRACE = """\
Traceback (most recent call last):
  File "train.py", line 200, in forward
    logits = self.head(features)
RuntimeError: CUDA error: device-side assert triggered
CUDA kernel errors might be asynchronously reported at some other API call.
"""

_NAN_LOSS_TRACE = """\
  File "train.py", line 78, in train_step
    loss = criterion(logits, targets)
FloatingPointError: invalid value encountered in scalar divide
nan loss detected at step 42
"""

_IMPORT_TRACE = """\
Traceback (most recent call last):
  File "train.py", line 5, in <module>
    from monai.transforms import Compose
ModuleNotFoundError: No module named 'monai'
"""

_FILE_NOT_FOUND_TRACE = """\
Traceback (most recent call last):
  File "train.py", line 33, in load_checkpoint
    state = torch.load(args.resume)
FileNotFoundError: [Errno 2] No such file or directory: '/checkpoints/best.pth'
"""

_TIMEOUT_TRACE = """\
Process timed out after 3600 seconds. Watchdog triggered SIGTERM.
Training loop did not complete epoch 1 within the configured timeout.
"""

_PERMISSION_TRACE = """\
Traceback (most recent call last):
  File "train.py", line 210, in save_checkpoint
    torch.save(state, path)
PermissionError: [Errno 13] Permission denied: '/mnt/shared/checkpoints/latest.pth'
"""

_UNKNOWN_TRACE = """\
Segmentation fault (core dumped)
"""


# ---------------------------------------------------------------------------
# Tests: one-to-one classification
# ---------------------------------------------------------------------------

def test_shape_mismatch_classified_as_shape():
    assert classify_trace(_SHAPE_TRACE) == "shape"


def test_size_mismatch_also_shape():
    assert classify_trace(_SHAPE_TRACE_2) == "shape"


def test_oom_classified_as_oom():
    assert classify_trace(_OOM_TRACE) == "oom"


def test_device_assert_classified_correctly():
    # device_assert rule appears before shape in priority order --
    # must not be misclassified as shape even if the word "mismatch" appears nearby
    assert classify_trace(_DEVICE_ASSERT_TRACE) == "device_assert"


def test_nan_loss_classified():
    assert classify_trace(_NAN_LOSS_TRACE) == "nan_loss"


def test_import_error_classified():
    assert classify_trace(_IMPORT_TRACE) == "import_error"


def test_file_not_found_classified():
    assert classify_trace(_FILE_NOT_FOUND_TRACE) == "file_not_found"


def test_timeout_classified():
    assert classify_trace(_TIMEOUT_TRACE) == "timeout"


def test_permission_classified():
    assert classify_trace(_PERMISSION_TRACE) == "permission"


def test_unknown_trace_returns_unknown():
    assert classify_trace(_UNKNOWN_TRACE) == "unknown"


# ---------------------------------------------------------------------------
# Priority: device_assert must beat shape
# ---------------------------------------------------------------------------

def test_device_assert_priority_over_shape():
    """A trace mentioning both 'device-side assert' and 'size mismatch' (edge case)
    must be classified as device_assert because that rule is checked first."""
    combined = (
        "RuntimeError: CUDA error: device-side assert triggered\n"
        "Note: size mismatch may be the root cause\n"
    )
    assert classify_trace(combined) == "device_assert"


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

def test_non_string_input_returns_unknown():
    """classify_trace should never raise on unexpected input types."""
    assert classify_trace(None) == "unknown"  # type: ignore[arg-type]
    assert classify_trace(42) == "unknown"  # type: ignore[arg-type]


def test_empty_string_returns_unknown():
    assert classify_trace("") == "unknown"


def test_case_insensitivity():
    """Matching must be case-insensitive (e.g. 'Out Of Memory' vs 'out of memory')."""
    assert classify_trace("CUDA Out Of Memory encountered during backward pass") == "oom"


# ---------------------------------------------------------------------------
# build_triage helper
# ---------------------------------------------------------------------------

def test_build_triage_produces_required_fields():
    result = build_triage("cond_001", _SHAPE_TRACE)
    assert result["condition_id"] == "cond_001"
    assert result["error_class"] == "shape"
    assert result["stack_trace_excerpt"] == _SHAPE_TRACE


def test_build_triage_unknown_trace():
    result = build_triage("cond_002", _UNKNOWN_TRACE)
    assert result["error_class"] == "unknown"
    assert result["condition_id"] == "cond_002"
