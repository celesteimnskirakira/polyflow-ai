"""
Polyflow CLI — multi-model AI workflow engine.

Key commands:
  polyflow doctor          Check your setup
  polyflow list            Browse available workflows
  polyflow run <workflow>  Run a workflow (by name or file path)
  polyflow new "..."       Generate a workflow from a description
  polyflow validate <file> Validate a workflow YAML
  polyflow schema          Show the YAML schema reference
  polyflow pull <name>     Pull a workflow from the community registry
  polyflow search          List community workflows
  polyflow init            Configure API keys
"""
from __future__ import annotations
import asyncio
import os
import sys
import time
from pathlib import Path

import click
from rich.console import Console
from rich.prompt import Prompt
from rich.table import Table
from rich import box

from polyflow import __version__
from polyflow.config import Config, save_config, load_config

console = Console()
err_console = Console(stderr=True)

# ─── Workflow resolution ──────────────────────────────────────────────────────

def _resolve_workflow(ref: str) -> Path:
    """
    Resolve a workflow reference to a Path.
    Accepts: file path, name (with or without .yaml),
             name from workflows/examples/, ~/.polyflow/workflows/.
    """
    candidate = Path(ref)

    # 1. Exact path
    if candidate.exists() and candidate.is_file():
        return candidate

    # 2. Add .yaml extension
    with_yaml = Path(ref + ".yaml") if not ref.endswith(".yaml") else candidate
    if with_yaml.exists():
        return with_yaml

    # 3. Search in well-known directories
    search_dirs = [
        Path("workflows/examples"),
        Path("workflows"),
        Path.home() / ".polyflow" / "workflows",
    ]
    # Also try relative to the polyflow package's own examples
    _pkg_examples = Path(__file__).parent.parent.parent.parent / "workflows" / "examples"
    if _pkg_examples.is_dir():
        search_dirs.append(_pkg_examples)

    name = Path(ref).stem  # strip any extension
    for d in search_dirs:
        for suffix in ("", ".yaml"):
            p = d / (name + suffix)
            if p.exists():
                return p

    raise FileNotFoundError(
        f"Workflow '{ref}' not found.\n"
        f"  • Run [bold]polyflow list[/bold] to see available workflows\n"
        f"  • Run [bold]polyflow pull {ref}[/bold] to download from registry\n"
        f"  • Run [bold]polyflow new \"{ref}\"[/bold] to generate one"
    )


def _list_local_workflows() -> list[tuple[str, str, str]]:
    """Return list of (name, description, path) for local workflows."""
    results = []
    search_dirs = [
        Path("workflows/examples"),
        Path("workflows"),
        Path.home() / ".polyflow" / "workflows",
    ]
    _pkg_examples = Path(__file__).parent.parent.parent.parent / "workflows" / "examples"
    if _pkg_examples.is_dir():
        search_dirs.insert(0, _pkg_examples)

    seen = set()
    for d in search_dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.yaml")):
            if p.name in seen:
                continue
            seen.add(p.name)
            try:
                import yaml
                raw = yaml.safe_load(p.read_text())
                desc = raw.get("description", "")
                tags = raw.get("tags", [])
                results.append((p.stem, desc, str(p), tags))
            except Exception:
                results.append((p.stem, "", str(p), []))
    return results


# ─── Commands ─────────────────────────────────────────────────────────────────

@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(__version__, prog_name="polyflow")
def main():
    """
    Polyflow — define, run and share multi-model AI workflows in YAML.

    \b
    Get started in 30 seconds:
      export OPENROUTER_API_KEY=sk-or-...
      polyflow list
      polyflow run code-review-multi-model -i "$(git diff HEAD~1)"

    \b
    Docs & examples: https://github.com/celesteimnskirakira/polyflow
    """
    pass


@main.command()
def doctor():
    """Check your environment and API key setup."""
    import httpx

    console.print("\n[bold]Polyflow Doctor[/bold] — system check\n")
    ok = True

    def check(label: str, status: bool, note: str = "", fix: str = ""):
        icon = "[green]✓[/green]" if status else "[red]✗[/red]"
        line = f"  {icon}  {label}"
        if note:
            line += f"  [dim]{note}[/dim]"
        console.print(line)
        if not status and fix:
            console.print(f"       [yellow]→ {fix}[/yellow]")
        return status

    # Python version
    import sys
    py_ok = sys.version_info >= (3, 11)
    check("Python", py_ok, f"{sys.version.split()[0]}", "Upgrade to Python 3.11+")
    ok = ok and py_ok

    # Polyflow version
    check("Polyflow", True, f"v{__version__}")

    # API keys
    console.print()
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    ant_key = os.environ.get("ANTHROPIC_API_KEY", "")
    gem_key = os.environ.get("GEMINI_API_KEY", "")
    oai_key = os.environ.get("OPENAI_API_KEY", "")

    if or_key:
        check("OPENROUTER_API_KEY", True, f"{or_key[:12]}... (covers all models ✨)")
    else:
        check(
            "OPENROUTER_API_KEY", False,
            "not set",
            "export OPENROUTER_API_KEY=sk-or-... (get one at openrouter.ai)"
        )
        ok = False
        # Fall back to individual keys
        check("ANTHROPIC_API_KEY", bool(ant_key), "set" if ant_key else "not set")
        check("GEMINI_API_KEY",    bool(gem_key), "set" if gem_key else "not set")
        check("OPENAI_API_KEY",    bool(oai_key), "set" if oai_key else "not set")
        if not any([ant_key, gem_key, oai_key]):
            ok = False

    # Config file
    console.print()
    cfg_path = Path.home() / ".polyflow" / "config.yaml"
    check("Config file", cfg_path.exists(), str(cfg_path) if cfg_path.exists() else "not found (using env vars)")

    # Network + OpenRouter reachability (quick check)
    console.print()
    try:
        r = httpx.get("https://openrouter.ai/api/v1/models", timeout=5,
                      headers={"Authorization": f"Bearer {or_key}"} if or_key else {})
        reachable = r.status_code in (200, 401)  # 401 = reachable but key invalid
        check("OpenRouter API", reachable, "reachable" if reachable else f"HTTP {r.status_code}")
    except Exception as e:
        check("OpenRouter API", False, "unreachable", "Check network connection")

    # Local workflows
    console.print()
    workflows = _list_local_workflows()
    check("Local workflows", len(workflows) > 0, f"{len(workflows)} found" if workflows else "none found")

    console.print()
    if ok:
        console.print("[bold green]✓ All good! Ready to run.[/bold green]")
        console.print("\n  Try: [bold]polyflow list[/bold]")
    else:
        console.print("[bold yellow]⚠ Fix the issues above, then re-run polyflow doctor[/bold yellow]")
    console.print()


@main.command("list")
@click.option("--tag", "-t", default=None, help="Filter by tag")
def list_workflows(tag: str | None):
    """List available workflows (local + examples)."""
    workflows = _list_local_workflows()

    if not workflows:
        console.print("[yellow]No workflows found.[/yellow]")
        console.print("  Run [bold]polyflow search[/bold] to browse community workflows")
        console.print("  Run [bold]polyflow pull <name>[/bold] to download one")
        return

    if tag:
        workflows = [(n, d, p, t) for n, d, p, t in workflows if tag in t]
        if not workflows:
            console.print(f"[yellow]No workflows with tag '{tag}'.[/yellow]")
            return

    table = Table(box=box.ROUNDED, show_header=True, header_style="bold cyan", padding=(0, 1))
    table.add_column("Name", style="bold white", min_width=28)
    table.add_column("Description", style="dim")
    table.add_column("Tags", style="cyan", min_width=20)

    for name, desc, path, tags in workflows:
        short_desc = (desc[:60] + "…") if len(desc) > 61 else desc
        tags_str = " ".join(f"[dim]{t}[/dim]" for t in tags[:4])
        table.add_row(name, short_desc, tags_str)

    console.print(f"\n  [bold]{len(workflows)} workflows available[/bold]\n")
    console.print(table)
    console.print()
    console.print("  Run: [bold]polyflow run <name> -i \"your input\"[/bold]")
    if tag is None:
        console.print("  Filter: [bold]polyflow list --tag security[/bold]")
    console.print()


@main.command()
@click.argument("workflow_ref")
@click.option("--input", "-i", "user_input", default="", help="Input to pass to the workflow")
@click.option("--output", "-o", default=None, help="Save final output to a file")
@click.option("--show-output/--no-show-output", default=True, help="Preview step outputs")
def run(workflow_ref: str, user_input: str, output: str | None, show_output: bool):
    """
    Run a workflow by name or file path.

    \b
    Examples:
      polyflow run code-review-multi-model -i "$(git diff HEAD~1)"
      polyflow run ./my-flow.yaml -i "build a todo API"
      polyflow run bug-triage -i "TypeError in auth.py line 42"
    """
    from polyflow.engine.runner import run_workflow

    try:
        workflow_path = _resolve_workflow(workflow_ref)
    except FileNotFoundError as e:
        err_console.print(f"[red]✗ {e}[/red]")
        sys.exit(1)

    if not user_input:
        user_input = click.prompt("  Workflow input")

    config = load_config()
    if not config.uses_openrouter and not config.api_keys:
        err_console.print(
            "[yellow]⚠ No API keys found.[/yellow] "
            "Set [bold]OPENROUTER_API_KEY[/bold] or run [bold]polyflow init[/bold]."
        )
        sys.exit(1)

    ctx = asyncio.run(run_workflow(workflow_path, user_input, config, show_output=show_output))

    if output and ctx.step_outputs:
        last_output = list(ctx.step_outputs.values())[-1]
        Path(output).write_text(last_output, encoding="utf-8")
        console.print(f"[dim]Output written to {output}[/dim]")


@main.command()
@click.argument("workflow_file", type=click.Path(exists=True, path_type=Path))
def validate(workflow_file: Path):
    """
    Validate a workflow YAML against the schema.

    \b
    Examples:
      polyflow validate my-flow.yaml
      polyflow validate workflows/examples/code-review-multi-model.yaml
    """
    import yaml
    from pydantic import ValidationError
    from polyflow.schema.workflow import Workflow

    try:
        raw = yaml.safe_load(workflow_file.read_text())
        wf = Workflow.model_validate(raw)
        console.print(f"\n  [green]✓[/green] [bold]{wf.name}[/bold] — valid ({len(wf.steps)} steps)\n")
        for step in wf.steps:
            if step.type == "parallel":
                stype = f"[dim]parallel[/dim] × {len(step.steps)}"
            else:
                stype = f"[dim]{step.model}[/dim]"
            hitl = " [yellow]+hitl[/yellow]" if step.hitl else ""
            cond = " [blue]+if[/blue]" if step.condition else ""
            console.print(f"    [dim]{step.id:28}[/dim] {stype}{hitl}{cond}")
        console.print()
    except ValidationError as e:
        err_console.print(f"\n  [red]✗ Validation failed:[/red] {workflow_file.name}\n")
        for error in e.errors():
            loc = " → ".join(str(x) for x in error["loc"])
            err_console.print(f"  [red]  {loc}[/red]")
            err_console.print(f"      {error['msg']}\n")
        sys.exit(1)
    except Exception as e:
        err_console.print(f"\n  [red]✗ Error:[/red] {e}\n")
        sys.exit(1)


@main.command()
def schema():
    """Show the Polyflow YAML schema reference."""
    from rich.markdown import Markdown

    md = Markdown(_SCHEMA_REFERENCE)
    console.print()
    console.print(md)
    console.print()


@main.command()
@click.argument("description")
@click.option("--output", "-o", default="workflow.yaml", help="Output file path")
def new(description: str, output: str):
    """
    Generate a workflow YAML from a natural language description.

    \b
    Examples:
      polyflow new "Claude writes a plan, Gemini reviews it, I approve" -o plan-review.yaml
      polyflow new "Security audit of Python code with OWASP checklist" -o sec-audit.yaml
    """
    import yaml
    from pydantic import ValidationError
    from polyflow.schema.workflow import Workflow

    config = load_config()

    console.print(f"\n  [dim]Generating workflow: {description[:60]}...[/dim]")

    with console.status("[cyan]Generating workflow YAML...[/cyan]"):
        if config.uses_openrouter:
            from openai import OpenAI
            from polyflow.models.openrouter import OPENROUTER_BASE_URL
            client_or = OpenAI(api_key=config.openrouter_api_key, base_url=OPENROUTER_BASE_URL)
            yaml_content = client_or.chat.completions.create(
                model="anthropic/claude-sonnet-4-5",
                max_tokens=2048,
                messages=[
                    {"role": "system", "content": _NEW_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Generate a Polyflow workflow for:\n{description}"},
                ],
            ).choices[0].message.content
        else:
            import anthropic
            api_key = config.get_api_key("claude")
            client_ant = anthropic.Anthropic(api_key=api_key)
            yaml_content = client_ant.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=_NEW_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": f"Generate a Polyflow workflow for:\n{description}"}],
            ).content[0].text

    # Strip accidental markdown fences
    yaml_content = yaml_content.strip()
    if yaml_content.startswith("```"):
        lines = yaml_content.splitlines()
        yaml_content = "\n".join(l for l in lines if not l.startswith("```")).strip()

    # Validate before saving
    try:
        raw = yaml.safe_load(yaml_content)
        wf = Workflow.model_validate(raw)
        Path(output).write_text(yaml_content)
        console.print(f"\n  [green]✓[/green] Workflow [bold]{wf.name}[/bold] saved to [bold]{output}[/bold]")
        console.print(f"    {len(wf.steps)} steps: {', '.join(s.id for s in wf.steps)}\n")
        console.print(f"  Run: [bold]polyflow run {output} -i \"your input\"[/bold]")
        console.print(f"  Edit: [bold]polyflow validate {output}[/bold]\n")
    except (ValidationError, Exception) as e:
        console.print(f"\n  [red]✗ Generated YAML failed validation:[/red] {e}")
        Path(output).write_text(yaml_content)
        console.print(f"  [yellow]Raw output saved to {output} — edit and re-validate.[/yellow]\n")


@main.command()
def init():
    """
    Configure API keys for Polyflow.

    \b
    Tip: Set OPENROUTER_API_KEY in your shell to skip this step.
    OpenRouter covers Claude, Gemini, and GPT-4 with a single key.
    Get a key at: https://openrouter.ai
    """
    console.print("\n  [bold]Polyflow Setup[/bold] — configure API keys\n")

    if os.environ.get("OPENROUTER_API_KEY"):
        console.print("  [green]✓[/green] OPENROUTER_API_KEY already set in environment\n")
        console.print("  You're ready to run! Try: [bold]polyflow list[/bold]\n")
        return

    console.print("  [bold]Option 1 (recommended):[/bold] OpenRouter — one key, all models")
    console.print("  Get a free key at [link=https://openrouter.ai]https://openrouter.ai[/link]\n")
    or_key = Prompt.ask("  OpenRouter API key (Enter to skip)", default="")
    if or_key:
        cfg = Config(openrouter_api_key=or_key)
        save_config(cfg)
        console.print("\n  [green]✓[/green] Saved to ~/.polyflow/config.yaml")
        console.print("  Run: [bold]polyflow doctor[/bold] to verify setup\n")
        return

    console.print("\n  [bold]Option 2:[/bold] Individual model keys\n")
    keys = {}
    for model, label, hint in [
        ("claude", "Anthropic (Claude)", "sk-ant-..."),
        ("gemini", "Google (Gemini)", "AIza..."),
        ("gpt-4", "OpenAI (GPT-4)", "sk-..."),
    ]:
        key = Prompt.ask(f"  {label} [{hint}] (Enter to skip)", default="")
        if key:
            keys[model] = key

    cfg = Config(api_keys=keys)
    save_config(cfg)
    console.print("\n  [green]✓[/green] Saved to ~/.polyflow/config.yaml\n")


@main.command()
@click.argument("name")
@click.option("--output", "-o", default=None, help="Save path (default: <name>.yaml)")
def pull(name: str, output: str):
    """
    Pull a workflow from the community registry.

    \b
    Examples:
      polyflow pull code-review-multi-model
      polyflow pull security-audit -o my-audit.yaml
    """
    from polyflow.registry.client import pull_workflow
    dest = Path(output or f"{name}.yaml")
    try:
        with console.status(f"[cyan]Pulling {name}...[/cyan]"):
            asyncio.run(pull_workflow(name, dest))
        console.print(f"\n  [green]✓[/green] Saved to [bold]{dest}[/bold]")
        console.print(f"  Validate: [bold]polyflow validate {dest}[/bold]")
        console.print(f"  Run:      [bold]polyflow run {name} -i \"your input\"[/bold]\n")
    except FileNotFoundError as e:
        console.print(f"\n  [red]✗[/red] {e}\n")
        sys.exit(1)


@main.command()
def search():
    """List available workflows in the community registry."""
    from polyflow.registry.client import list_workflows
    try:
        with console.status("[cyan]Fetching registry...[/cyan]"):
            workflows = asyncio.run(list_workflows())
        console.print(f"\n  [bold]{len(workflows)} community workflows:[/bold]\n")
        for name in workflows:
            console.print(f"  • {name}")
        console.print(f"\n  Install: [bold]polyflow pull <name>[/bold]\n")
    except Exception as e:
        console.print(f"\n  [red]Registry unavailable:[/red] {e}")
        console.print("  → https://github.com/celesteimnskirakira/polyflow\n")


@main.command()
@click.option("--shell", type=click.Choice(["bash", "zsh", "fish"]), default=None)
def completion(shell: str | None):
    """
    Print shell completion setup instructions.

    \b
    Examples:
      polyflow completion --shell zsh
      polyflow completion --shell bash
    """
    detected = os.environ.get("SHELL", "").split("/")[-1]
    s = shell or detected or "bash"

    instructions = {
        "bash": (
            'eval "$(_POLYFLOW_COMPLETE=bash_source polyflow)"\n\n'
            "Add to ~/.bashrc:\n"
            '  eval "$(_POLYFLOW_COMPLETE=bash_source polyflow)"'
        ),
        "zsh": (
            'eval "$(_POLYFLOW_COMPLETE=zsh_source polyflow)"\n\n'
            "Add to ~/.zshrc:\n"
            '  eval "$(_POLYFLOW_COMPLETE=zsh_source polyflow)"'
        ),
        "fish": (
            "_POLYFLOW_COMPLETE=fish_source polyflow | source\n\n"
            "Add to ~/.config/fish/completions/polyflow.fish:\n"
            "  _POLYFLOW_COMPLETE=fish_source polyflow | source"
        ),
    }
    console.print(f"\n  [bold]Shell completion ({s}):[/bold]\n")
    console.print(f"  {instructions.get(s, instructions['bash'])}\n")


# ─── Schema reference (inline, accessible via `polyflow schema`) ──────────────

_SCHEMA_REFERENCE = """\
# Polyflow YAML Schema Reference

## Minimal workflow

```yaml
name: my-workflow          # required
version: "1.0"             # optional, default "1.0"
description: "..."         # optional, shown at runtime

steps:
  - id: step1              # unique identifier (used in {{steps.step1.output}})
    name: My Step          # display name shown in terminal
    model: claude          # claude | gemini | gpt-4
    prompt: "..."          # prompt template (supports {{...}} expressions)
```

## Template expressions

| Expression | Description |
|---|---|
| `{{input}}` | User's input passed with `-i` flag |
| `{{steps.step_id.output}}` | Output from a previous step |
| `{{hitl.step_id.choice}}` | User's HITL choice (continue/abort/revise) |
| `{{hitl.step_id.note}}` | Revision notes from HITL |
| `{{vars.key}}` | Workflow variable |
| `{{context}}` | Injected file context |
| `{{a \\| b}}` | Pipe fallback — use `b` if `a` is empty |

## Parallel steps

```yaml
- id: validate
  name: Cross-Validate
  type: parallel
  steps:
    - id: gemini_check
      model: gemini
      prompt: "Review: {{steps.generate.output}}"
    - id: gpt4_check
      model: gpt-4
      prompt: "Review: {{steps.generate.output}}"
  aggregate:
    mode: diff          # diff | vote | summary | raw
    model: claude       # optional: model to synthesize results
```

## Human-in-the-loop (HITL)

```yaml
hitl:
  message: "Review the output. Continue?"
  options: [continue, abort, revise]   # any words you want
  show: diff                           # diff | summary | raw | (omit to hide)
  timeout: 10m
```

Use the choice in downstream steps:
```yaml
condition: "{{hitl.review.choice}} != 'abort'"
```

## Conditional execution

```yaml
condition: "{{hitl.review.choice}} == 'revise'"
```

Evaluates `LHS == RHS` or `LHS != RHS` (no code execution, safe).

## Error handling

```yaml
on_error:
  retry: 2                  # retry attempts (default 0)
  fallback: continue        # abort | continue | skip
  partial: continue         # parallel: continue if one sub-step fails
```

## Output

```yaml
output:
  format: markdown          # markdown | json | text
  save_to: output/result.md
  include: [step1, step3]   # specific steps to include (default: all)
```

## Context injection

```yaml
context:
  inject_cwd: true          # inject project file tree
  inject_files:             # inject specific files
    - "src/**/*.py"
    - "README.md"
  max_file_size: 50kb
```

## Variables

```yaml
vars:
  language: Python
  style: concise

steps:
  - prompt: "Write in {{vars.language}}. Style: {{vars.style}}."
```

## Step timeout

```yaml
- id: slow_step
  timeout: 2m               # 30s | 2m | 120 (seconds)
```

## Available models

| Alias | Model |
|---|---|
| `claude` | Claude Sonnet (via Anthropic or OpenRouter) |
| `gemini` | Gemini 2.0 Flash (via Google or OpenRouter) |
| `gpt-4` | GPT-4o (via OpenAI or OpenRouter) |
"""

_NEW_SYSTEM_PROMPT = """\
You are a Polyflow workflow generator. Convert natural language descriptions \
into valid Polyflow YAML workflows.

Rules:
- Output ONLY raw YAML. No markdown fences, no explanation.
- Use models: claude, gemini, gpt-4
- Include HITL checkpoints at key decision points
- Use {{input}} for the user's input
- Use {{steps.step_id.output}} to reference previous step outputs
- Make prompts detailed and specific

Schema quick reference:
  name: str (required)
  version: "1.0"
  steps:
    - id: str
      name: str
      model: claude|gemini|gpt-4
      prompt: str (supports {{...}} templates)
      type: sequential|parallel
      hitl: {message: str, options: list, show: diff|summary|raw}
      condition: "{{hitl.x.choice}} == 'value'"
      on_error: {retry: int, fallback: abort|continue}
"""
