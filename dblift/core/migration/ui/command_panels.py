"""Rich command panels, imported only when command output is rendered."""

from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from rich.panel import Panel
    from rich.text import Text


def props_text(*lines: str) -> "Text":
    """Style property names in the command header."""
    from rich.text import Text

    body = Text()
    for i, line in enumerate(lines):
        line = str(line) if line is not None else ""
        if ": " in line:
            key, _, val = line.partition(": ")
            body.append(key + ": ", style="bold")
            body.append(val)
        else:
            body.append(line)
        if i < len(lines) - 1:
            body.append("\n")
    return body


def render_main_header_panel(raw_header: str) -> str:
    """Render the application banner as a Rich panel string."""
    from rich import box
    from rich.panel import Panel

    from dblift.core.logger.console import render_panel_to_str

    skip = {"DBLIFT DATABASE MIGRATION LOG"}
    body_lines = [
        line
        for line in raw_header.splitlines()
        if line and not line.startswith("=") and not line.startswith("-") and line not in skip
    ]
    return render_panel_to_str(
        Panel(
            "\n".join(body_lines), title="DBLIFT DATABASE MIGRATION LOG", box=box.HEAVY, expand=True
        ),
        width=80,
    )


def build_footer_panel(
    command_name: str,
    success: bool,
    execution_time: str,
    error_message: Optional[str] = None,
    schema_version: Optional[str] = None,
    applied_scripts: Optional[List[Any]] = None,
) -> "Panel":
    """Build the command completion panel."""
    from rich import box
    from rich.panel import Panel
    from rich.text import Text

    status_style = {"SUCCESS": "bold green", "WARNING": "yellow", "FAILED": "bold red"}
    title = "SUCCESS" if success else "FAILED"
    border_style = status_style.get(title, "default")
    status_msg = (
        f"Command {command_name.upper()} completed successfully (Execution time: {execution_time})"
        if success
        else f"Command {command_name.upper()} failed (Execution time: {execution_time})"
    )

    body = Text()
    if applied_scripts:
        for script in applied_scripts:
            body.append(f"  - {script}\n")
    body.append(str(status_msg))
    if not success and error_message:
        body.append("\n")
        body.append("Error: ", style="bold")
        fmt = str(error_message).rstrip()
        if "\n" in fmt:
            body.append("\n" + "\n".join("  " + ln for ln in fmt.splitlines()))
        else:
            body.append(fmt)
    if schema_version:
        body.append("\n")
        body.append("Schema Version: ", style="bold")
        body.append(str(schema_version))

    return Panel(body, title=title, box=box.HEAVY, border_style=border_style, expand=True)


def build_command_header_panel(
    command_name: str,
    filters: Optional[List[str]] = None,
    schema_version: Optional[str] = None,
    database_url: Optional[str] = None,
    connection_info: Optional[str] = None,
    database_name: Optional[str] = None,
    schema_name: Optional[str] = None,
    database_config: Any = None,
) -> "Panel":
    """Build the command header panel with database details."""
    from rich import box
    from rich.panel import Panel

    lines: List[str] = []
    if connection_info:
        lines.append(connection_info)

    if database_name:
        lines.append(f"Database: {database_name}")
    elif database_config is not None:
        db_name = getattr(database_config, "database_name", None) or getattr(
            database_config, "database", None
        )
        if db_name:
            lines.append(f"Database: {db_name}")

    if schema_name:
        lines.append(f"Schema: {schema_name}")
    elif database_config is not None:
        schema = getattr(database_config, "schema", None)
        if schema:
            lines.append(f"Schema: {schema}")

    lines.append(f"Schema Version: {schema_version or '<none>'}")
    lines.append(f"Database URL: {database_url or '<not available>'}")
    if filters:
        lines.append(f"Filtering Options: {' '.join(filters)}")

    return Panel(
        props_text(*lines),
        title=f"DBLIFT COMMAND: {command_name.upper()}",
        box=box.HEAVY,
        expand=True,
    )
