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
    dry_run: bool = False,
) -> TemplateContext:
    """
    Execute a workflow YAML file.
    Returns the final TemplateContext (contains all step outputs).
    """
    from rich.syntax import Syntax

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

    _workflow_start = time.monotonic()

    if dry_run:
        console.print(f"\n[bold yellow]◎ Dry run:[/bold yellow] {workflow.name}  [dim](no API calls)[/dim]")
    else:
        console.print(f"\n[bold green]▶ Running:[/bold green] {workflow.name}")
    if workflow.description:
        console.print(f"[dim]{workflow.description}[/dim]")
    console.print()

    from polyflow.engine.template import render

    for step in workflow.steps:
        if dry_run:
            # Render prompt but skip API call
            from polyflow.engine.executor import _evaluate_condition
            if step.condition and not _evaluate_condition(step.condition, ctx):
                console.print(f"[yellow]⏭  {step.name} — would be skipped (condition false)[/yellow]")
                continue
            if step.type == "parallel":
                console.print(f"[cyan]◎[/cyan] {step.name}  [dim](parallel × {len(step.steps)})[/dim]")
                for sub in step.steps:
                    rendered = render(sub.prompt, ctx)
                    console.print(Panel(
                        Syntax(rendered, "text", theme="monokai", padding=(0, 1)),
                        title=f"[dim]{sub.id} ({sub.model})[/dim]",
                        border_style="dim",
                    ))
            else:
                rendered = render(step.prompt or "", ctx)
                console.print(f"[cyan]◎[/cyan] {step.name}  [dim]({step.model})[/dim]")
                console.print(Panel(
                    Syntax(rendered, "text", theme="monokai", padding=(0, 1)),
                    title=f"[dim]{step.id} — prompt preview[/dim]",
                    border_style="dim",
                ))
            continue

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

        # Show preview only when HITL won't already display the content
        if show_output and not (step.hitl and step.hitl.show):
            preview = output[:400] + ("…" if len(output) > 400 else "")
            console.print(Panel(preview, border_style="dim", padding=(0, 1)))

        if step.hitl:
            # Cap content shown in HITL panel to avoid overwhelming the terminal
            hitl_content = ""
            if step.hitl.show:
                hitl_content = output[:2000] + ("\n\n[…truncated]" if len(output) > 2000 else "")
            result = prompt_hitl(
                message=step.hitl.message,
                options=step.hitl.options,
                content=hitl_content,
            )
            ctx.hitl_choices[step.id] = {"choice": result.choice, "note": result.note}
            if result.choice == "abort":
                console.print("[red]✗ Workflow aborted by user.[/red]")
                return ctx

    if dry_run:
        console.print("\n[bold yellow]◎ Dry run complete.[/bold yellow]  No API calls were made.\n")
        return ctx

    # Save final output if configured
    if workflow.output.save_to:
        _save_output(workflow, ctx)

    total_elapsed = time.monotonic() - _workflow_start
    _print_run_summary(workflow, ctx, total_elapsed)
    return ctx


def _print_run_summary(workflow: Workflow, ctx: TemplateContext, total_elapsed: float) -> None:
    """Print a brief summary of which steps produced output and the total run time."""
    step_count = len(ctx.step_outputs)
    if step_count == 0:
        console.print("\n[bold green]✓ Workflow complete.[/bold green]  [dim](no step output)[/dim]")
        return

    step_ids = list(ctx.step_outputs.keys())
    # Show short preview of each step output length
    parts = [f"[bold]{sid}[/bold] ({len(ctx.step_outputs[sid])} chars)" for sid in step_ids]
    summary = ", ".join(parts)

    console.print(
        f"\n[bold green]✓ Workflow complete.[/bold green]  "
        f"[dim]{step_count} step{'s' if step_count != 1 else ''} · "
        f"{total_elapsed:.1f}s total[/dim]"
    )
    console.print(f"  [dim]Outputs: {summary}[/dim]")


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
            {sid: ctx.step_outputs[sid] for sid in included_ids if sid in ctx.step_outputs},
            indent=2,
            ensure_ascii=False,
        )

    save_path.parent.mkdir(parents=True, exist_ok=True)
    save_path.write_text(content, encoding="utf-8")
    console.print(f"[dim]Output saved to {save_path}[/dim]")
