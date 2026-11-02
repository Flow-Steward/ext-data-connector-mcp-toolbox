# Legacy shared SQL connector build tooling

This repository contains legacy shared source templates and build tooling for
[Flow Steward](https://github.com/Flow-Steward/flow-steward-app) SQL connectors
built on [Google MCP Toolbox for Databases](https://github.com/googleapis/mcp-toolbox).
It is **not an installable common extension**. Install the package published by
the repository for the database you use; each database has its own extension,
native driver build, release version and runtime-target ZIPs.

| Database | Extension repository | Package identity |
| --- | --- | --- |
| PostgreSQL, AlloyDB and Cloud SQL for PostgreSQL | [ext-data-postgres](https://github.com/Flow-Steward/ext-data-postgres) | `flowsteward.data-connector-mcp-toolbox-postgres` |
| MySQL, MariaDB and Cloud SQL for MySQL | [ext-data-mysql](https://github.com/Flow-Steward/ext-data-mysql) | `flowsteward.data-connector-mcp-toolbox-mysql` |
| Microsoft SQL Server and Cloud SQL for SQL Server | [ext-data-mssql](https://github.com/Flow-Steward/ext-data-mssql) | `flowsteward.data-connector-mcp-toolbox-mssql` |
| SQLite | [ext-data-sqlite](https://github.com/Flow-Steward/ext-data-sqlite) | `flowsteward.data-connector-mcp-toolbox-sqlite` |
| ClickHouse | [ext-data-clickhouse](https://github.com/Flow-Steward/ext-data-clickhouse) | `flowsteward.data-connector-mcp-toolbox-clickhouse` |
| Snowflake | [ext-data-snowflake](https://github.com/Flow-Steward/ext-data-snowflake) | `flowsteward.data-connector-mcp-toolbox-snowflake` |
| SingleStore | [ext-data-singlestore](https://github.com/Flow-Steward/ext-data-singlestore) | `flowsteward.data-connector-mcp-toolbox-singlestore` |
| OceanBase | [ext-data-oceanbase](https://github.com/Flow-Steward/ext-data-oceanbase) | `flowsteward.data-connector-mcp-toolbox-oceanbase` |
| Spanner (GoogleSQL and PostgreSQL dialects) | [ext-data-spanner](https://github.com/Flow-Steward/ext-data-spanner) | `flowsteward.data-connector-mcp-toolbox-spanner` |

A shared source template, pinned Toolbox version or coordinated maintenance
batch does not mean that one extension bundles the other databases' drivers.
The build tooling selects the source and tool packages required by each
variant. The database repository's current README, manifests and release assets
are the authority for installation and supported behavior.

Existing tags and release assets through the 1.2 series remain historical
artifacts. They are not replaced, retagged or used as a recommendation to install
a generic Data Connector MCP Toolbox extension. The sections below preserve
the shared implementation and reproducible-build reference for maintainers.

## Shared implementation reference: workflow database writes

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

## Shared template requirements

Every variant speaks the host contract `extension_host_v2` with its final
execution scope and is built on `flowsteward-extension-sdk` 0.4.0 (the wheel
for tests is `connector/dev-wheels/`); an older Flow Steward Core does not run
it. Every variant carries the logo `connector/icon.png` (the Flow Steward wave
mark).

## How the build tooling is organised

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

## Extending the shared template

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
5. Maintain and validate the resulting extension in its own database repository.
   Publish its package there, then register that repository in the
   [catalog](https://github.com/Flow-Steward/extensions).

## Fixing a bug, and not breaking another database

The legacy factory renders the shared `connector/` template into the variants
listed in `variants/`. A template change can therefore affect several rendered
outputs. The existing checks below describe the shared factory's validation
surfaces; their presence is not evidence that a particular revision has passed
or that independent database repositories have been updated:

| Check | Runs | Catches |
| --- | --- | --- |
| `scripts/check_family.py` | once | a connection type in no variant or in two, duplicate ids, a variant without `sums/` |
| connector logic tests (`-m "not packaged"`) | once, for all 16 types | a code change that breaks any database's behaviour |
| build + `sums/` | per variant | a binary that no longer reproduces |
| `scripts/smoke_variant.py` | per variant, both architectures | a binary missing a type one of its prebuilts needs |
| packaged tests (`-m "packaged or variant_contract"`) | per variant, inside the rendered extension | wrong architecture, checksums, or a variant offering what it was not built for |
| `scripts/live_check.py` | variants with `live_checks:` | schema reading and parameter binding against a real PostgreSQL and MySQL |
| `scripts/catalog_check.py` | per variant | an archive the extension catalog would refuse |

Within this factory, identities come from the variant file name, native types
from Toolbox's prebuilt YAML, and runtime offers from `variant.json`. These
inputs support reviewing related variants together. Rendering a template here
does not update or release the independent database repositories.

## Shared maintenance and release ownership

For a shared SDK, Toolbox pin or adapter fix, use `variants/` as the inventory
of factory variants and review `connector/`, the source patches and affected
`sums/<name>.sha256` together. The existing render, build, package and check
scripts operate on this repository's `build/<name>/` outputs. There is no
cross-repository update or publication command in this tooling.

Apply the applicable change separately in each affected database repository,
review its database-specific behavior, run its required checks, and publish its
own version and architecture packages. A coordinated batch may share a source
revision or dependency pin while retaining separate package identities, binary
contents, checksums and release histories. Do not copy another database's
executable into an extension.

The retained historical Release workflow reads `connector/extension.yaml` and
was designed to publish every variant under one tag in this repository. It is
preserved as build history, not the release path for the independent database
extensions. Publish new database releases from the repositories linked above;
leave this repository's existing tags and assets unchanged.

## Licence

Apache-2.0. Google MCP Toolbox is Apache-2.0; see `connector/NOTICE` and
`connector/THIRD_PARTY.yml`.
