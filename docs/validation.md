# Validation scope

Automated checks use actual Chromium browser actions. They do not call a model API or create records in third-party hosted accounts.

## Independent applications

**sqlite-web 0.8.2**, installed from its released package. The test creates a temporary SQLite database, starts the unmodified Flask application, teaches its native insert form, replays with different data, and separately queries SQLite for both exact rows. No application-specific selector or API shortcut is added to the runner. Source: https://github.com/coleifer/sqlite-web.

**TodoMVC JavaScript ES6**, upstream commit `ff43b02e59dfa604386bb382034b2cd07c2bcd8a`. Four unmodified distribution files, the upstream MIT license, and per-file hashes are in `tests/vendor/todomvc`. The workflow is learned from its placeholder-identified input and Enter submission. This upstream build uses JavaScript memory for its todo store; it is not evidence of durability or persistent browser storage. Source: https://github.com/tastejs/todomvc.

A separate owned test application verifies cookies/local storage across browser contexts and rejects a repeated task when its outcome is already present. This test is explicitly not independent application evidence.

## Reliability and security checks

- Concurrent identical run claims admit only one execution; conflicting inputs with the same ID are rejected.
- Restarting the library converts unfinished runs to `interrupted`; reusing that ID does not execute again.
- A real MCP client reconnects to a fresh server process and retrieves the same completed workbench run without another write.
- Corrections preserve old revisions and reject stale edits.
- Backups preserve workflows and optional browser state, have restrictive permissions, and can be restored.
- Missing/ambiguous targets, cross-origin requests, malformed inputs, stale tokens, and workbench-as-target misuse are rejected or stopped.
- Browser checks exercise the full workbench prepare/capture/finish/save/run/correct/forget flow, JSON export, mobile overflow, and legacy teaching flow.
- An injected journal write failure produces an uncertain result and blocks new runs. Unknown newer database formats are rejected without leaving a stale process lock.

GitHub CI runs acceptance checks and package builds on Python 3.10, 3.12, and 3.13 under Linux. Local verification uses macOS. Windows is unsupported because library ownership currently uses POSIX file locking.

## Claims this does not support

There is no random sample of websites, success-rate benchmark, independent security audit, sustained load test, external user study, agent-planning evaluation, or demonstrated speed advantage over good handwritten automation. The named external apps informed acceptance development; neither is claimed as an unseen evaluation set. Test counts are not production-readiness scores.
