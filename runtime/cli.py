from __future__ import annotations

import argparse
import json
from typing import Any

try:
    from runtime.discord_slash import WorkflowSlashError, parse_workflow_slash
    from runtime.orchestrator import WorkflowOrchestrator, demo_llm
    from runtime.templates import TemplateError, edit_template, install_template
except ModuleNotFoundError:
    from discord_slash import WorkflowSlashError, parse_workflow_slash
    from orchestrator import WorkflowOrchestrator, demo_llm
    from templates import TemplateError, edit_template, install_template


def _parse_kv(values: list[str]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"invalid --input value, expected key=value: {item}")
        key, value = item.split("=", 1)
        output[key] = value
    return output


def _parse_set(values: list[str]) -> dict[str, Any]:
    updates = _parse_kv(values)
    allowed = {"description", "summary"}
    invalid = sorted(set(updates) - allowed)
    if invalid:
        raise SystemExit(f"invalid --set key(s): {', '.join(invalid)}; allowed: description, summary")
    return updates


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermes-workflow")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run a natural-language workflow message")
    run.add_argument("message")

    slash = sub.add_parser("slash", help="route a Discord /workflow command body")
    slash.add_argument("message")

    run_template = sub.add_parser("run-template", help="run a reusable workflow template")
    run_template.add_argument("template")
    run_template.add_argument("--input", action="append", default=[], help="template input as key=value")

    sub.add_parser("list", help="list workflow states")
    sub.add_parser("templates", help="list workflow templates")

    install = sub.add_parser("install", help="install a workflow template from a local path or URL")
    install.add_argument("source")
    install.add_argument("--name")
    install.add_argument("--overwrite", action="store_true")

    edit = sub.add_parser("edit", help="edit workflow template metadata")
    edit.add_argument("template")
    edit.add_argument("--set", action="append", default=[], help="metadata update as key=value; supports description/summary")

    resume = sub.add_parser("resume", help="resume latest or selected workflow")
    resume.add_argument("workflow_id", nargs="?")

    approve = sub.add_parser("approve", help="approve a side-effect step and resume")
    approve.add_argument("workflow_id")
    approve.add_argument("step_id")

    args = parser.parse_args(argv)
    orchestrator = WorkflowOrchestrator(llm=demo_llm)

    if args.command == "run":
        result = orchestrator.run(args.message)
    elif args.command == "slash":
        try:
            routed = parse_workflow_slash(args.message)
        except WorkflowSlashError as exc:
            result = {"status": "error", "error": str(exc)}
        else:
            return main(routed.argv)
    elif args.command == "run-template":
        result = orchestrator.run_template(args.template, _parse_kv(args.input))
    elif args.command == "list":
        result = {"workflows": orchestrator.list_workflows()}
    elif args.command == "templates":
        result = {"templates": orchestrator.list_templates()}
    elif args.command == "install":
        try:
            result = {"template": install_template(args.source, template_dir=orchestrator.root / "workflows", name=args.name, overwrite=args.overwrite)}
        except TemplateError as exc:
            result = {"status": "error", "error": str(exc)}
    elif args.command == "edit":
        try:
            result = {"template": edit_template(args.template, _parse_set(args.set), template_dir=orchestrator.root / "workflows")}
        except TemplateError as exc:
            result = {"status": "error", "error": str(exc)}
    elif args.command == "resume":
        result = orchestrator.resume(args.workflow_id)
    elif args.command == "approve":
        result = orchestrator.approve(args.workflow_id, args.step_id)
    else:
        parser.error(f"unknown command: {args.command}")

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
