# Changelog

## 1.1.2

- A saved query may use SQL keywords before a parenthesis: `JOIN … USING (id)`,
  `ON (…)`, `EXISTS (subquery)` and `IN (…)`, including a plain `IN ('open', 'paid')`
  list. The read-only check took each of them for a call to an unknown function and
  refused the query. A name that does call something must still be a known
  read-only function, so `nextval(…)`, `pg_sleep(…)` or `dblink_exec(…)` inside
  those parentheses are refused as before.

## 1.1.1

- The logo (`icon.png`) now has a transparent background; in 1.1.0 the Flow Steward wave sat on a black box on dark themes.

## 1.1.0

- Speaks the final extension host contract `extension_host_v2`
  (`runtime.contract_version`) and is built on `flowsteward-extension-sdk` 0.4.0.
  A request of another contract, with a missing execution-scope key
  (`group_id`, `for_each_id`, `step_id`, `step_execution_id`), with both a Group
  and a For each as its owner, or with a step but no step execution, is refused
  with `invalid_host_envelope` before Toolbox is started. An older Flow Steward
  does not run this release.
- Works the same for a step at the root, in a Group or in a For each.
- Logo: `icon.png`, the Flow Steward wave mark.

## 1.0.0

- Initial reference release for Flow Steward dataset connectors.
- Adds read-only Google MCP Toolbox database connector operations for connection tests, schema introspection, query validation, preview, execution, and output-schema inference.
- Includes declarative extension UI pages and a deterministic local smoke test fixture.
- Packages checksum-verified linux-amd64 and linux-arm64 Google MCP Toolbox 1.3.0 source builds.
- Uses bounded MCP stdio with timeout cleanup and sanitized protocol failures.
- Removes SQLite and all private extension persistence paths.
