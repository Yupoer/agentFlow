from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class ValidationError(ValueError):
    pass


class LLMQuotaExceededError(RuntimeError):
    pass


def _error_status_code(exc: BaseException) -> int | None:
    for attr in ("status_code", "status", "code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value

    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def is_llm_quota_exceeded(exc: BaseException) -> bool:
    status_code = _error_status_code(exc)
    if status_code == 429:
        return True

    message = str(exc).lower()
    return "quota" in message or "rate limit" in message or "ratelimit" in message


def is_retryable_llm_error(exc: BaseException) -> bool:
    if is_llm_quota_exceeded(exc):
        return False

    status_code = _error_status_code(exc)
    if status_code is not None:
        return 500 <= status_code <= 599

    if isinstance(exc, TimeoutError):
        return True

    message = str(exc).lower()
    timeout_markers = (
        "timeout",
        "timed out",
        "read timed out",
        "connect timed out",
        "connection timed out",
        "network timeout",
    )
    return any(marker in message for marker in timeout_markers)


def load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid schema JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError("schema must be a JSON object")
    return value


def parse_json_object(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValidationError(f"invalid JSON output: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError("stage output must be a JSON object")
    return value


def validate_schema(instance: dict[str, Any], schema: dict[str, Any]) -> None:
    try:
        import jsonschema
    except ImportError:
        _minimal_validate(instance, schema, "$")
        return

    try:
        jsonschema.Draft202012Validator(schema).validate(instance)
    except Exception as exc:
        raise ValidationError(str(exc)) from exc


def _minimal_validate(value: Any, schema: dict[str, Any], path: str) -> None:
    any_of = schema.get("anyOf")
    if any_of is not None:
        errors = []
        for child_schema in any_of:
            try:
                _minimal_validate(value, child_schema, path)
                return
            except ValidationError as exc:
                errors.append(str(exc))
        raise ValidationError(f"{path}: expected anyOf match; {errors[0] if errors else ''}")

    expected_type = schema.get("type")
    if isinstance(expected_type, list):
        errors = []
        for child_type in expected_type:
            try:
                child_schema = dict(schema)
                child_schema["type"] = child_type
                _minimal_validate(value, child_schema, path)
                return
            except ValidationError as exc:
                errors.append(str(exc))
        raise ValidationError(f"{path}: expected one of {expected_type}; {errors[0] if errors else ''}")

    if expected_type is not None:
        valid = {
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
            "string": isinstance(value, str),
            "boolean": isinstance(value, bool),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "null": value is None,
        }.get(expected_type, True)
        if not valid:
            raise ValidationError(f"{path}: expected {expected_type}")

    enum_values = schema.get("enum")
    if enum_values is not None and value not in enum_values:
        raise ValidationError(f"{path}: expected one of {enum_values}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                raise ValidationError(f"{path}: missing required key '{key}'")
        properties = schema.get("properties", {})
        additional = schema.get("additionalProperties", True)
        for key, child in value.items():
            if key in properties:
                _minimal_validate(child, properties[key], f"{path}.{key}")
            elif additional is False:
                raise ValidationError(f"{path}: unexpected key '{key}'")

    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            _minimal_validate(item, schema["items"], f"{path}[{index}]")


def validate_stage_output(stage_name: str, instance: dict[str, Any], schema_path: str | Path) -> None:
    validate_schema(instance, load_json(schema_path))
    if stage_name == "stage1":
        validate_stage1_contract(instance)
    elif stage_name == "stage2":
        validate_stage2_contract(instance)
    elif stage_name == "stage3":
        validate_stage3_contract(instance)
    elif stage_name == "stage4":
        validate_stage4_contract(instance)
    elif stage_name == "stage5":
        validate_stage5_contract(instance)
    else:
        raise ValidationError(f"unknown stage: {stage_name}")


def validate_stage1_contract(data: dict[str, Any]) -> None:
    status = data["status"]
    blockers = data["blockers"]
    if status == "ready" and blockers:
        raise ValidationError("stage1 ready output requires blockers to be empty")
    if status == "blocked" and not blockers:
        raise ValidationError("stage1 blocked output requires blockers")
    if status == "ready" and not data["objective"].strip():
        raise ValidationError("stage1 ready output requires objective")


def validate_stage2_contract(data: dict[str, Any]) -> None:
    status = data["status"]
    blockers = data["blockers"]
    if status == "ready" and blockers:
        raise ValidationError("stage2 ready output requires blockers to be empty")
    if status == "blocked" and not blockers:
        raise ValidationError("stage2 blocked output requires blockers")
    if status == "ready" and not data["steps"]:
        raise ValidationError("stage2 ready output requires steps")


def validate_stage3_step_result(data: dict[str, Any]) -> None:
    required = ("step_id", "status", "output", "error")
    for key in required:
        if key not in data:
            raise ValidationError(f"stage3 step result missing required key '{key}'")
    unexpected = set(data) - set(required) - {"artifacts"}
    if unexpected:
        raise ValidationError(f"stage3 step result unexpected keys: {sorted(unexpected)}")
    if not isinstance(data["step_id"], str) or not data["step_id"].strip():
        raise ValidationError("stage3 step result requires step_id")
    if data["status"] not in {"done", "failed", "skipped"}:
        raise ValidationError("stage3 step result status must be done, failed, or skipped")
    if not isinstance(data["output"], str):
        raise ValidationError("stage3 step result output must be a string")
    if data["error"] is not None and not isinstance(data["error"], str):
        raise ValidationError("stage3 step result error must be string or null")
    if data["status"] == "done" and data["error"] is not None:
        raise ValidationError("stage3 done step result requires error to be null")
    if data["status"] in {"failed", "skipped"} and not data["error"]:
        raise ValidationError("stage3 failed/skipped step result requires error")
    artifacts = data.get("artifacts", [])
    if not isinstance(artifacts, list):
        raise ValidationError("stage3 step result artifacts must be an array")
    for artifact in artifacts:
        validate_stage3_artifact(artifact)


def validate_stage3_artifact(data: dict[str, Any]) -> None:
    if not isinstance(data, dict):
        raise ValidationError("stage3 artifact must be an object")
    required = ("type", "uri", "status")
    for key in required:
        if key not in data:
            raise ValidationError(f"stage3 artifact missing required key '{key}'")
    unexpected = set(data) - set(required) - {"description"}
    if unexpected:
        raise ValidationError(f"stage3 artifact unexpected keys: {sorted(unexpected)}")
    if data["type"] not in {"file", "url", "email", "message", "json", "markdown", "other"}:
        raise ValidationError("stage3 artifact type is invalid")
    if not isinstance(data["uri"], str) or not data["uri"].strip():
        raise ValidationError("stage3 artifact requires uri")
    if data["status"] not in {"created", "verified", "pending", "missing"}:
        raise ValidationError("stage3 artifact status is invalid")
    if "description" in data and not isinstance(data["description"], str):
        raise ValidationError("stage3 artifact description must be a string")


def validate_stage3_contract(data: dict[str, Any]) -> None:
    status = data["status"]
    blockers = data["blockers"]
    step_results = data["step_results"]
    for result in step_results:
        validate_stage3_step_result(result)
    if status == "ready":
        if blockers:
            raise ValidationError("stage3 ready output requires blockers to be empty")
        if any(result["status"] != "done" for result in step_results):
            raise ValidationError("stage3 ready output requires all steps done")
    if status == "partial":
        if not any(result["status"] in {"failed", "skipped"} for result in step_results):
            raise ValidationError("stage3 partial output requires failed or skipped steps")
        if not blockers:
            raise ValidationError("stage3 partial output requires blockers")
    if status == "blocked" and not blockers:
        raise ValidationError("stage3 blocked output requires blockers")


def validate_stage4_verdict(data: dict[str, Any]) -> None:
    required = ("step_id", "verdict", "reason")
    for key in required:
        if key not in data:
            raise ValidationError(f"stage4 verdict missing required key '{key}'")
    unexpected = set(data) - set(required)
    if unexpected:
        raise ValidationError(f"stage4 verdict unexpected keys: {sorted(unexpected)}")
    if not isinstance(data["step_id"], str) or not data["step_id"].strip():
        raise ValidationError("stage4 verdict requires step_id")
    if data["verdict"] not in {"pass", "fail", "skipped"}:
        raise ValidationError("stage4 verdict must be pass, fail, or skipped")
    if not isinstance(data["reason"], str) or not data["reason"].strip():
        raise ValidationError("stage4 verdict requires reason")


def validate_stage4_contract(data: dict[str, Any]) -> None:
    status = data["status"]
    verdicts = data["verdicts"]
    blockers = data["blockers"]
    if not isinstance(data["summary"], str) or not data["summary"].strip():
        raise ValidationError("stage4 output requires summary")
    for verdict in verdicts:
        validate_stage4_verdict(verdict)
    if status == "ready":
        if blockers:
            raise ValidationError("stage4 ready output requires blockers to be empty")
        if any(verdict["verdict"] != "pass" for verdict in verdicts):
            raise ValidationError("stage4 ready output requires all verdicts pass")
    if status == "partial":
        if not any(verdict["verdict"] in {"fail", "skipped"} for verdict in verdicts):
            raise ValidationError("stage4 partial output requires failed or skipped verdicts")
    if status == "blocked" and not blockers:
        raise ValidationError("stage4 blocked output requires blockers")


def validate_stage5_step(data: dict[str, Any]) -> None:
    required = ("step_id", "status", "verdict", "output")
    for key in required:
        if key not in data:
            raise ValidationError(f"stage5 step missing required key '{key}'")
    unexpected = set(data) - set(required)
    if unexpected:
        raise ValidationError(f"stage5 step unexpected keys: {sorted(unexpected)}")
    if not isinstance(data["step_id"], str) or not data["step_id"].strip():
        raise ValidationError("stage5 step requires step_id")
    if data["status"] not in {"done", "failed", "skipped"}:
        raise ValidationError("stage5 step status must be done, failed, or skipped")
    if data["verdict"] not in {"pass", "fail", "skipped"}:
        raise ValidationError("stage5 step verdict must be pass, fail, or skipped")
    if not isinstance(data["output"], str):
        raise ValidationError("stage5 step output must be a string")


def validate_stage5_contract(data: dict[str, Any]) -> None:
    for key in ("objective", "summary", "plan_summary", "execution_summary", "verification_summary", "execution_mode", "partial_reason"):
        if not isinstance(data[key], str):
            raise ValidationError(f"stage5 output {key} must be a string")
    if data["execution_mode"] not in {"standalone", "delegated"}:
        raise ValidationError("stage5 execution_mode must be standalone or delegated")
    if not isinstance(data["stage3_available"], bool):
        raise ValidationError("stage5 stage3_available must be a boolean")
    for step in data["steps"]:
        validate_stage5_step(step)
    if data["status"] == "ready":
        if data["errors"]:
            raise ValidationError("stage5 ready output requires errors to be empty")
        if data["blockers"]:
            raise ValidationError("stage5 ready output requires blockers to be empty")
    if data["status"] == "error" and not data["errors"]:
        raise ValidationError("stage5 error output requires errors")
    if data["status"] == "blocked" and not data["blockers"]:
        raise ValidationError("stage5 blocked output requires blockers")
