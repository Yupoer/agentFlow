from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.request import urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STAGE2_SCHEMA = PROJECT_ROOT / "schemas" / "stage2-plan.schema.json"
TEMPLATE_DIR = PROJECT_ROOT / "workflows"
_BINDING_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


class TemplateError(ValueError):
    pass


def list_templates(template_dir: str | Path | None = None) -> list[dict[str, Any]]:
    root = Path(template_dir) if template_dir else TEMPLATE_DIR
    if not root.exists():
        return []
    templates = []
    for path in sorted(root.glob("*.yaml")) + sorted(root.glob("*.yml")) + sorted(root.glob("*.json")):
        data = load_template(path)
        templates.append({
            "name": data.get("name") or path.stem,
            "path": str(path),
            "description": data.get("description", ""),
            "inputs": data.get("inputs", {}),
        })
    return templates


def load_template(name_or_path: str | Path, template_dir: str | Path | None = None) -> dict[str, Any]:
    path = Path(name_or_path)
    if not path.exists():
        root = Path(template_dir) if template_dir else TEMPLATE_DIR
        candidates = [root / f"{name_or_path}{suffix}" for suffix in (".yaml", ".yml", ".json")]
        path = next((candidate for candidate in candidates if candidate.exists()), path)
    if not path.exists():
        raise TemplateError(f"workflow template not found: {name_or_path}")
    text = path.read_text(encoding="utf-8")
    data = _parse_mapping(text, path)
    validate_template(data)
    return data


def bind_template(template: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    declared_inputs = template.get("inputs") or {}
    missing = [name for name, spec in declared_inputs.items() if spec.get("required", True) and name not in inputs]
    if missing:
        raise TemplateError(f"missing workflow inputs: {', '.join(missing)}")

    values = {name: spec.get("default", "") for name, spec in declared_inputs.items() if isinstance(spec, dict)}
    values.update(inputs)
    bound = _bind_value(template, values)
    plan = {
        "status": "ready",
        "summary": str(bound.get("summary") or bound.get("description") or bound.get("name") or "workflow template plan"),
        "steps": bound["steps"],
        "risks": list(bound.get("risks") or []),
        "artifacts": list(bound.get("artifacts") or []),
        "blockers": [],
    }
    validate_template_plan(plan)
    return plan



def validate_template(template: dict[str, Any]) -> None:
    if not isinstance(template, dict):
        raise TemplateError("workflow template must be a mapping/object")
    if not isinstance(template.get("name"), str) or not template.get("name", "").strip():
        raise TemplateError("workflow template requires non-empty name")
    if "steps" not in template or not isinstance(template["steps"], list):
        raise TemplateError("workflow template requires steps array")
    inputs = template.get("inputs", {})
    if inputs is not None and not isinstance(inputs, dict):
        raise TemplateError("workflow template inputs must be an object")
    for name, spec in (inputs or {}).items():
        if not isinstance(name, str) or not name:
            raise TemplateError("workflow template input names must be non-empty strings")
        if not isinstance(spec, dict):
            raise TemplateError(f"workflow template input spec must be object: {name}")
        if "required" in spec and not isinstance(spec["required"], bool):
            raise TemplateError(f"workflow template input required must be boolean: {name}")
    validate_template_plan({
        "status": "ready",
        "summary": str(template.get("summary") or template.get("description") or template.get("name") or "workflow template plan"),
        "steps": template["steps"],
        "risks": list(template.get("risks") or []),
        "artifacts": list(template.get("artifacts") or []),
        "blockers": [],
    })


def validate_template_plan(plan: dict[str, Any]) -> None:
    try:
        from runtime.validator import ValidationError, validate_stage_output
    except ModuleNotFoundError:
        from validator import ValidationError, validate_stage_output
    try:
        validate_stage_output("stage2", plan, STAGE2_SCHEMA)
    except ValidationError as exc:
        raise TemplateError(f"workflow template schema validation failed: {exc}") from exc


def install_template(source: str | Path, *, template_dir: str | Path | None = None, name: str | None = None, overwrite: bool = False) -> dict[str, Any]:
    root = Path(template_dir) if template_dir else TEMPLATE_DIR
    root.mkdir(parents=True, exist_ok=True)
    source_text: str
    suffix = ".yaml"
    if str(source).startswith(("http://", "https://")):
        with urlopen(str(source), timeout=20) as response:
            source_text = response.read().decode("utf-8")
        suffix = Path(str(source).split("?", 1)[0]).suffix or ".yaml"
    else:
        src = Path(source)
        if not src.exists():
            raise TemplateError(f"workflow template source not found: {source}")
        source_text = src.read_text(encoding="utf-8")
        suffix = src.suffix or ".yaml"
    data = _parse_mapping(source_text, Path(f"template{suffix}"))
    validate_template(data)
    template_name = name or data.get("name")
    if not isinstance(template_name, str) or not template_name.strip():
        raise TemplateError("workflow template install requires a name")
    target = root / f"{_safe_template_name(template_name)}{suffix if suffix in {'.yaml', '.yml', '.json'} else '.yaml'}"
    if target.exists() and not overwrite:
        raise TemplateError(f"workflow template already exists: {target}")
    target.write_text(source_text, encoding="utf-8")
    return {"name": template_name, "path": str(target)}


def edit_template(name: str, updates: dict[str, Any], *, template_dir: str | Path | None = None) -> dict[str, Any]:
    root = Path(template_dir) if template_dir else TEMPLATE_DIR
    template = load_template(name, root)
    for key, value in updates.items():
        if key not in {"description", "summary"}:
            raise TemplateError(f"workflow template edit supports description/summary only, got: {key}")
        template[key] = value
    validate_template(template)
    path = _template_path(name, root)
    path.write_text(json.dumps(template, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"name": template.get("name") or path.stem, "path": str(path), "updated": sorted(updates)}


def _template_path(name_or_path: str | Path, template_dir: str | Path | None = None) -> Path:
    path = Path(name_or_path)
    if path.exists():
        return path
    root = Path(template_dir) if template_dir else TEMPLATE_DIR
    for suffix in (".yaml", ".yml", ".json"):
        candidate = root / f"{name_or_path}{suffix}"
        if candidate.exists():
            return candidate
    raise TemplateError(f"workflow template not found: {name_or_path}")


def _safe_template_name(name: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", name).strip("._-")
    if not safe:
        raise TemplateError("workflow template name is invalid")
    return safe

def _bind_value(value: Any, inputs: dict[str, Any]) -> Any:
    if isinstance(value, str):
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            if key not in inputs:
                raise TemplateError(f"unbound workflow input: {key}")
            return str(inputs[key])
        return _BINDING_RE.sub(replace, value)
    if isinstance(value, list):
        return [_bind_value(item, inputs) for item in value]
    if isinstance(value, dict):
        return {key: _bind_value(child, inputs) for key, child in value.items() if key not in {"inputs"}}
    return value


def _parse_mapping(text: str, path: Path) -> Any:
    if path.suffix == ".json":
        return json.loads(text)
    try:
        import yaml  # type: ignore
    except Exception:
        # YAML 1.2 accepts JSON as a subset. This fallback intentionally supports
        # JSON-compatible .yaml files without adding a dependency.
        return json.loads(text)
    return yaml.safe_load(text)
