"""Permission-aware client for the local iMessage file bridge."""

from __future__ import annotations

import json
import os
import pathlib
import stat
import time
import uuid
from typing import Any

# Product layout: ~/Library/Application Support/Bridge Pro/bridges/<product-id>
LAYOUT = pathlib.Path("Library") / "Application Support" / "Bridge Pro" / "bridges"
PRODUCT_IDS = ("claude", "grok", "openai")

# DIY default: ~/Library/Application Support/ChatGPTCodexIMessage
DEFAULT_BRIDGE = pathlib.Path.home() / "Library" / "Application Support" / "ChatGPTCodexIMessage"
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class BridgeError(RuntimeError):
    """A safe, user-facing bridge failure."""


def _absolute_preserving_links(path: pathlib.Path) -> pathlib.Path:
    expanded = path.expanduser()
    return expanded if expanded.is_absolute() else pathlib.Path.cwd() / expanded


def _reject_symlink_components(path: pathlib.Path) -> None:
    absolute = _absolute_preserving_links(path)
    current = pathlib.Path(absolute.anchor)
    for component in absolute.parts[1:]:
        current /= component
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(metadata.st_mode):
            raise BridgeError(f"Refusing symlinked bridge path component: {current}")


def _validate_private_directory(path: pathlib.Path, label: str) -> None:
    _reject_symlink_components(path)
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise BridgeError(f"{label} is missing at {path}; rerun the iMessage installer") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise BridgeError(f"{label} is not a directory: {path}")
    if metadata.st_uid != os.getuid():
        raise BridgeError(f"{label} is not owned by the current user: {path}")
    if stat.S_IMODE(metadata.st_mode) & 0o077:
        raise BridgeError(f"{label} permissions are too broad at {path}; expected mode 700")


def _read_private_response(path: pathlib.Path) -> dict[str, Any]:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise BridgeError("Helper response is not a regular file")
        if metadata.st_uid != os.getuid():
            raise BridgeError("Helper response is not owned by the current user")
        if stat.S_IMODE(metadata.st_mode) & 0o077:
            raise BridgeError("Helper response permissions are too broad; expected mode 600")
        if metadata.st_size > MAX_RESPONSE_BYTES:
            raise BridgeError("Helper response exceeds the 16 MiB safety limit")
        payload = bytearray()
        while len(payload) <= MAX_RESPONSE_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_RESPONSE_BYTES + 1 - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > MAX_RESPONSE_BYTES:
            raise BridgeError("Helper response exceeds the 16 MiB safety limit")
    finally:
        os.close(descriptor)

    try:
        decoded = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeError("Helper returned malformed response JSON") from exc
    if not isinstance(decoded, dict):
        raise BridgeError("Helper response must be a JSON object")
    return decoded


def resolve_runtime_bridge(
    explicit_path: pathlib.Path | str | None = None,
    product: str | None = None,
) -> pathlib.Path:
    """
    Resolve the bridge root directory for DIY or product mode.
    
    Args:
        explicit_path: Explicit --bridge-root path if provided
        product: Product ID (claude, grok, openai) if in product mode
    
    Returns:
        Absolute bridge root path
    
    Raises:
        ValueError: If both explicit_path and product are provided
    """
    if explicit_path and product:
        raise ValueError("--bridge-root is mutually exclusive with --product")
    
    if product:
        if product not in PRODUCT_IDS:
            raise ValueError(f"Unknown product: {product}; expected one of {list(PRODUCT_IDS)}")
        return pathlib.Path.home() / LAYOUT / product
    
    if explicit_path:
        return _absolute_preserving_links(pathlib.Path(explicit_path))
    
    # DIY mode: --bridge-root CLI or CHATGPT_CODEX_IMESSAGE_BRIDGE env or DEFAULT_BRIDGE
    configured = os.environ.get("CHATGPT_CODEX_IMESSAGE_BRIDGE")
    return _absolute_preserving_links(pathlib.Path(configured) if configured else DEFAULT_BRIDGE)


class BridgeClient:
    def __init__(self, bridge_root: pathlib.Path | None = None) -> None:
        configured = os.environ.get("CHATGPT_CODEX_IMESSAGE_BRIDGE")
        self.bridge_root = _absolute_preserving_links(
            bridge_root or (pathlib.Path(configured) if configured else DEFAULT_BRIDGE)
        )
        self.requests = self.bridge_root / "control" / "requests"
        self.responses = self.bridge_root / "control" / "responses"

    def _validate(self) -> None:
        _validate_private_directory(self.bridge_root, "Bridge root")
        _validate_private_directory(self.requests, "Request directory")
        _validate_private_directory(self.responses, "Response directory")

    def request(
        self,
        action: str,
        params: dict[str, Any],
        *,
        timeout_seconds: float = 20.0,
        delivery_may_be_unknown: bool = False,
    ) -> dict[str, Any]:
        self._validate()
        request_id = uuid.uuid4().hex
        request_name = f"request-{request_id}.json"
        request_path = self.requests / request_name
        temporary_path = self.requests / f".{request_name}.{os.getpid()}.tmp"
        response_path = self.responses / f"response-{request_id}.json"
        payload = json.dumps(
            {"id": request_id, "action": action, "params": params},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")

        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(temporary_path, flags, 0o600)
        try:
            with os.fdopen(descriptor, "wb", closefd=False) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
        finally:
            os.close(descriptor)

        try:
            os.replace(temporary_path, request_path)
            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                try:
                    result = _read_private_response(response_path)
                except FileNotFoundError:
                    time.sleep(0.05)
                    continue
                except Exception:
                    response_path.unlink(missing_ok=True)
                    raise
                response_path.unlink(missing_ok=True)
                if result.get("id") != request_id:
                    raise BridgeError("Helper response ID does not match the request")
                if result.get("ok") is not True:
                    error = result.get("error")
                    raise BridgeError(error if isinstance(error, str) else "iMessage helper request failed")
                return result
        finally:
            temporary_path.unlink(missing_ok=True)
            request_path.unlink(missing_ok=True)

        suffix = (
            " Delivery status may be unknown; inspect Messages before attempting another send."
            if delivery_may_be_unknown
            else ""
        )
        raise BridgeError(f"Timed out waiting for the iMessage helper.{suffix}")
