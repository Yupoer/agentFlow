from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping

_TOKEN_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*}}")


def stringify(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)
    if value is None:
        return ""
    return str(value)


def render_template(template: str, variables: Mapping[str, Any], *, strict: bool = True) -> str:
    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in variables:
            if strict:
                raise KeyError(f"missing template variable: {key}")
            return match.group(0)
        return stringify(variables[key])

    return _TOKEN_RE.sub(replace, template)


def render_file(path: str | Path, variables: Mapping[str, Any], *, strict: bool = True) -> str:
    return render_template(Path(path).read_text(encoding="utf-8"), variables, strict=strict)
