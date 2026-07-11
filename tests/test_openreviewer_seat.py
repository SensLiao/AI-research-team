"""openreviewer_seat — optional local seat: parsing, unavailability honesty, leniency anchor (wave 1)."""
from __future__ import annotations

import json

import pytest

from research_agent_teams.tools.openreviewer_seat import (
    SeatUnavailable,
    leniency_offset,
    parse_ratings,
    review_with_local_seat,
)

REVIEW_TEXT = """**Summary:** A solid contribution with some gaps.

Rating: 5
Soundness: 3
Presentation: 2
Contribution: 3
Confidence: 4

The seed policy is unclear and Table 2 aggregates over different splits.
"""


def ok_transport(url, headers, body):
    assert url.endswith("/api/generate")
    req = json.loads(body.decode("utf-8"))
    assert req["stream"] is False and "PAPER:" in req["prompt"]
    return json.dumps({"response": REVIEW_TEXT}).encode("utf-8")


def test_available_seat_parses_ratings(monkeypatch):
    monkeypatch.delenv("RAT_OLLAMA_URL", raising=False)
    out = review_with_local_seat("# Paper\nbody", "Review per NeurIPS template.",
                                 post_transport=ok_transport)
    assert out["available"] is True and out["seat"] == "llama-openreviewer-8b"
    assert out["ratings"] == {"rating": 5.0, "soundness": 3.0, "presentation": 2.0,
                              "contribution": 3.0, "confidence": 4.0}
    assert "seed policy" in out["review_text"]


def test_env_url_and_model_override(monkeypatch):
    seen = {}

    def capture(url, headers, body):
        seen["url"] = url
        seen["model"] = json.loads(body.decode("utf-8"))["model"]
        return json.dumps({"response": "Rating: 4"}).encode("utf-8")

    monkeypatch.setenv("RAT_OLLAMA_URL", "http://127.0.0.1:9999/")
    monkeypatch.setenv("RAT_OPENREVIEWER_MODEL", "openreviewer:8b-q4")
    out = review_with_local_seat("p", "t", post_transport=capture)
    assert out["available"] and seen["url"] == "http://127.0.0.1:9999/api/generate"
    assert seen["model"] == "openreviewer:8b-q4"


def test_unreachable_endpoint_is_honestly_unavailable():
    def down(url, headers, body):
        raise SeatUnavailable("local Ollama endpoint unreachable at http://127.0.0.1:11434: refused")
    out = review_with_local_seat("p", "t", post_transport=down)
    assert out["available"] is False and "unreachable" in out["reason"]


def test_malformed_or_empty_response_is_unavailable():
    out = review_with_local_seat("p", "t",
                                 post_transport=lambda u, h, b: b"not json at all")
    assert out["available"] is False and "malformed" in out["reason"]
    out2 = review_with_local_seat("p", "t",
                                  post_transport=lambda u, h, b: json.dumps({"response": "  "}).encode())
    assert out2["available"] is False and "empty" in out2["reason"]


def test_input_validation():
    with pytest.raises(ValueError):
        review_with_local_seat("  ", "t", post_transport=ok_transport)
    with pytest.raises(ValueError):
        review_with_local_seat("p", "", post_transport=ok_transport)


def test_remote_endpoint_is_refused_manuscript_never_leaves_box():
    # Adversarial (reviewer HIGH/MEDIUM): the LOCAL-ONLY contract must be ENFORCED, not just stated.
    def must_not_be_called(url, headers, body):
        raise AssertionError("transport must not run for a rejected non-local endpoint")
    for bad in ("http://evil.example.com:11434", "https://10.0.0.5/api",
                "http://user:pass@127.0.0.1:11434", "ftp://127.0.0.1"):
        with pytest.raises(ValueError):
            review_with_local_seat("paper", "template", url=bad, post_transport=must_not_be_called)


def test_loopback_variants_are_allowed(monkeypatch):
    monkeypatch.delenv("RAT_OLLAMA_URL", raising=False)
    for good in ("http://127.0.0.1:11434", "http://localhost:11434", "http://[::1]:11434"):
        out = review_with_local_seat("paper", "template", url=good, post_transport=ok_transport)
        assert out["available"] is True


def test_env_remote_url_is_refused(monkeypatch):
    monkeypatch.setenv("RAT_OLLAMA_URL", "http://203.0.113.9:11434")
    with pytest.raises(ValueError):
        review_with_local_seat("paper", "template",
                               post_transport=lambda u, h, b: b"{}")


def test_parse_ratings_first_occurrence_wins_and_leniency_offset():
    text = "Rating: 6\nlater the text says Rating: 2 again"
    assert parse_ratings(text) == {"rating": 6.0}
    assert leniency_offset({"rating": 5.0}, 6.5) == 1.5      # panel runs 1.5 lenient vs the seat
    assert leniency_offset({}, 6.5) is None
    assert leniency_offset({"rating": 5.0}, None) is None
