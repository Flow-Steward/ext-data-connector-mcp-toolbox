"""Opt-in real Redis and Valkey checks using the packaged Toolbox binary."""

import json
from pathlib import Path
from uuid import uuid4
import pytest
import main
from test_runtime import envelope

LOCAL = Path(__file__).with_name("live-kv.local.json")
SERVERS = json.loads(LOCAL.read_text()) if LOCAL.exists() else []


@pytest.mark.parametrize(
    "server", SERVERS or [None], ids=lambda s: s["kind"] if s else "not-configured"
)
def test_live_lifecycle(server, monkeypatch):
    if server is None:
        pytest.skip("Provide ignored tests/live-kv.local.json for disposable servers")
    monkeypatch.setenv("FS_ALLOW_PRIVATE_REMOTE_URLS", "1")
    key = "case-" + uuid4().hex

    def call(action, args=None, *, project="p", account="a", check=True):
        p = envelope(action, {"key": key, **(args or {})}, project=project, kind=server["kind"])
        p["runtime_context"]["account_id"] = account
        p["action"]["target"]["connection"]["config"].update(host=server["host"], tls=False)
        p["action"]["target"]["connection"]["secrets"] = {"password": server.get("password", "")}
        r = main.handle(p)
        if check:
            assert r["ok"], r
            return r["result"]
        return r

    assert call("get")["found"] is False
    assert not call("set", {"value": "absent", "condition": "xx"})["applied"]
    assert call("set", {"value": ""})["applied"]
    assert call("set", {"value": "", "condition": "xx"})["applied"]
    assert call("get")["value"] == "" and call("get")["found"]
    value = 'line 1\n$other ${NOT_SET} " end'
    call("set", {"value": value, "ttl_seconds": 60})
    assert call("get")["value"] == value
    assert 0 < call("ttl")["value"] <= 60
    assert call("set", {"value": "must-not-win", "condition": "nx"})["applied"] is False
    assert call("get")["value"] == value
    assert call("get", project="other")["found"] is False
    assert call("get", account="other")["found"] is False
    assert call("delete", project="other")["applied"] is False
    assert call("get")["value"] == value
    assert call("delete")["value"] == 1
    assert call("ttl")["value"] == -2
    assert call("increment", {"amount": 3})["value"] == 3
    assert call("increment", {"amount": -1})["value"] == 2
    assert call("exists")["value"] == 1
    call("set", {"value": "9007199254740991"})
    overflow = call("increment", check=False)
    assert overflow["error_code"] == "invalid_provider_response"
    assert overflow["external_effect_status"] == "timeout_unknown" and not overflow["retryable"]
    assert call("get")["value"] == "9007199254740992"
    assert call("expire", {"ttl_seconds": 60})["applied"]
    call("delete")
    assert call("hash_set", {"fields": {"a": "hello world", "b": "$key\n"}})["value"] == 2
    assert call("hash_set", {"fields": {"a": "updated"}})["value"] == 0
    assert call("hash_get", {"field": "a"})["value"] == "updated"
    assert call("hash_get", {"field": "missing"})["found"] is False
    assert call("hash_get_all")["value"] == {"a": "updated", "b": "$key\n"}
    wrong = call("get", check=False)
    assert not wrong["ok"] and wrong["error_code"] in {"wrong_type", "provider_unavailable"}
    assert call("hash_delete", {"fields": ["a", "b"]})["value"] == 2
    assert call("hash_get_all")["value"] == {}
    assert call("list_push", {"values": ["a b", "\n"]})["value"] == 2
    assert call("list_length")["value"] == 2
    assert call("list_range", {"count": 1})["value"] == ["a b"]
    assert call("list_pop")["value"] == "a b"
    assert call("list_pop", {"direction": "right"})["value"] == "\n"
    assert call("list_pop")["value"] is None
    call("list_push", {"values": ["a", "b"], "direction": "left"})
    assert call("list_range")["value"] == ["b", "a"]
    assert call("delete")["value"] == 1
    assert call("delete")["value"] == 0
