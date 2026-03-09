import pytest
from unittest.mock import AsyncMock, patch
from polyflow.engine.executor import execute_step, execute_parallel
from polyflow.schema.workflow import Step, SubStep, AggregateConfig, OnError
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
async def test_aggregate_model_calls_llm(config):
    """aggregate.model triggers an LLM summarization call after parallel substeps."""
    step = Step(
        id="validate",
        name="Validate",
        type="parallel",
        steps=[
            SubStep(id="a", model="claude", prompt="Review A"),
            SubStep(id="b", model="gemini", prompt="Review B"),
        ],
        aggregate=AggregateConfig(mode="diff", model="claude"),
    )
    ctx = TemplateContext(input="test")

    with patch("polyflow.engine.executor.get_model_adapter") as mock_get:
        mock_adapter = AsyncMock()
        # First two calls = substep completions, third = aggregate summary
        mock_adapter.complete = AsyncMock(side_effect=["A output", "B output", "Final summary"])
        mock_get.return_value = mock_adapter

        result = await execute_parallel(step, ctx, config)

    assert result == "Final summary"
    assert mock_adapter.complete.call_count == 3


@pytest.mark.asyncio
async def test_non_retryable_error_skips_backoff(config):
    """Client errors (401/400) should not be retried — fail immediately."""
    step = Step(
        id="s1", name="S1", model="claude", prompt="test",
        on_error=OnError(retry=3, fallback="continue"),
    )
    ctx = TemplateContext(input="test")

    call_count = 0

    async def auth_error(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise RuntimeError("401 Unauthorized")

    with patch("polyflow.engine.executor.get_model_adapter") as mock_get:
        mock_adapter = AsyncMock()
        mock_adapter.complete = auth_error
        mock_get.return_value = mock_adapter
        result = await execute_step(step, ctx, config)

    assert result is None
    assert call_count == 1  # should NOT retry on 401


@pytest.mark.asyncio
async def test_rate_limit_error_is_retried(config):
    """429 rate limit errors should be retried up to on_error.retry times."""
    step = Step(
        id="s1", name="S1", model="claude", prompt="test",
        on_error=OnError(retry=2, fallback="continue"),
    )
    ctx = TemplateContext(input="test")

    call_count = 0

    async def rate_limited(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise RuntimeError("429 Too Many Requests")
        return "success"

    with patch("polyflow.engine.executor.get_model_adapter") as mock_get:
        with patch("polyflow.engine.executor.asyncio.sleep", new_callable=AsyncMock):
            mock_adapter = AsyncMock()
            mock_adapter.complete = rate_limited
            mock_get.return_value = mock_adapter
            result = await execute_step(step, ctx, config)

    assert result == "success"
    assert call_count == 3


@pytest.mark.asyncio
async def test_parallel_partial_failure_continues(config):
    """With on_error.partial='continue', failed substeps are excluded from output."""
    step = Step(
        id="par", name="Par", type="parallel",
        steps=[
            SubStep(id="ok", model="claude", prompt="test"),
            SubStep(id="fail", model="gemini", prompt="test"),
        ],
        aggregate=AggregateConfig(mode="raw"),
        on_error=OnError(partial="continue"),
    )
    ctx = TemplateContext(input="test")
    call_count = 0

    async def mixed(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "ok output"
        raise RuntimeError("substep failed")

    with patch("polyflow.engine.executor.get_model_adapter") as mock_get:
        mock_adapter = AsyncMock()
        mock_adapter.complete = mixed
        mock_get.return_value = mock_adapter
        result = await execute_parallel(step, ctx, config)

    assert "ok output" in result
    assert "failed" not in result


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
