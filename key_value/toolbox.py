"""Bounded managed Toolbox subprocess; no shell or caller executable overrides."""

from __future__ import annotations
import contextlib
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import platform
import selectors
import signal
import subprocess  # nosec B404
import tempfile
import time
from flowsteward_extension_sdk import resolve_pinned_ips
from validation import Failure, require

ROOT = Path(__file__).resolve().parent
MAX_OUTPUT = 1024 * 1024


def _binary():
    arch = {"aarch64": "arm64", "arm64": "arm64", "x86_64": "amd64", "amd64": "amd64"}.get(
        platform.machine().lower()
    )
    if platform.system() != "Linux" or not arch:
        raise Failure("native_unavailable", "Toolbox requires Linux AMD64 or ARM64.")
    target = "linux-" + arch
    path = ROOT / "bin" / target / "toolbox"
    try:
        expected = json.loads((ROOT / "toolbox-provenance.json").read_text())["binaries"][target][
            "sha256"
        ]
        with path.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        require(
            actual == expected,
            "Packaged Toolbox checksum does not match.",
            code="native_unavailable",
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise Failure(
            "native_unavailable", "Install the packaged Toolbox binary for this architecture."
        ) from exc
    return str(path)


def _endpoint(config):
    try:
        ips = tuple(
            resolve_pinned_ips(config["host"], port=config["port"], purpose="Redis/Valkey endpoint")
        )
        require(bool(ips), "No endpoint addresses.", code="network_blocked")
        private = all(not ipaddress.ip_address(ip).is_global for ip in ips)
        allow = os.environ.get("FS_ALLOW_PRIVATE_REMOTE_URLS", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        require(
            not private or allow,
            "Private endpoints require host administrator permission.",
            code="network_blocked",
        )
        require(config["tls"] or private, "Public endpoints require TLS.", code="network_blocked")
        return ips[0]
    except (ValueError, OSError) as exc:
        raise Failure("network_blocked", "Endpoint blocked by host network policy.") from exc


def managed_config(config, secrets, command, arguments, ip):
    address = f"[{ip}]:{config['port']}" if ":" in ip else f"{ip}:{config['port']}"
    source = {
        "kind": "source",
        "name": "kv-source",
        "type": "redis",
        "address": [address],
        "username": secrets.get("username", ""),
        "password": secrets.get("password", ""),
        "database": config["database"],
        "clusterEnabled": False,
        "tls": {
            "enabled": config["tls"],
            "insecureSkipVerify": False,
            "serverName": config["host"],
        },
    }
    parameters = []
    for name, value in arguments.items():
        parameter = {
            "name": name,
            "type": "array" if isinstance(value, list) else "string",
            "description": "Bound workflow data.",
        }
        if isinstance(value, list):
            parameter["items"] = {
                "name": "item",
                "type": "string",
                "description": "One command argument.",
            }
        parameters.append(parameter)
    tool = {
        "kind": "tool",
        "name": "kv-command",
        "type": "redis",
        "source": "kv-source",
        "description": "One bounded workflow key-value command.",
        "commands": [command],
        "parameters": parameters,
    }
    # JSON is YAML. Escape dollars before Toolbox's raw config environment expansion;
    # decoding restores literal secrets and command placeholders without interpolation.
    return (
        "\n---\n".join(
            json.dumps(d, ensure_ascii=True).replace("$", "\\u0024") for d in (source, tool)
        )
        + "\n"
    )


def _send(process, payload, deadline):
    if process.stdin is None:
        raise Failure("provider_unavailable", "Toolbox input is unavailable.")
    data = memoryview(json.dumps(payload, allow_nan=False, separators=(",", ":")).encode() + b"\n")
    require(len(data) <= 264 * 1024, "Toolbox input exceeds its byte limit.")
    fd = process.stdin.fileno()
    os.set_blocking(fd, False)
    with selectors.DefaultSelector() as selector:
        selector.register(fd, selectors.EVENT_WRITE)
        while data:
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise Failure("timeout", "Toolbox input deadline exceeded.")
            try:
                written = os.write(fd, data[:65536])
            except BlockingIOError:
                continue
            if written <= 0:
                raise Failure("provider_unavailable", "Toolbox input closed.")
            data = data[written:]


def _read(process, request_id, deadline, state):
    require(
        process.stdout is not None and process.stderr is not None,
        "Toolbox streams unavailable.",
        code="provider_unavailable",
    )
    with selectors.DefaultSelector() as selector:
        selector.register(process.stdout, selectors.EVENT_READ, "stdout")
        selector.register(process.stderr, selectors.EVENT_READ, "stderr")
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise Failure("timeout", "Toolbox deadline exceeded.")
            events = selector.select(remaining)
            if not events:
                raise Failure("timeout", "Toolbox deadline exceeded.")
            for key, _ in events:
                chunk = os.read(key.fd, 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                state["bytes"] += len(chunk)
                require(
                    state["bytes"] <= MAX_OUTPUT,
                    "Toolbox output exceeded its byte limit.",
                    code="response_too_large",
                )
                if key.data == "stderr":
                    continue
                state["buffer"].extend(chunk)
                while b"\n" in state["buffer"]:
                    line, _, tail = state["buffer"].partition(b"\n")
                    state["buffer"] = bytearray(tail)
                    try:
                        data = json.loads(line)
                    except (ValueError, UnicodeError):
                        continue
                    if isinstance(data, dict) and data.get("id") == request_id:
                        require(
                            data.get("jsonrpc") == "2.0",
                            "Invalid Toolbox protocol.",
                            code="invalid_provider_response",
                        )
                        return data
    raise Failure("provider_unavailable", "Toolbox closed before its response.")


def _stop(process):
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=2)
    for stream in (process.stdin, process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def _result(response):
    if response.get("error"):
        raise Failure("provider_unavailable", "Toolbox rejected the command.")
    result = response.get("result")
    require(isinstance(result, dict), "Invalid Toolbox result.", code="invalid_provider_response")
    if result.get("isError"):
        # Inspect only for a bounded classification; never return native diagnostics.
        detail = str(result.get("content", ""))[:8192].upper()
        code = (
            "wrong_type"
            if "WRONGTYPE" in detail
            else (
                "authentication_failed"
                if "WRONGPASS" in detail or "NOAUTH" in detail
                else "provider_unavailable"
            )
        )
        raise Failure(code, "Redis/Valkey command failed.")
    if "structuredContent" in result:
        value = result["structuredContent"]
        require(
            isinstance(value, list) and len(value) == 1,
            "Invalid Toolbox command result.",
            code="invalid_provider_response",
        )
        return value[0]
    content = result.get("content")
    require(
        isinstance(content, list) and len(content) == 1,
        "Expected one command result.",
        code="invalid_provider_response",
    )
    block = content[0]
    require(
        isinstance(block, dict)
        and block.get("type") == "text"
        and isinstance(block.get("text"), str),
        "Invalid Toolbox content.",
        code="invalid_provider_response",
    )
    try:
        return json.loads(block["text"])
    except (ValueError, TypeError) as exc:
        raise Failure("invalid_provider_response", "Toolbox result is not JSON.") from exc


def invoke(config, secrets, command, arguments, *, timeout_seconds):
    executable = _binary()
    ip = _endpoint(config)
    dispatched = False
    process = None
    try:
        with tempfile.TemporaryDirectory(prefix="fs-kv-") as directory:
            path = Path(directory) / "tools.yaml"
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                stream.write(managed_config(config, secrets, command, arguments, ip))
            process = subprocess.Popen(  # nosec B603
                [
                    executable,
                    "--config",
                    str(path),
                    "--stdio",
                    "--disable-reload",
                    "--log-level",
                    "ERROR",
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env={"LANG": "C.UTF-8"},
                start_new_session=True,
            )
            deadline = time.monotonic() + timeout_seconds
            state = {"bytes": 0, "buffer": bytearray()}
            try:
                _send(
                    process,
                    {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-06-18",
                            "capabilities": {},
                            "clientInfo": {"name": "flowsteward.redis-valkey", "version": "1.0.0"},
                        },
                    },
                    deadline,
                )
                initial = _read(process, 1, deadline, state)
                require(
                    not initial.get("error") and isinstance(initial.get("result"), dict),
                    "Toolbox initialization failed.",
                    code="provider_unavailable",
                )
                _send(
                    process,
                    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
                    deadline,
                )
                dispatched = True
                _send(
                    process,
                    {
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/call",
                        "params": {"name": "kv-command", "arguments": arguments},
                    },
                    deadline,
                )
                return _result(_read(process, 2, deadline, state))
            finally:
                _stop(process)
    except Failure as exc:
        exc.dispatched = exc.dispatched or dispatched
        raise
    except (OSError, ValueError, TypeError, subprocess.SubprocessError) as exc:
        raise Failure(
            "provider_unavailable", "Toolbox process failed.", dispatched=dispatched
        ) from exc
