# Toolbox Dataset Connector

`flowsteward.toolbox-dataset-connector` is the canonical reference extension for Flow Steward dataset connectors.
It is meant to be copied by the next connector author, so the contract, file layout, and runtime boundaries are intentionally explicit and portable.

## What This Extension Demonstrates

This bundle is the reference for the first-release dataset connector pattern:

- Flow Steward Core owns connection records, secrets, permissions, lifecycle, invocation, and dataset projection.
- The extension owns connector-specific runtime behavior, source catalog projection, query validation rules, and response normalization.
- The extension contract is self-describing from `extension.yaml`, schemas, manifests, and this README. A new author should not need to read Flow Steward Core internals to understand how to build the next connector.

## Requirements

This release speaks the host contract `extension_host_v2` with its final
execution scope (`group_id`, `for_each_id`, `step_id`, `step_execution_id`)
and is built on `flowsteward-extension-sdk` 0.4.0. A request with another
contract, a missing scope key, both a Group and a For each as its owner, or a
step without its execution is refused (`invalid_host_envelope`) before Toolbox
is started or a database is reached. Install it on a Flow Steward Core that
speaks this contract; an older Core does not run it.

Logo: `icon.png` (the Flow Steward wave mark).

## Core vs Extension Boundary

Keep this split when building the next connector:

- Flow Steward Core should discover, validate, install, invoke, and project extension contracts.
- Flow Steward Core should not import extension Python modules or embed provider-specific SQL/runtime logic.
- The extension should translate Flow Steward connector actions such as `test_connection`, `introspect_schema`, `validate_query`, `preview_query`, `execute_template`, and `infer_output_schema` into provider-specific runtime calls.
- Provider-specific quirks should stay in the extension runtime or a narrow adapter under the extension bundle.

If a future connector requires database-specific parsing, auth mapping, or environment setup, put that logic here in the bundle, not in Core.

## Reference File Layout

Expected layout for this style of extension:

- `extension.yaml`
  Declares identity, Manifest v2 `features`, Extension Contract v2, `dataset_connectors`, `operation_manifest`, `resource_query_manifest`, schemas, and declarative UI references.
- `main.py`
  Python subprocess runtime entrypoint. Receives canonical Flow Steward action/query payloads and returns canonical Flow Steward envelopes.
- `health.py`
  Fast runtime health command.
- `schemas/`
  Portable JSON-schema-like definitions for connection config, secrets, and subscriptions.
- `ui/`
  Declarative-only UI manifest, pages, components, actions, and queries. No custom HTML, CSS, or JavaScript belongs here.
- `fixtures/`
  Dev/test-only helpers and sample data. These must not become required end-user runtime dependencies.
- `scripts/`
  Docker-only source builds, the checked-in upstream parameter-binding patch, checksum verification, integration, and smoke checks.
- `tests/`
  Extension-local tests only. Provider-specific behavior belongs here, not in global Core test suites.
- `domain/`, `handlers/`, `infrastructure/`
  Optional internal organization for non-trivial runtimes. Use these folders if runtime logic grows, instead of pushing complexity into `main.py`.

## Bundle Layout in This Extension

- `extension.yaml` declares identity, Manifest v2 `features`, Extension Contract v2, `dataset_connectors`, `operation_manifest`, `resource_query_manifest`, config schema, secrets schema, and declarative UI refs.
- `main.py` is the Python subprocess runtime. It invokes the packaged target binary with `toolbox --prebuilt=<kind> --stdio`, performs a bounded MCP handshake, and normalizes responses into Flow Steward envelopes.
- `health.py` is the extension health command.
- `schemas/config.schema.yaml` documents the connection config shape for Toolbox prebuilts.
- `schemas/secrets.schema.yaml` documents secret values passed to Toolbox as environment variables.
- `ui/` contains declarative-only UI manifest, query manifest, action manifest, and components.
- `scripts/smoke_check.py` uses a stateless MCP protocol double; production integration uses disposable PostgreSQL.
- `bin/linux-amd64/toolbox` and `bin/linux-arm64/toolbox` are pinned source builds of Google MCP Toolbox 1.3.0.
- `scripts/patches/0001-flowsteward-driver-bound-query-params.patch` adds the MCP inputs that pass values to native Toolbox `RunSQL` driver arguments.
- `THIRD_PARTY.yml`, `SHA256SUMS`, `LICENSE`, and `NOTICE` record exact provenance and verify the packaged executables.

The packaged executables are tracked with Git LFS. Contributors and CI runners
must have Git LFS installed before checkout; a normal clone then materializes
the verified binaries without any install-time or runtime download.

## Supported Connector Catalog

This package ships the portable upstream Google MCP Toolbox source set for the bundled Linux targets, excluding Oracle because it requires a separate Oracle Client/CGO runtime. MariaDB uses the compatible MySQL protocol adapter. The published dataset connector catalog is derived from the runtime capability matrix, so a source is selectable only when its packaged prebuilt exposes the schema and query tools required by this extension contract.

Important:

- End users should not need to configure a custom `toolbox_command` in the UI.
- Product runtime selects exactly one packaged binary from the normalized Linux architecture.
- Install and runtime perform no downloads and create no private database or persistent extension state.

Flow Steward Core does not import this package, does not open database drivers, and does not know Toolbox-specific SQL. Core only invokes declared extension actions through the canonical extension runtime.

## Saved Query Parameter Binding

Saved SQL uses canonical value placeholders such as `:status`. The runtime scans SQL without treating literals, quoted identifiers, comments, or PostgreSQL casts as parameters, validates values against `param_schema_jsonb`, and compiles placeholders for the selected driver. SQL text and values cross MCP separately. The patched upstream execute tools pass those values to `RunSQL`; no runtime value is quoted, escaped, formatted, or concatenated into SQL text.

The portable contract accepts only declared JSON primitives: strings, integers, finite numbers, booleans, and null. Arrays, objects, missing values, undeclared values, type mismatches, and non-finite numbers fail before Toolbox invocation. Parameters are values only and cannot select identifiers, operators, keywords, ordering directions, or SQL fragments.

## Canonical Runtime Contract

This extension is a reference for how a dataset connector should look from the outside:

- Declared connector catalog rows live under `runtime.extension_contract_v2.dataset_connectors[*].connector_catalog`.
- Connection settings come from `connection_schema`.
- Secret values come from `secret_schema`.
- Operations are documented under `operation_manifest` with `description`, `required_scopes`, `result_fields`, and `error_codes`.
- Read-only UI data sources are documented under `resource_query_manifest`.
- All public query/action responses return Flow Steward's canonical envelope:

```json
{
  "ok": true,
  "result": {},
  "commands": [],
  "events": [],
  "reload": [],
  "errors": []
}
```

Failures use `errors[]` objects with stable `code`, `message`, and `path` fields. Provider-specific Toolbox details stay under clearly named `metadata` fields.

## Schema Snapshot

The schema introspection output is `dataset_schema_snapshot.v1`:

```json
{
  "schema_version": "dataset_schema_snapshot.v1",
  "source_kind": "postgres",
  "resources": [
    {
      "resource_id": "orders",
      "name": "orders",
      "resource_type": "table",
      "selectable": true,
      "columns": [
        {
          "name": "order_id",
          "source_type": "INTEGER",
          "value_type": "integer",
          "nullable": true,
          "default_value": null,
          "primary_key": true,
          "primary_key_ordinal": 1,
          "ordinal": 0,
          "metadata": {}
        }
      ],
      "indexes": [],
      "constraints": {"primary_key": ["order_id"]},
      "metadata": {"toolbox_schema_name": "public"}
    }
  ],
  "metadata": {
    "connector_id": "toolbox_postgres",
    "toolbox_prebuilt": "postgres",
    "resource_count": 1
  }
}
```

## Local Developer Loop

Run the standalone extension suite in Docker:

```bash
docker compose -f infra/docker/docker-compose.yaml -f infra/docker/docker-compose.dev.yaml run --rm --no-deps fs-app \
  python -m core.entrypoints.cli tooling extensions test flowsteward.toolbox-dataset-connector
```

The check proves:

- extension health works
- Google MCP Toolbox is invoked through bounded MCP STDIO with `--prebuilt=postgres --stdio`
- schema introspection returns normalized typed resources
- saved query-template validation and bounded preview use explicit test injection

Run the packaged binary against a disposable PostgreSQL container separately:

```bash
extensions/flowsteward_toolbox_dataset_connector/scripts/run_postgres_integration.sh
```

Rebuild both packaged targets from pinned upstream source and verify checksums:

```bash
extensions/flowsteward_toolbox_dataset_connector/scripts/build_toolbox_binaries.sh
docker run --rm -v "$PWD/extensions/flowsteward_toolbox_dataset_connector:/extension:ro" \
  python:3.12.10-slim-bookworm python /extension/scripts/verify_toolbox_artifacts.py \
  --root /extension
```

The build runs entirely in a pinned Docker image. It verifies the upstream commit,
runs `git apply --check` for the parameter-binding patch, applies it, runs the
affected Go tests, removes Oracle registration, builds both Linux targets, and
regenerates checksums. Network access is used only by the explicit build, never
by extension install or runtime.

## Dev Fixtures vs Product Runtime

Keep this distinction sharp:

- `fixtures/fake_toolbox.py` is a stateless test-only MCP process; it never persists data.
- The fake is selected only through direct test dependency injection; manifest, config, and environment values cannot replace the packaged production command.
- Test fixtures are not part of the public product contract and never appear as runtime fallback paths.
- If a future connector needs a smoke adapter, document it the same way: explicit, isolated, and clearly non-product.

## Copying This Pattern

To build the next dataset connector, copy this bundle and replace only the connector-specific adapter mapping:

- Keep the manifest sections portable: `dataset_connectors`, `operation_manifest`, `resource_query_manifest`, schemas, UI refs, and `features`.
- Keep query/action outputs canonical and typed through `result_fields` plus explicit `error_codes`.
- Put provider behavior in the extension runtime or a narrow runtime adapter, not in Flow Steward core services.
- Add an explicitly injected stateless protocol fixture plus a smoke check before exposing the connector in UI/API.
- Keep extension-local tests under the bundle and keep global tests provider-neutral.
- Prefer small internal modules under `domain/`, `handlers/`, or `infrastructure/` once runtime complexity grows; do not turn `main.py` into an unstructured monolith.

## Author Checklist

Before calling the next dataset connector "reference-ready", check:

- `extension.yaml` is understandable without reading Core code.
- Connector catalog rows have stable IDs, names, and query languages.
- Config and secret schemas are enough to render the user form.
- Operation/query manifests declare typed result fields and explicit error codes.
- Runtime returns only canonical envelopes.
- UI is declarative-only.
- Smoke check runs without production credentials.
- Provider-specific tests live inside the extension bundle.
- Dev-only fixtures are clearly documented as non-product paths.

## Binary Provenance

The pinned upstream release is MCP Toolbox for Databases `v1.3.0`, commit
`b0010060a939455d91e4f8ba62dc3e72b1892469`. Google publishes a
287,397,352-byte Linux amd64 artifact for this release and no Linux arm64
artifact. Both targets are therefore built from the same pinned source in
Docker with the checked-in Flow Steward parameter-binding patch, excluding
Oracle, and stripped with reproducible Go flags. Exact toolchain versions,
source URL, patch path, and checksums live in `THIRD_PARTY.yml`.
