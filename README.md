# Flow Steward data connectors for Google MCP Toolbox

Database drivers for [Flow Steward](https://github.com/Flow-Steward/flow-steward-app),
built on [Google MCP Toolbox for Databases](https://github.com/googleapis/mcp-toolbox).
Each database family is its own extension, installed from
**Extensions → Marketplace** — install only the ones you use.

| Extension | Connection types |
| --- | --- |
| `flowsteward.data-connector-mcp-toolbox-postgres` | PostgreSQL, AlloyDB Omni, AlloyDB for PostgreSQL, Cloud SQL for PostgreSQL |
| `flowsteward.data-connector-mcp-toolbox-mysql` | MySQL, MariaDB, Cloud SQL for MySQL |
| `flowsteward.data-connector-mcp-toolbox-mssql` | Microsoft SQL Server, Cloud SQL for SQL Server |
| `flowsteward.data-connector-mcp-toolbox-spanner` | Spanner (GoogleSQL), Spanner (PostgreSQL) |
| `flowsteward.data-connector-mcp-toolbox-sqlite` | SQLite |
| `flowsteward.data-connector-mcp-toolbox-clickhouse` | ClickHouse |
| `flowsteward.data-connector-mcp-toolbox-snowflake` | Snowflake |
| `flowsteward.data-connector-mcp-toolbox-singlestore` | SingleStore |
| `flowsteward.data-connector-mcp-toolbox-oceanbase` | OceanBase |

This repository is also **the worked example of a Flow Steward data connector**:
copy it to build a driver for another database.

## How it is organised

- `connector/` — the one shared implementation: the extension runtime
  (`main.py`), schemas, declarative UI and tests. It knows every database above.
- `variants/<name>.yaml` — one file per extension: its name, card text and the
  Toolbox *prebuilt configurations* it offers.
- `scripts/render_variant.py` — turns `connector/` into the extension
  `flowsteward.data-connector-mcp-toolbox-<name>`, offering only that variant's
  connection types.
- `scripts/build_toolbox.sh` — compiles Toolbox with **only** the source and tool
  types the variant's prebuilt configurations use. They are read from Toolbox's
  own prebuilt YAML, so a variant never ships a driver it cannot offer. A
  single-database binary is ~30 MB, against ~125 MB for all 42 Toolbox sources.
- `sums/<name>.sha256` — the binaries a release must reproduce byte for byte;
  pinned Toolbox commit, Go image and build epoch make that possible.
- `scripts/package_variant.py` — one archive per runtime target
  (`linux-amd64`, `linux-arm64`), in the format Flow Steward's installer expects.

## Add another database

Google MCP Toolbox ships ~40 sources; this repository offers the ones whose SQL
execution our parameter-binding patch (`scripts/patches/`) covers.

1. Find the Toolbox prebuilt configuration for it under
   `internal/prebuiltconfigs/tools/` (for example `oracle.yaml`).
2. Add its connection type to `connector/extension.yaml` (`connector_catalog`)
   and to `connector/schemas/config.schema.yaml`, and teach `connector/main.py`
   anything it needs (parameter style, required settings).
3. Add `variants/<name>.yaml` with `prebuilts: [<prebuilt>]`.
4. Build it: `python3 scripts/render_variant.py <name> && sh scripts/build_toolbox.sh <name>`,
   then record `sums/<name>.sha256` (`cd build/<name> && sha256sum bin/*/toolbox`).
5. Tag a release. Then add the new extension to the
   [catalog](https://github.com/Flow-Steward/extensions) with one entry file.

## Release

Push a tag equal to `connector/extension.yaml`'s version (`v1.0.1`). The
**Release** workflow builds every variant in parallel, refuses binaries that
differ from `sums/`, and publishes one GitHub Release with
`<extension_id>-<version>-<target>.zip` for each variant and target.

## Licence

Apache-2.0. Google MCP Toolbox is Apache-2.0; see `connector/NOTICE` and
`connector/THIRD_PARTY.yml`.
