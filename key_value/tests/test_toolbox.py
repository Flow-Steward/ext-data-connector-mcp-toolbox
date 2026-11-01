"""Exercise real subprocess framing, cleanup, limits and data escaping."""

import inspect
from pathlib import Path
import time
import pytest
import toolbox
from validation import Failure

CONFIG = {
    "host": "redis.example",
    "port": 6379,
    "database": 0,
    "namespace": "workflow",
    "tls": True,
    "request_timeout_seconds": 15,
}


def fake_binary(tmp_path, monkeypatch, body):
    script = tmp_path / "fake-toolbox"
    script.write_text("#!/usr/local/bin/python\nimport json,sys,os,time\n" + body)
    script.chmod(0o700)
    monkeypatch.setattr(toolbox, "_binary", lambda: str(script))
    monkeypatch.setattr(toolbox, "_endpoint", lambda config: "127.0.0.1")
    return script


INIT = """
first=json.loads(sys.stdin.readline())
print(json.dumps({'jsonrpc':'2.0','id':1,'result':{'protocolVersion':'2025-06-18'}}),flush=True)
"""


def test_stdin_writes_have_a_deadline():
    assert "deadline" in inspect.signature(toolbox._send).parameters


def test_literal_secrets_are_not_expanded_and_config_is_removed(tmp_path, monkeypatch):
    fake_binary(
        tmp_path,
        monkeypatch,
        INIT
        + """
sys.stdin.readline()
call=json.loads(sys.stdin.readline())
path=sys.argv[sys.argv.index('--config')+1]
raw=open(path).read()
source,tool=[json.loads(x) for x in raw.split('\\n---\\n')]
value={'password':source['password'],'command':tool['commands'][0],'args':call['params']['arguments'],'mode':os.stat(path).st_mode & 0o777,'path':path,'raw':raw}
print(json.dumps({'jsonrpc':'2.0','id':2,'result':{'content':[{'type':'text','text':json.dumps(value)}]}}),flush=True)
""",
    )
    secret = 'x${HOME}:\n" secret'
    value = toolbox.invoke(
        CONFIG,
        {"password": secret},
        ["SET", "$key", "$value"],
        {"key": "scope:key", "value": "$key\n FLUSHALL"},
        timeout_seconds=2,
    )
    assert value["password"] == secret
    assert "${HOME}" not in value["raw"]
    assert value["command"] == ["SET", "$key", "$value"]
    assert value["args"]["value"] == "$key\n FLUSHALL"
    assert value["mode"] == 0o600
    assert not Path(value["path"]).exists() and not Path(value["path"]).parent.exists()


def test_pipe_backpressure_cannot_bypass_deadline(tmp_path, monkeypatch):
    fake_binary(tmp_path, monkeypatch, INIT + "time.sleep(30)\n")
    started = time.monotonic()
    with pytest.raises(Failure) as failure:
        toolbox.invoke(
            CONFIG,
            {},
            ["SET", "$key", "$value"],
            {"key": "key", "value": "x" * 250000},
            timeout_seconds=0.3,
        )
    assert failure.value.code == "timeout" and failure.value.dispatched
    assert time.monotonic() - started < 3


def test_oversized_output_is_bounded(tmp_path, monkeypatch):
    fake_binary(
        tmp_path,
        monkeypatch,
        INIT
        + """
sys.stdin.readline()
sys.stdin.readline()
print('x'*1200000,flush=True)
""",
    )
    with pytest.raises(Failure) as failure:
        toolbox.invoke(CONFIG, {}, ["GET", "$key"], {"key": "key"}, timeout_seconds=2)
    assert failure.value.code == "response_too_large" and failure.value.dispatched


def test_provider_diagnostics_do_not_leak_secrets(tmp_path, monkeypatch):
    fake_binary(
        tmp_path,
        monkeypatch,
        INIT
        + """
sys.stdin.readline()
sys.stdin.readline()
print(json.dumps({'jsonrpc':'2.0','id':2,'result':{'isError':True,'content':[{'type':'text','text':'WRONGTYPE secret-password'}]}}),flush=True)
""",
    )
    with pytest.raises(Failure) as failure:
        toolbox.invoke(
            CONFIG,
            {"password": "secret-password"},
            ["GET", "$key"],
            {"key": "key"},
            timeout_seconds=2,
        )
    assert failure.value.code == "wrong_type"
    assert "secret-password" not in str(failure.value)


def test_public_plaintext_endpoint_is_rejected(monkeypatch):
    monkeypatch.setattr(toolbox, "resolve_pinned_ips", lambda *a, **k: ("8.8.8.8",))
    with pytest.raises(Failure) as failure:
        toolbox._endpoint({**CONFIG, "tls": False})
    assert failure.value.code == "network_blocked"


def test_private_permission_matches_sdk_boolean_spellings(monkeypatch):
    monkeypatch.setattr(toolbox, "resolve_pinned_ips", lambda *a, **k: ("127.0.0.1",))
    monkeypatch.setenv("FS_ALLOW_PRIVATE_REMOTE_URLS", " true ")
    assert toolbox._endpoint({**CONFIG, "tls": False}) == "127.0.0.1"
