"""Bounded Redis/Valkey action and project connection values."""

from __future__ import annotations
import ipaddress
import json
import re


class Failure(Exception):
    def __init__(self, code, message, *, dispatched=False):
        super().__init__(message)
        self.code = code
        self.dispatched = dispatched


def require(condition, message, *, code="invalid_payload"):
    if not condition:
        raise Failure(code, message)


def text(value, name, maximum=65536, *, nonempty=False):
    require(isinstance(value, str), f"{name} must be text.")
    try:
        require(len(value.encode("utf-8")) <= maximum, f"{name} exceeds its UTF-8 byte limit.")
    except UnicodeError as exc:
        raise Failure("invalid_payload", f"{name} must be valid UTF-8.") from exc
    require(not nonempty or bool(value.strip()), f"{name} must be nonempty.")
    return value


def integer(value, name, low, high):
    require(
        type(value) is int and low <= value <= high,
        f"{name} must be an integer from {low} to {high}.",
    )
    return value


def bounded_json(value, limit=256 * 1024):
    try:
        require(
            len(json.dumps(value, allow_nan=False).encode()) <= limit,
            "Input exceeds the JSON byte limit.",
        )
    except (ValueError, TypeError, RecursionError, UnicodeError) as exc:
        raise Failure("invalid_payload", "Bounded valid JSON is required.") from exc


def connection_values(connection):
    try:
        config = connection.get("config") or {}
        secrets = connection.get("secrets") or {}
        require(
            isinstance(config, dict) and isinstance(secrets, dict),
            "Connection must contain objects.",
        )
        require(
            set(config)
            <= {"host", "port", "database", "namespace", "tls", "request_timeout_seconds"},
            "Unknown connection setting.",
        )
        require(set(secrets) <= {"username", "password"}, "Unknown credential setting.")
        host = text(config.get("host"), "host", 253, nonempty=True)
        require(
            not any(c.isspace() or c in "/\\@?#[]$" for c in host),
            "Use a hostname or IP without a URL, port or credentials.",
        )
        if ":" in host:
            ipaddress.IPv6Address(host)
        port = integer(config.get("port", 6379), "port", 1, 65535)
        database = integer(config.get("database", 0), "database", 0, 15)
        namespace = text(config.get("namespace", "workflow"), "namespace", 64, nonempty=True)
        require(
            bool(re.fullmatch(r"[A-Za-z0-9_-]{1,64}", namespace)),
            "Namespace must use letters, digits, hyphens or underscores.",
        )
        tls = config.get("tls", True)
        require(type(tls) is bool, "TLS must be boolean.")
        timeout = integer(
            config.get("request_timeout_seconds", 15), "request_timeout_seconds", 1, 30
        )
        for name in ("username", "password"):
            text(secrets.get(name, ""), name, 8192)
        return {
            "host": host,
            "port": port,
            "database": database,
            "namespace": namespace,
            "tls": tls,
            "request_timeout_seconds": timeout,
        }, secrets
    except (Failure, ValueError, TypeError) as exc:
        raise Failure(
            "invalid_connection", "Invalid Redis/Valkey connection configuration or credentials."
        ) from exc
