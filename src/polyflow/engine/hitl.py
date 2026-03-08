from dataclasses import dataclass
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

console = Console()


@dataclass
class HitlResult:
    choice: str
    note: str = ""


_SHORTCUTS = {"c": "continue", "a": "abort", "r": "revise", "s": "skip"}


def prompt_hitl(message: str, options: list[str], content: str = "") -> HitlResult:
    """Display model output and prompt for human confirmation."""
    if content:
        console.print(Panel(content, title="[bold cyan]Model Output[/bold cyan]", expand=False))

    shortcuts = {k: v for k, v in _SHORTCUTS.items() if v in options}
    opts_display = " / ".join(
        f"[bold]{o[0]}[/bold]{o[1:]} ({o[0]})" for o in options
    )
    console.print(f"\n[yellow]{message}[/yellow]")
    console.print(f"Options: {opts_display}")

    while True:
        raw = input("> ").strip().lower()
        choice = shortcuts.get(raw, raw)
        if choice in options:
            break
        console.print(f"[red]Invalid choice. Enter one of: {', '.join(options)}[/red]")

    note = ""
    if choice == "revise":
        note = input("Your revision notes: ").strip()

    return HitlResult(choice=choice, note=note)
