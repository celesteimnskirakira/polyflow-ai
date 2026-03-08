from __future__ import annotations
import time
import yaml
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from polyflow.schema.workflow import Workflow
from polyflow.engine.template import TemplateContext
from polyflow.engine.executor import execute_step
from polyflow.engine.hitl import prompt_hitl
from polyflow.engine.context_builder import build_context
from polyflow.config import Config, load_config

console = Console()


async def run_workflow(
    workflow_path: Path,
    user_input: str,
    config: Config,
    cwd: Path | None = None,
    show_output: bool = True,
) -> TemplateContext:
    """
    Execute a workflow YAML file.
    Returns the final TemplateContext (contains all step outputs).
    """
    raw = yaml.safe_load(workflow_path.read_text())
    workflow = Workflow.model_validate(raw)

    # Build context string from inject_cwd / inject_files
    context_str = build_context(
        inject_cwd=workflow.context.inject_cwd,
        inject_files=workflow.context.inject_files,
        max_file_size=workflow.context.max_file_size,
        cwd=cwd or workflow_path.parent,
    )

    ctx = TemplateContext(
        input=user_input,
        vars=workflow.vars,
        context_str=context_str,
    )

    console.print(f"\n[bold green]▶ Running:[/bold green] {workflow.name}")
    if workflow.description:
        console.print(f"[dim]{workflow.description}[/dim]")
    console.print()

    for step in workflow.steps:
        t0 = time.monotonic()
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), TimeElapsedColumn(), transient=True) as p:
            task_id = p.add_task(f"[cyan]{step.name}[/cyan]...")
            output = await execute_step(step, ctx, config)
            p.update(task_id, completed=True)
        elapsed = time.monotonic() - t0

        if output is None:
            console.print(f"[yellow]⏭  {step.name} — skipped[/yellow]")
            continue

        console.print(f"[green]✓[/green] {step.name}  [dim]{elapsed:.1f}s[/dim]")
        ctx.step_outputs[step.id] = output

        if show_output:
            preview = output[:400] + ("…" if len(output) > 400 else "")
            console.print(Panel(preview, border_style="dim", padding=(0, 1)))

        # save_to: per-step output saving (future: individual step output config)
        # For now, honour workflow-level output.save_to after the last step.

        if step.hitl:
            result = prompt_hitl(
                message=step.hitl.message,
                options=step.hitl.options,
                content=output if step.hitl.show else "",
            )
            ctx.hitl_choices[step.id] = {"choice": result.choice, "note": result.note}
            if result.choice == "abort":
                console.print("[red]✗ Workflow aborted by user.[/red]")
                return ctx

    # Save final output if configured
    if workflow.output.save_to:
        _save_output(workflow, ctx)

    console.print("\n[bold green]✓ Workflow complete.[/bold green]")
    return ctx


def _save_output(workflow: Workflow, ctx: TemplateContext) -> None:
    """Save workflow output to file based on output config."""
    output_cfg = workflow.output
    save_path = Path(output_cfg.save_to)

    # Collect outputs (all steps, or only those in output.include)
    included_ids = output_cfg.include or list(ctx.step_outputs.keys())
    sections: list[str] = []

    for step_id in included_ids:
        if step_id in ctx.step_outputs:
            sections.append(f"## {step_id}\n\n{ctx.step_outputs[step_id]}")

    content = "\n\n---\n\n".join(sections)

    if output_cfg.format == "json":
        import json
        content = json.dumps(
            {sid: ctx.step_outputs.get(sid) for sid in included_ids},
            indent=2,
            ensure_ascii=False,
        )

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(content, encoding="utf-8")
    console.print(f"[dim]Output saved to {save_path}[/dim]")
