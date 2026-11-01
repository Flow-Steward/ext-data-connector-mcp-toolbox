"""Compile a fixed bounded operation to one parameterized Toolbox command."""

from __future__ import annotations
import hashlib
import json
from typing import Any
from validation import Failure, integer, require, text

WRITES = {
    "set",
    "delete",
    "expire",
    "increment",
    "hash_set",
    "hash_delete",
    "list_push",
    "list_pop",
}
FIELDS = {
    "get": set(),
    "set": {"value", "ttl_seconds", "condition"},
    "delete": set(),
    "exists": set(),
    "ttl": set(),
    "expire": {"ttl_seconds"},
    "increment": {"amount"},
    "hash_get": {"field"},
    "hash_set": {"fields"},
    "hash_delete": {"fields"},
    "hash_get_all": set(),
    "list_push": {"values", "direction"},
    "list_pop": {"direction"},
    "list_range": {"start", "count"},
    "list_length": set(),
}


def physical_key(args, config, context, connection_id):
    key = text(args.get("key"), "key", 256, nonempty=True)
    for name in ("account_id", "project_id"):
        require(
            isinstance(context.get(name), str) and bool(context[name].strip()),
            "Account and project scope required.",
            code="invalid_connection",
        )
    scope = hashlib.sha256(
        json.dumps(
            [context["account_id"], context["project_id"], connection_id], separators=(",", ":")
        ).encode()
    ).hexdigest()[:32]
    return config["namespace"] + ":" + scope + ":" + key


def compile_command(action, args, config, context, connection_id):
    if action not in FIELDS:
        raise Failure("unknown_action", "Unknown Redis/Valkey action.")
    require(set(args) <= FIELDS[action] | {"connection_ref", "key"}, "Unknown action input.")
    params: dict[str, Any] = {"key": physical_key(args, config, context, connection_id)}
    fixed = {
        "get": "GET",
        "delete": "DEL",
        "exists": "EXISTS",
        "ttl": "TTL",
        "hash_get_all": "HGETALL",
        "list_length": "LLEN",
    }
    if action in fixed:
        return [fixed[action], "$key"], params
    if action == "set":
        params["value"] = text(args.get("value"), "value")
        condition = args.get("condition", "always")
        require(condition in {"always", "nx", "xx"}, "Condition must be always, nx or xx.")
        command = ["SET", "$key", "$value"]
        if "ttl_seconds" in args:
            params["ttl"] = str(integer(args["ttl_seconds"], "ttl_seconds", 1, 2147483647))
            command.extend(["EX", "$ttl"])
        if condition != "always":
            command.append(condition.upper())
        return command, params
    if action == "expire":
        params["ttl"] = str(integer(args.get("ttl_seconds"), "ttl_seconds", 1, 2147483647))
        return ["EXPIRE", "$key", "$ttl"], params
    if action == "increment":
        params["amount"] = str(
            integer(args.get("amount", 1), "amount", -9007199254740991, 9007199254740991)
        )
        return ["INCRBY", "$key", "$amount"], params
    if action == "hash_get":
        params["field"] = text(args.get("field"), "field", 256, nonempty=True)
        return ["HGET", "$key", "$field"], params
    if action == "hash_set":
        fields = args.get("fields")
        require(isinstance(fields, dict) and 1 <= len(fields) <= 64, "Supply 1 to 64 hash fields.")
        params["items"] = []
        for name, value in fields.items():
            params["items"].extend(
                [text(name, "field", 256, nonempty=True), text(value, "field value")]
            )
        return ["HSET", "$key", "$items"], params
    if action == "hash_delete":
        fields = args.get("fields")
        require(isinstance(fields, list) and 1 <= len(fields) <= 64, "Supply 1 to 64 field names.")
        params["items"] = [text(name, "field", 256, nonempty=True) for name in fields]
        return ["HDEL", "$key", "$items"], params
    if action in {"list_push", "list_pop"}:
        direction = args.get("direction", "right" if action == "list_push" else "left")
        require(direction in {"left", "right"}, "Direction must be left or right.")
        prefix = "L" if direction == "left" else "R"
        if action == "list_pop":
            return [prefix + "POP", "$key"], params
        values = args.get("values")
        require(isinstance(values, list) and 1 <= len(values) <= 64, "Supply 1 to 64 list values.")
        params["items"] = [text(v, "list value") for v in values]
        return [prefix + "PUSH", "$key", "$items"], params
    start = integer(args.get("start", 0), "start", 0, 2147483647)
    count = integer(args.get("count", 100), "count", 1, 100)
    params.update(start=str(start), end=str(start + count - 1))
    return ["LRANGE", "$key", "$start", "$end"], params


def normalize_result(action, value, key):
    integer_results = {
        "delete",
        "exists",
        "ttl",
        "expire",
        "increment",
        "hash_set",
        "hash_delete",
        "list_push",
        "list_length",
    }
    if action in integer_results:
        require(
            type(value) is int,
            "Provider returned an invalid integer.",
            code="invalid_provider_response",
        )
        require(
            -9007199254740991 <= value <= 9007199254740991,
            "Provider result exceeds safe integer bounds.",
            code="invalid_provider_response",
        )
    if action in {"get", "hash_get", "list_pop"}:
        require(
            value is None or isinstance(value, str),
            "Provider returned invalid text.",
            code="invalid_provider_response",
        )
    if action == "set":
        require(
            value in (None, "OK"),
            "Provider returned invalid SET result.",
            code="invalid_provider_response",
        )
    if action == "hash_get_all":
        # RESP3 yields a map; RESP2 may yield alternating field/value strings.
        if isinstance(value, list):
            require(len(value) % 2 == 0, "Invalid hash result.", code="invalid_provider_response")
            value = dict(zip(value[::2], value[1::2], strict=True))
        require(
            isinstance(value, dict)
            and all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()),
            "Provider returned invalid hash.",
            code="invalid_provider_response",
        )
    if action == "list_range":
        require(
            isinstance(value, list)
            and len(value) <= 100
            and all(isinstance(v, str) for v in value),
            "Provider returned invalid list.",
            code="invalid_provider_response",
        )
    found = value is not None
    if action in {"exists", "expire", "delete"}:
        found = value > 0
    if action == "ttl":
        found = value != -2
    if action in {"hash_get_all", "list_range"}:
        found = bool(value)
    applied = action in WRITES
    if action == "set":
        applied = value == "OK"
    if action in {"delete", "expire", "hash_delete"}:
        applied = value > 0
    if action == "list_pop":
        applied = value is not None
    return {"key": key, "value": value, "found": found, "applied": applied}
