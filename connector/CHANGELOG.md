# Changelog

## 1.0.0

- Initial reference release for Flow Steward dataset connectors.
- Adds read-only Google MCP Toolbox database connector operations for connection tests, schema introspection, query validation, preview, execution, and output-schema inference.
- Includes declarative extension UI pages and a deterministic local smoke test fixture.
- Packages checksum-verified linux-amd64 and linux-arm64 Google MCP Toolbox 1.3.0 source builds.
- Uses bounded MCP stdio with timeout cleanup and sanitized protocol failures.
- Removes SQLite and all private extension persistence paths.
