import pytest
from polyflow.engine.template import render, TemplateContext


def test_render_input_variable():
    ctx = TemplateContext(input="build a REST API")
    result = render("Task: {{input}}", ctx)
    assert result == "Task: build a REST API"


def test_render_step_output():
    ctx = TemplateContext(
        input="test",
        step_outputs={"generate": "Here is the plan: step 1, step 2"}
    )
    result = render("Review: {{steps.generate.output}}", ctx)
    assert result == "Review: Here is the plan: step 1, step 2"


def test_render_fallback_pipe():
    """{{a | b}} uses b when a is empty/missing."""
    ctx = TemplateContext(
        input="test",
        step_outputs={"generate": "original plan"}
        # 'revise' not present
    )
    result = render("Plan: {{steps.revise.output | steps.generate.output}}", ctx)
    assert result == "Plan: original plan"


def test_render_fallback_pipe_literal():
    """{{a | literal string}} uses the literal when a is missing."""
    ctx = TemplateContext(input="test")
    result = render("Note: {{steps.missing.output | no output yet}}", ctx)
    assert result == "Note: no output yet"


def test_render_vars():
    ctx = TemplateContext(input="test", vars={"language": "zh"})
    result = render("Language: {{vars.language}}", ctx)
    assert result == "Language: zh"


def test_render_context_string():
    ctx = TemplateContext(input="test", context_str="src/\n  main.py")
    result = render("Context: {{context}}", ctx)
    assert result == "Context: src/\n  main.py"
