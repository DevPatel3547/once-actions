# Changelog

## 0.2.0 — Local workbench beta

- Separate-browser recording with preparation, named inputs and explicit visible outcome checks.
- Persistent library, immutable corrections, optional private cookies/local storage and run history.
- Atomic run identity, duplicate-call handling, interruption recovery and journal-failure reporting.
- MCP connection to a saved revision through the same journal; legacy file commands preserved.
- Browser installation check, private SQLite backup, packaging and operation guides.
- Checks against pinned unmodified TodoMVC and sqlite-web; actual SQLite writes inspected independently of browser status.

Supported scope is a personal macOS/Linux application with native controls and one application origin. See the README and operations guide for boundaries. This release makes no arbitrary-site, production-scale, benchmark or novelty claim.

## 0.1.0

Owned-app demonstration, parameterized export, deterministic browser execution and standalone MCP prototype.
