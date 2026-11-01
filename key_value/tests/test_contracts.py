"""Public host-v2 contract safety and operation parity checks."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
READS = {
    "get",
    "exists",
    "ttl",
    "hash_get",
    "hash_get_all",
    "list_range",
    "list_length",
}
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
OPERATIONS = READS | WRITES
CONFIG = {"host", "port", "database", "namespace", "tls", "request_timeout_seconds"}


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


def test_identity_and_host_contract():
    manifest = load("extension.yaml")
    descriptor = load("extension-descriptor.yaml")
    assert manifest["extension_id"] == descriptor["extension_id"] == "flowsteward.redis-valkey"
    assert manifest["version"] == descriptor["release_version"] == "1.0.0"
    assert manifest["kind"] == "tool_provider"
    assert manifest["required_scopes"] == ["extension:invoke"]
    assert manifest["features"] == ["tool", "action"]
    assert manifest["egress"] == {"connection_fields": ["redis.host", "valkey.host"]}
    assert manifest["runtime"] == descriptor["runtime"]
    assert manifest["runtime"]["contract_version"] == "extension_host_v2"
    assert "dataset_provider" not in str(manifest)


def test_connection_types_are_explicit_bounded_and_secret_safe():
    connections = load("contracts/connection_types.yaml")["connection_types"]
    assert {c["connection_type_id"] for c in connections} == {"redis", "valkey"}
    for connection in connections:
        config = connection["config_schema"]
        assert config["additionalProperties"] is False
        assert set(config["properties"]) == CONFIG
        assert config["required"] == ["host"]
        props = config["properties"]
        assert props["port"]["minimum"] == 1
        assert props["port"]["maximum"] == 65535
        assert props["port"]["default"] == 6379
        assert props["database"]["minimum"] == 0
        assert props["database"]["maximum"] == 15
        assert props["namespace"]["pattern"] == "^[A-Za-z0-9_-]{1,64}$"
        assert props["tls"]["default"] is True
        assert props["request_timeout_seconds"]["maximum"] == 30
        secret = connection["secret_schema"]
        assert secret["additionalProperties"] is False
        assert set(secret["properties"]) == {"username", "password"}
        assert not secret.get("required")
        assert connection["capabilities"]["workflow_trigger"] is False
        assert connection["safety_profile"]["stores_secret_values"] is False


def test_operation_action_form_parity_and_connected_inputs():
    operations = load("contracts/operation_manifest.yaml")["operations"]
    actions = load("ui/actions/actions.yaml")["actions"]
    forms = load("contracts/step_ui_manifest.yaml")["forms"]
    assert {o["operation_id"] for o in operations} == OPERATIONS
    assert {a["action_id"] for a in actions} == OPERATIONS
    assert {f["operation_id"] for f in forms} == OPERATIONS
    assert len(operations) == len(actions) == len(forms) == 15
    action_map = {a["action_id"]: a for a in actions}
    form_map = {f["operation_id"]: f for f in forms}
    for operation in operations:
        operation_id = operation["operation_id"]
        assert operation["operation_kind"] == "action"
        assert operation["connection_type_ids"] == ["redis", "valkey"]
        inputs = {item["name"]: item for item in operation["inputs"]}
        assert inputs["key"]["required"] is True
        assert inputs["connection_ref"]["required"] is True
        action = action_map[operation_id]
        assert action["required_scopes"] == ["extension:invoke"]
        assert action["handler"] == {"mode": "extension"}
        assert {p["name"] for p in action["parameters"]} == set(inputs)
        assert {p["name"] for p in form_map[operation_id]["fields"]} == set(inputs) - {
            "connection_ref"
        }
        assert operation["outputs"] == [
            {"name": "value", "value_type": "json"},
            {"name": "found", "value_type": "boolean"},
            {"name": "applied", "value_type": "boolean"},
            {"name": "key", "value_type": "text"},
        ]
        assert action["result_fields"] == operation["result_fields"]
        assert action["error_codes"] == operation["error_codes"]


def test_only_mutations_declare_durable_suppressed_effects():
    effects = load("extension.yaml")["external_effects"]
    assert {effect["operation_id"] for effect in effects} == WRITES
    assert len(effects) == len(WRITES)
    for effect in effects:
        assert effect["effect_kind"] == "database_write"
        assert effect["idempotency"] == "required"
        assert effect["test_mode_behavior"] == "suppress"


def test_bounded_inputs_and_defaults():
    ops = {
        o["operation_id"]: {i["name"]: i for i in o["inputs"]}
        for o in load("contracts/operation_manifest.yaml")["operations"]
    }
    assert ops["set"]["value"]["required"] is True
    assert ops["set"]["value"]["schema"]["maxLength"] == 65536
    assert ops["set"]["condition"]["schema"] == {
        "type": "string",
        "enum": ["always", "nx", "xx"],
        "default": "always",
    }
    assert ops["expire"]["ttl_seconds"]["required"] is True
    assert ops["set"]["ttl_seconds"]["schema"]["maximum"] == 2147483647
    assert ops["increment"]["amount"]["schema"]["maximum"] == 9007199254740991
    assert ops["hash_set"]["fields"]["schema"]["not"] == {"const": {}}
    assert "1–64 fields" in ops["hash_set"]["fields"]["schema"]["description"]
    assert ops["hash_set"]["fields"]["schema"]["additionalProperties"] == {
        "type": "string",
        "maxLength": 65536,
    }
    assert ops["hash_delete"]["fields"]["schema"]["maxItems"] == 64
    assert ops["list_push"]["values"]["schema"]["maxItems"] == 64
    assert ops["list_range"]["count"]["schema"]["maximum"] == 100
    assert ops["list_push"]["direction"]["schema"]["default"] == "right"
    assert ops["list_pop"]["direction"]["schema"]["default"] == "left"


def test_ui_resolves_two_connection_forms_and_uses_masked_secrets():
    manifest = load("ui/ui_manifest.yaml")
    forms = []
    for page_ref in manifest["pages"]:
        page_path = ROOT / "ui" / page_ref["ref"]
        page = yaml.safe_load(page_path.read_text())
        for component_ref in page["components"]:
            component = yaml.safe_load((page_path.parent / component_ref["ref"]).read_text())
            if component["type"] == "connection_form":
                forms.append(component)
    assert {f["data"]["connection_type"] for f in forms} == {"redis", "valkey"}
    for form in forms:
        assert set(form["data"]["config_fields"]) == CONFIG
        assert set(form["data"]["secret_fields"]) == {"username", "password"}
        assert {f["path"] for f in form["fields"] if f["widget"] == "secret"} == {
            "username",
            "password",
        }
