from __future__ import annotations

import csv
import io
import json
import sys
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime
from enum import Enum
from typing import Any

from rich.console import Console
from rich.table import Table

from exit_codes import UsageError

OUTPUT_FORMATS: tuple[str, ...] = ("table", "json", "csv")
EMPTY_CELL = "—"


@dataclass(frozen=True)
class Column:
    key: str
    header: str
    align: str = "left"
    width: int | None = None


def column(key: str, header: str | None = None, *, align: str = "left") -> Column:
    default_header = key.replace("_", " ").strip().capitalize()
    return Column(key=key, header=header or default_header, align=align)


def parse_output(value: str) -> str:
    normalized = (value or "").strip().lower()
    if normalized not in OUTPUT_FORMATS:
        raise UsageError(
            f"unsupported output format: {value!r} (choose from "
            f"{', '.join(OUTPUT_FORMATS)})"
        )
    return normalized


def to_jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if is_dataclass(value) and not isinstance(value, type):
        return {key: to_jsonable(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return value


def cell_text(value: Any) -> str:
    if value is None or value == "":
        return EMPTY_CELL
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%SZ")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return str(value.value)
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def rows_to_json(rows: Iterable[dict[str, Any]]) -> str:
    return json.dumps(
        [to_jsonable(row) for row in rows],
        ensure_ascii=False,
        indent=2,
    )


def rows_to_csv(columns: Sequence[Column], rows: Iterable[dict[str, Any]]) -> str:
    output = io.StringIO(newline="")
    writer = csv.DictWriter(
        output,
        fieldnames=[column.key for column in columns],
        extrasaction="ignore",
        lineterminator="\n",
    )
    writer.writeheader()
    for row in rows:
        writer.writerow(
            {column.key: _csv_value(row.get(column.key)) for column in columns}
        )
    return output.getvalue()


def _csv_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return to_jsonable(value)


def build_table(
    title: str | None,
    columns: Sequence[Column],
    rows: Sequence[dict[str, Any]],
) -> Table:
    table = Table(title=title, show_lines=False)
    for column in columns:
        table.add_column(
            column.header,
            justify="right" if column.align == "right" else "left",
            no_wrap=False,
        )
    for row in rows:
        table.add_row(*(cell_text(row.get(column.key)) for column in columns))
    return table


def emit_rows(
    rows: Sequence[dict[str, Any]],
    columns: Sequence[Column],
    output: str,
    *,
    title: str | None = None,
    empty_message: str | None = None,
    console: Console | None = None,
) -> None:
    stream = console or Console()
    if output == "json":
        print(rows_to_json(rows))
        return
    if output == "csv":
        sys.stdout.write(rows_to_csv(columns, rows))
        return
    if not rows:
        if empty_message:
            stream.print(f"[yellow]{empty_message}[/yellow]")
        return
    stream.print(build_table(title, columns, rows))


def emit_document(payload: Any, output: str, *, title: str | None = None) -> None:
    if output == "json":
        print(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2))
        return
    rows = [
        {"field": key, "value": value} for key, value in to_jsonable(payload).items()
    ]
    table = Table(title=title)
    table.add_column("Field")
    table.add_column("Value")
    for row in rows:
        table.add_row(str(row["field"]), cell_text(row["value"]))
    Console().print(table)
