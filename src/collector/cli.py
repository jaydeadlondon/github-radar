from __future__ import annotations
import typer
from rich.console import Console
from version import __version__

app = typer.Typer(
    name="radar",
    help="GitHub Radar — track rising stars on GitHub.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def version() -> None:
    console.print(f"github-radar {__version__}")
