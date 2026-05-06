from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Sequence


class WorkflowSlashError(ValueError):
    pass


@dataclass(frozen=True)
class WorkflowSlashCommand:
    """Parsed `/workflow ...` command routed to runtime/cli.py argv."""

    argv: list[str]
    mode: str

    def shell_command(self, *, python: str = "python", cli_path: str = "runtime/cli.py") -> str:
        return " ".join(shlex.quote(part) for part in [python, cli_path, *self.argv])


def parse_workflow_slash(text: str | Sequence[str]) -> WorkflowSlashCommand:
    """Route Discord `/workflow` text to runtime CLI argv.

    Supported shapes:
    - `/workflow <自然語言>` -> `run <自然語言>`
    - `/workflow template <name> <key=value...>` -> `run-template <name> --input key=value ...`
    - `/workflow approve <workflow_id> <step_id>` -> `approve <workflow_id> <step_id>`

    Discord interactions may pass only the command body; the `/workflow` prefix is optional.
    """

    tokens = _tokens(text)
    if tokens and tokens[0] == "/workflow":
        tokens = tokens[1:]
    if not tokens:
        raise WorkflowSlashError("/workflow requires a natural-language request or subcommand")

    subcommand = tokens[0]
    if subcommand == "template":
        return _parse_template(tokens[1:])
    if subcommand == "approve":
        return _parse_approve(tokens[1:])

    message = _natural_language_payload(text, tokens)
    return WorkflowSlashCommand(argv=["run", message], mode="natural_language")


def _tokens(text: str | Sequence[str]) -> list[str]:
    if isinstance(text, str):
        try:
            return shlex.split(text)
        except ValueError as exc:
            raise WorkflowSlashError(f"invalid /workflow syntax: {exc}") from exc
    return [str(item) for item in text]


def _natural_language_payload(text: str | Sequence[str], tokens: list[str]) -> str:
    if isinstance(text, str):
        body = text.strip()
        if body.startswith("/workflow"):
            body = body[len("/workflow") :].strip()
        if body:
            return body
    return " ".join(tokens).strip()


def _parse_template(args: list[str]) -> WorkflowSlashCommand:
    if not args:
        raise WorkflowSlashError("/workflow template requires a template name")
    name, *pairs = args
    if not name:
        raise WorkflowSlashError("/workflow template requires a template name")
    invalid = [item for item in pairs if "=" not in item or item.startswith("=")]
    if invalid:
        raise WorkflowSlashError(f"template inputs must be key=value: {', '.join(invalid)}")

    argv = ["run-template", name]
    for pair in pairs:
        argv.extend(["--input", pair])
    return WorkflowSlashCommand(argv=argv, mode="template")


def _parse_approve(args: list[str]) -> WorkflowSlashCommand:
    if len(args) != 2:
        raise WorkflowSlashError("/workflow approve requires workflow_id and step_id")
    return WorkflowSlashCommand(argv=["approve", args[0], args[1]], mode="approve")
