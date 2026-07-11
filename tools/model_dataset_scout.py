"""Deterministic core of the model-dataset-scout (the 'shortlister').

Given a task description and a list of candidate dicts (each with kind/name/ref plus
optional modality/license/fit_notes), assemble and return the model_dataset_candidates
payload. The LLM agent gathers candidates by reading domain profiles, literature, and
known registries, then calls this builder; the builder — not the LLM — assembles the
payload and derives the counts, so the output is mechanical, not a vibe.

No I/O, no network, no LLM. Pure function over dicts.
"""
from __future__ import annotations

from typing import List


def build_candidates(task: str, candidates: List[dict]) -> dict:
    """Build a model_dataset_candidates payload.

    Args:
        task: Non-empty string describing the research task.
        candidates: List of candidate dicts. Each must contain at minimum
            'kind' ('model' | 'dataset'), 'name', and 'ref'.
            Optional fields: 'modality', 'license', 'fit_notes'.
            Dicts are passed through unmutated; caller is responsible for
            supplying only schema-allowed fields.

    Returns:
        A dict with keys: task, candidates, n_models, n_datasets.
        n_models  = count of entries where kind == 'model'
        n_datasets = count of entries where kind == 'dataset'
    """
    n_models: int = sum(1 for c in candidates if c.get("kind") == "model")
    n_datasets: int = sum(1 for c in candidates if c.get("kind") == "dataset")
    return {
        "task": task,
        "candidates": list(candidates),
        "n_models": n_models,
        "n_datasets": n_datasets,
    }
