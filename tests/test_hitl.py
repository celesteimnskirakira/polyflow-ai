import pytest
from unittest.mock import patch
from polyflow.engine.hitl import prompt_hitl, HitlResult


def test_hitl_continue(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "c")
    result = prompt_hitl(
        message="Review complete. Continue?",
        options=["continue", "abort"],
        content="Some model output here"
    )
    assert result.choice == "continue"
    assert result.note == ""


def test_hitl_revise_captures_note(monkeypatch):
    inputs = iter(["r", "Please add error handling"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    result = prompt_hitl(
        message="Review complete.",
        options=["continue", "abort", "revise"],
        content="Plan output"
    )
    assert result.choice == "revise"
    assert result.note == "Please add error handling"


def test_hitl_abort(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "a")
    result = prompt_hitl(
        message="Confirm?",
        options=["continue", "abort"],
        content=""
    )
    assert result.choice == "abort"
