"""Bounded workflow actions and effect semantics."""

from copy import deepcopy
import pytest
import main


def envelope(action, args=None, *, project="p", kind="redis"):
    return {
        "contract_version": "extension_host_v2",
        "mode": "action",
        "runtime_context": {
            "group_id": None,
            "for_each_id": None,
            "step_id": "step",
            "step_execution_id": "execution",
            "account_id": "a",
            "project_id": project,
            "external_effect_id": "claim",
        },
        "action": {
            "action_id": action,
            "input": {"connection_ref": "conn", "key": "item", **(args or {})},
            "target": {
                "connection": {
                    "connection_id": "conn",
                    "connection_type": kind,
                    "config": {
                        "host": "redis.example",
                        "port": 6379,
                        "database": 0,
                        "namespace": "workflows",
                        "tls": True,
                    },
                    "secrets": {"username": "default", "password": "secret"},
                }
            },
        },
    }


def fake(monkeypatch, value):
    import toolbox

    calls = []

    def invoke(config, secrets, command, arguments, *, timeout_seconds):
        calls.append(deepcopy((config, secrets, command, arguments, timeout_seconds)))
        return value

    monkeypatch.setattr(toolbox, "invoke", invoke)
    return calls


def test_get_missing_and_empty_are_distinct(monkeypatch):
    fake(monkeypatch, None)
    r = main.handle(envelope("get"))
    assert r["ok"], r
    assert r["result"]["value"] is None and not r["result"]["found"]
    fake(monkeypatch, "")
    r = main.handle(envelope("get"))
    assert r["result"]["value"] == "" and r["result"]["found"]


def test_set_nx_ttl_is_one_command_and_values_are_parameters(monkeypatch):
    calls = fake(monkeypatch, "OK")
    r = main.handle(
        envelope("set", {"value": 'a\n$other " value', "ttl_seconds": 60, "condition": "nx"})
    )
    assert r["ok"], r
    _, _, command, args, _ = calls[0]
    assert command == ["SET", "$key", "$value", "EX", "$ttl", "NX"]
    assert args["value"] == 'a\n$other " value' and args["ttl"] == "60"
    assert "item" in args["key"] and args["key"] != "item"
    assert r["result"]["applied"]


def test_namespaces_include_project_and_connection(monkeypatch):
    calls = fake(monkeypatch, "value")
    main.handle(envelope("get"))
    main.handle(envelope("get", project="other"))
    p = envelope("get")
    p["action"]["target"]["connection"]["connection_id"] = "different"
    p["action"]["input"]["connection_ref"] = "different"
    main.handle(p)
    assert len({c[3]["key"] for c in calls}) == 3


@pytest.mark.parametrize(
    "args",
    [
        {"ttl_seconds": 0},
        {"condition": "bad"},
        {"value": 123},
        {"value": "x" * 65537},
        {"ttl_seconds": True},
    ],
)
def test_set_invalid_input_never_calls_provider(monkeypatch, args):
    calls = fake(monkeypatch, "OK")
    r = main.handle(envelope("set", {"value": "hello", **args}))
    assert not r["ok"] and r["error_code"] == "invalid_payload"
    assert not calls


def test_write_claim_and_test_mode_before_io(monkeypatch):
    calls = fake(monkeypatch, 1)
    p = envelope("increment")
    p["runtime_context"].pop("external_effect_id")
    assert main.handle(p)["error_code"] == "effect_claim_required"
    p = envelope("delete")
    p["runtime_context"]["test_mode"] = True
    assert main.handle(p)["error_code"] == "test_mode_suppressed"
    assert not calls


def test_test_mode_still_validates_input(monkeypatch):
    calls = fake(monkeypatch, None)
    p = envelope("set", {"value": 123})
    p["runtime_context"]["test_mode"] = True
    assert main.handle(p)["error_code"] == "invalid_payload"
    assert not calls


def test_failure_after_write_dispatch_is_uncertain(monkeypatch):
    import toolbox

    def fail(*a, **kw):
        raise toolbox.Failure("provider_unavailable", "Request failed", dispatched=True)

    monkeypatch.setattr(toolbox, "invoke", fail)
    r = main.handle(envelope("increment"))
    assert not r["ok"] and not r["definitely_no_external_effect"]
    assert r["external_effect_status"] == "timeout_unknown" and not r["retryable"]


def test_connection_cannot_override_executable_or_namespace(monkeypatch):
    calls = fake(monkeypatch, None)
    p = envelope("get")
    p["action"]["target"]["connection"]["config"]["command"] = "/tmp/evil"
    assert main.handle(p)["error_code"] == "invalid_connection"
    p = envelope("get", {"namespace": "evil"})
    assert main.handle(p)["error_code"] == "invalid_payload"
    assert not calls


def test_hash_and_list_commands_preserve_array_arguments(monkeypatch):
    calls = fake(monkeypatch, 2)
    assert main.handle(envelope("hash_set", {"fields": {"a": "one two", "b": "$key"}}))["ok"]
    assert calls[-1][2] == ["HSET", "$key", "$items"]
    assert calls[-1][3]["items"] == ["a", "one two", "b", "$key"]
    assert main.handle(envelope("list_push", {"values": ["a b", "\n"], "direction": "right"}))["ok"]
    assert calls[-1][2] == ["RPUSH", "$key", "$items"]
    assert calls[-1][3]["items"] == ["a b", "\n"]


def test_raw_commands_and_unbounded_ranges_rejected(monkeypatch):
    calls = fake(monkeypatch, [])
    assert (
        main.handle(envelope("execute", {"command": "FLUSHALL"}))["error_code"] == "unknown_action"
    )
    assert main.handle(envelope("list_range", {"count": 101}))["error_code"] == "invalid_payload"
    assert main.handle(envelope("list_range", {"start": -1}))["error_code"] == "invalid_payload"
    assert not calls


def test_nx_not_applied_is_success(monkeypatch):
    fake(monkeypatch, None)
    r = main.handle(envelope("set", {"value": "a", "condition": "nx"}))
    assert r["ok"] and not r["result"]["applied"]
