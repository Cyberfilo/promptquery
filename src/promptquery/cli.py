from __future__ import annotations

import sys

import click
from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console

from . import __version__
from .db import Database
from .llm import LLMError, extract_sql, make_client
from .prompts import build_system_prompt
from .render import render_results, render_sql
from .retrieval import TfIdfRetriever, expand_via_fks
from .safety import UnsafeQuery, validate_select_only
from .schema import introspect


@click.command(context_settings={"help_option_names": ["-h", "--help"]})
@click.argument("dsn", required=True)
@click.option(
    "--model",
    default=None,
    help="LLM model (e.g. claude-sonnet-4-6, gpt-4o, anthropic/claude-opus-4-7).",
)
@click.option(
    "--top-k",
    default=10,
    show_default=True,
    help="Number of tables to retrieve by relevance before FK expansion.",
)
@click.option(
    "--max-tables",
    default=20,
    show_default=True,
    help="Maximum tables sent to the LLM after FK expansion.",
)
@click.option(
    "-y",
    "--yes",
    is_flag=True,
    help="Skip the confirmation prompt and execute generated SQL immediately.",
)
@click.version_option(__version__, prog_name="promptquery")
def main(dsn: str, model: str | None, top_k: int, max_tables: int, yes: bool) -> None:
    """PromptQuery — natural-language SQL for Postgres.

    DSN is a libpq connection string, e.g. postgresql://user:pass@host/db.
    """
    console = Console()

    try:
        llm = make_client(model)
    except LLMError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)

    console.print(f"[dim]Connecting to[/dim] {_redact(dsn)} [dim]...[/dim]")
    try:
        db_ctx = Database(dsn).__enter__()
    except Exception as e:
        console.print(f"[red]Connection failed:[/red] {e}")
        sys.exit(1)

    try:
        console.print("[dim]Introspecting schema...[/dim]")
        schema = introspect(db_ctx)
        if not schema.tables:
            console.print("[yellow]No tables found in this database.[/yellow]")
            return
        console.print(f"[green]✓[/green] {len(schema.tables)} tables found "
                      f"[dim](LLM: {llm.name}/{llm.model})[/dim]")

        retriever = TfIdfRetriever(schema)
        session: PromptSession[str] = PromptSession(history=InMemoryHistory())

        console.print(
            "\n[bold]PromptQuery[/bold] — ask a question in plain English, "
            "or type [bold]exit[/bold] to quit.\n"
        )

        while True:
            try:
                question = session.prompt("? ").strip()
            except (KeyboardInterrupt, EOFError):
                console.print("\n[dim]bye[/dim]")
                break
            if not question:
                continue
            if question.lower() in {"exit", "quit", r"\q"}:
                break

            ranked = retriever.rank(question, top_k=top_k)
            seed = [t for t, score in ranked if score > 0] or [t for t, _ in ranked[:3]]
            relevant = expand_via_fks(schema, seed, max_total=max_tables)

            preview = ", ".join(t.qualified_name for t in relevant[:5])
            suffix = "..." if len(relevant) > 5 else ""
            console.print(
                f"[dim]Using {len(relevant)} tables: {preview}{suffix}[/dim]"
            )

            system_prompt = build_system_prompt(relevant)

            try:
                console.print("[dim]Generating SQL...[/dim]")
                raw = llm.generate(system_prompt, question)
            except Exception as e:
                console.print(f"[red]LLM error:[/red] {e}")
                continue

            sql = extract_sql(raw)
            if not sql:
                console.print("[red]LLM returned an empty response.[/red]")
                continue

            try:
                validate_select_only(sql)
            except UnsafeQuery as e:
                console.print(f"[red]Refusing to run query:[/red] {e}")
                render_sql(console, sql)
                continue

            render_sql(console, sql)

            if not yes:
                try:
                    answer = session.prompt("Run? [y/N] ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    console.print()
                    continue
                if answer not in {"y", "yes"}:
                    console.print("[dim]Skipped.[/dim]\n")
                    continue

            try:
                cols, rows = db_ctx.execute(sql)
            except Exception as e:
                console.print(f"[red]Query error:[/red] {e}\n")
                continue

            render_results(console, cols, rows)
            console.print()
    finally:
        db_ctx.close()


def _redact(dsn: str) -> str:
    if "://" not in dsn:
        return dsn
    scheme, _, rest = dsn.partition("://")
    if "@" in rest:
        creds, _, host = rest.partition("@")
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return dsn


if __name__ == "__main__":
    main()
