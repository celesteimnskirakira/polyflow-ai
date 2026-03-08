import pytest
from unittest.mock import AsyncMock, patch
from polyflow.engine.executor import execute_step, execute_parallel
from polyflow.schema.workflow import Step, SubStep, AggregateConfig
from polyflow.engine.template import TemplateContext
from polyflow.config import Config


@pytest.fixture
def config():
    return Config(api_keys={"claude": "test", "gemini": "test", "gpt-4": "test"})


@pytest.mark.asyncio
async def test_execute_sequential_step(config):
    step = Step(id="gen", name="Gen", model="claude", prompt="Plan: {{input}}")
    ctx = TemplateContext(input="build API")

    with patch("polyflow.engine.executor.get_model_adapter") as mock_get:
        mock_adapter = AsyncMock()
        mock_adapter.complete = AsyncMock(return_value="Step 1: Setup\nStep 2: Build")
        mock_get.return_value = mock_adapter

        result = await execute_step(step, ctx, config)

    assert result == "Step 1: Setup\nStep 2: Build"
    mock_adapter.complete.assert_called_once()


@pytest.mark.asyncio
async def test_execute_parallel_step(config):
    step = Step(
        id="validate",
        name="Validate",
        type="parallel",
        steps=[
            SubStep(id="gemini", model="gemini", prompt="Review: {{steps.gen.output}}"),
            SubStep(id="gpt4", model="gpt-4", prompt="Review: {{steps.gen.output}}"),
        ],
        aggregate=AggregateConfig(mode="raw"),
    )
    ctx = TemplateContext(input="test", step_outputs={"gen": "the plan"})

    with patch("polyflow.engine.executor.get_model_adapter") as mock_get:
        mock_adapter = AsyncMock()
        mock_adapter.complete = AsyncMock(side_effect=["Gemini says OK", "GPT4 says OK"])
        mock_get.return_value = mock_adapter

        result = await execute_parallel(step, ctx, config)

    assert "Gemini says OK" in result
    assert "GPT4 says OK" in result


@pytest.mark.asyncio
async def test_conditional_step_skipped(config):
    """Steps with a false `if` condition should be skipped."""
    step = Step(
        id="revise", name="Revise", model="claude", prompt="Revise",
        condition="{{hitl.validate.choice}} == 'revise'"
    )
    ctx = TemplateContext(
        input="test",
        hitl_choices={"validate": {"choice": "continue"}}
    )
    result = await execute_step(step, ctx, config)
    assert result is None   # skipped
