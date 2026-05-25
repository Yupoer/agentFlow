from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from urllib.error import URLError
from urllib.request import Request, urlopen

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def artifact_failure(artifact: dict[str, Any]) -> str:
    status = artifact.get("status")
    uri = str(artifact.get("uri") or "")
    artifact_type = artifact.get("type")
    if status in {"pending", "missing"}:
        return f"artifact {status}: {uri}"
    if artifact_type in {"file", "markdown", "json"} and not file_exists(uri):
        return f"artifact file does not exist: {uri}"
    if artifact_type == "url" and not url_reachable(uri):
        return f"artifact URL is not reachable: {uri}"
    if artifact_type == "email" and status != "verified" and not email_verified(uri, artifact):
        return f"artifact email is not verified in Himalaya sent mail: {uri}"
    if artifact_type == "message" and status != "verified" and not message_verified(uri, artifact):
        return f"artifact message is not verified from send_message result: {uri}"
    return ""


def file_exists(uri: str) -> bool:
    if not uri:
        return False
    path = Path(uri)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.exists()


def url_reachable(uri: str) -> bool:
    if not uri.startswith(("http://", "https://")):
        return False
    for method in ("HEAD", "GET"):
        request = Request(uri, method=method, headers={"User-Agent": "agentflow-verifier/0.1"})
        try:
            with urlopen(request, timeout=10) as response:
                if 200 <= response.status < 400:
                    return True
        except (URLError, TimeoutError, ValueError, OSError):
            continue
    return False


def email_verified(uri: str, artifact: dict[str, Any] | None = None) -> bool:
    """Verify an email artifact against Himalaya sent mail when possible.

    `uri` may be a raw Message-ID, `email:<recipient>`, or a JSON object/string
    containing message_id/message-id/recipient/to. A child executor may still set
    status=verified when it already performed a provider-specific verification.
    """

    needle = _artifact_payload(uri, artifact)
    message_id = str(needle.get("message_id") or needle.get("message-id") or needle.get("id") or uri).strip("<>")
    recipient = str(needle.get("recipient") or needle.get("to") or "")
    if uri.startswith("email:") and not recipient:
        recipient = uri.split(":", 1)[1]

    if not shutil.which("himalaya"):
        return False

    candidates = [message_id, recipient]
    candidates = [c for c in candidates if c and not c.startswith("email:")]
    if not candidates:
        return False

    folders = os.environ.get("AGENTFLOW_SENT_FOLDERS", "sent,Sent").split(",")
    for folder in [folder.strip() for folder in folders if folder.strip()]:
        try:
            proc = subprocess.run(
                ["himalaya", "envelope", "list", "--folder", folder, "--page-size", "50", "--output", "json"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if proc.returncode != 0:
            continue
        haystack = proc.stdout.lower()
        if any(candidate.lower() in haystack for candidate in candidates):
            return True
    return False


def message_verified(uri: str, artifact: dict[str, Any] | None = None) -> bool:
    """Verify a message artifact from a send_message tool result.

    The runtime cannot query arbitrary platform histories, so this accepts the
    structured result returned by send_message (success/ok/status sent + optional
    message_id/target). This prevents a plain unverified URI from passing.
    """

    payload = _artifact_payload(uri, artifact)
    if not payload:
        return False
    status = str(payload.get("status") or "").lower()
    success = payload.get("success") is True or payload.get("ok") is True or status in {"sent", "delivered", "verified"}
    has_handle = bool(payload.get("message_id") or payload.get("id") or payload.get("target") or payload.get("platform"))
    return bool(success and has_handle)


def _artifact_payload(uri: str, artifact: dict[str, Any] | None = None) -> dict[str, Any]:
    sources = [uri]
    if artifact:
        description = artifact.get("description")
        if isinstance(description, str):
            sources.append(description)
    for source in sources:
        try:
            data = json.loads(source)
        except (TypeError, json.JSONDecodeError):
            match = re.search(r"\{.*\}", str(source), re.S)
            if not match:
                continue
            try:
                data = json.loads(match.group(0))
            except json.JSONDecodeError:
                continue
        if isinstance(data, dict):
            return data
    return {}
