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

## Workflow database writes

The PostgreSQL, MySQL/MariaDB and Microsoft SQL Server extensions provide
**Execute database write** (`execute_write`) alongside their read-only dataset
connectors. Create a project connection of type **Toolbox SQL writer**, select
its database type and credentials, then select that connection in an Extension
tools workflow step. Existing dataset connections and saved SELECT queries stay
read-only; the write action uses an explicit project connection.

The action accepts one `INSERT`, `UPDATE` or `DELETE` statement. An `INSERT`
can use the database's upsert syntax. Pass values through named placeholders
and typed parameters rather than concatenating them into SQL:

```yaml
sql: UPDATE products SET stock = :stock WHERE sku = :sku
params: {stock: 12, sku: A-1}
param_schema:
  type: object
  properties:
    stock: {type: integer}
    sku: {type: string}
```

Supported values are strings, integers, finite numbers, booleans and null.
DDL, transaction scripts and multiple statements are rejected. Test mode
validates the input and suppresses writes. The host's external-effect ledger
tracks the operation; a transport failure after dispatch reports
`write_outcome_unknown` and must be inspected before retrying. It does not
promise exactly-once database execution.

Use bound parameters for values containing backslashes rather than SQL string
escape syntax, whose meaning depends on the server's SQL mode. Executable MySQL
comments are rejected; ordinary comments and quoted values are preserved.

Results contain `status`, `rows` and `returned_row_count`. This count describes
returned rows, **not affected rows**. A successful write without a result set
returns an empty list; zero matching updates are still successful execution.

Other database variants do not expose the write action. No database triggers
are provided. The shared adapter and database-specific parameter binding are
tested independently; live database coverage is reported separately.

## Redis and Valkey workflow storage

`key_value/` is the standalone `flowsteward.redis-valkey` extension. It provides
15 workflow actions for keys, TTL, conditional SET, counters, hashes and basic
lists, with separate Redis and Valkey project connection types. Both use the
packaged Redis-compatible Toolbox driver. It does not use the SQL dataset
contract, change the SQL variants, or require Core changes.

Build its minimal, pinned native binaries and package each architecture:

```sh
sh scripts/build_key_value_toolbox.sh
python3 key_value/scripts/package_extension.py --runtime-target linux-amd64
python3 key_value/scripts/package_extension.py --runtime-target linux-arm64
```

The archives are written to `dist/`. Each contains one architecture, its native
executable declaration, provenance/checksums and license. The source excludes
compiled binaries from git; build them before running the extension gate:

```sh
# Run from a Flow Steward checkout, using this repository's absolute path.
./core/entrypoints/cli/scripts/lint.sh --checks extension-static,extension-tests --extension-root /absolute/path/to/this/repository/key_value
```

See [Redis/Valkey setup, operations and limits](key_value/README.md). The SQL
family's renderer and release matrix remain separate from this new package.

## Requirements

Every variant speaks the host contract `extension_host_v2` with its final
execution scope and is built on `flowsteward-extension-sdk` 0.4.0 (the wheel
for tests is `connector/dev-wheels/`); an older Flow Steward Core does not run
it. Every variant carries the logo `connector/icon.png` (the Flow Steward wave
mark).

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

## Fixing a bug, and not breaking another database

The connector code is shared, so a fix in `connector/` reaches every variant, and
the family releases under one version. CI runs on every push and pull request,
so a change made for MySQL is proven against PostgreSQL before it is merged:

| Check | Runs | Catches |
| --- | --- | --- |
| `scripts/check_family.py` | once | a connection type in no variant or in two, duplicate ids, a variant without `sums/` |
| connector logic tests (`-m "not packaged"`) | once, for all 16 types | a code change that breaks any database's behaviour |
| build + `sums/` | per variant | a binary that no longer reproduces |
| `scripts/smoke_variant.py` | per variant, both architectures | a binary missing a type one of its prebuilts needs |
| packaged tests (`-m "packaged or variant_contract"`) | per variant, inside the rendered extension | wrong architecture, checksums, or a variant offering what it was not built for |
| `scripts/live_check.py` | variants with `live_checks:` | schema reading and parameter binding against a real PostgreSQL and MySQL |
| `scripts/catalog_check.py` | per variant | an archive the extension catalog would refuse |

Nothing is listed by hand per variant: ids come from the file name, the binary's
types from Toolbox's own prebuilt YAML, the runtime's offer from `variant.json`.
Adding a variant file is all it takes for every check to cover it.

## Release

Push a tag equal to `connector/extension.yaml`'s version (`v1.0.1`). The
**Release** workflow builds every variant in parallel, refuses binaries that
differ from `sums/`, and publishes one GitHub Release with
`<extension_id>-<version>-<target>.zip` for each variant and target.

## Licence

Apache-2.0. Google MCP Toolbox is Apache-2.0; see `connector/NOTICE` and
`connector/THIRD_PARTY.yml`.
