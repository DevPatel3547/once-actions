# Operating Once Actions

## Supported release scope

A personal local application on macOS or Linux, Python 3.10+, Chromium, and a desktop for recording. A single owner process controls each library; one workflow run is admitted at a time. The HTTP service binds only to `127.0.0.1` and is not designed for public hosting, multiple users, or network exposure.

Supported applications use native, named controls on a self-contained origin. HTTPS is accepted; unencrypted HTTP is limited to literal loopback addresses with an explicit port. Cross-origin browser requests are blocked, service workers are disabled, and WebSockets are closed. Multi-origin SSO, CDN dependencies, popups, frames, custom canvas controls, file uploads/downloads, and conditional workflows are outside this release. A unique label does not prove that a changed control still means the same thing.

Sign in during preparation, before capture. Optional saved browser state supports cookies and local storage. Expired sessions need a fresh recording or manual preparation; they are not automatically repaired. Browser state belongs to a saved workflow, not a shared global account profile. IndexedDB, sessionStorage, and memory-only application state are not saved.

## Run outcomes

| Status | Meaning | Action |
|---|---|---|
| `verified` | Expected exact text became visible after the actions | Check any business-critical result in the application |
| `executed` | Legacy v1 actions completed without an outcome check | Verify application state yourself |
| `precondition_failed` | Expected outcome was already visible before execution | No actions ran; inspect whether the task is already done |
| `needs_teaching` | A target was missing, ambiguous, or could not be operated | Inspect prior effects, correct or teach the changed control |
| `unverified` | Actions ran but expected text was not observed | Do not assume failure or success; inspect the application |
| `blocked` | The application attempted to leave its allowed origin | Use a supported self-contained application |
| `cancelled` | A stop request was observed before the next action | Current/earlier actions are not rolled back |
| `interrupted` | Process or execution ended without a confirmed result | Inspect effects; the old run ID never restarts execution |
| `storage_failed` | Execution ended but its result could not be saved | New runs are blocked; check application state and disk space, then restart |

The runtime checks a two-minute execution deadline between steps; a currently executing browser operation may finish after that deadline. Recording has a 15-minute limit. Cancellation is cooperative, not a transaction abort.

## Storage and backups

Default directory: `~/.local/share/once-actions`. It contains `library.sqlite3` and an owner lock. New directories use mode 0700; the database and backups use 0600. Protect your operating-system account and backups. The application does not encrypt the database.

Run inputs are not copied into the run journal; a keyed digest distinguishes retries with different inputs. However, URLs, target names, outcome text, and optional browser state can contain private information. Browser state can include the application's own copies of input data and authentication cookies. Do not publish the library or backups.

`once-actions backup --output /private/path/backup.sqlite3` uses SQLite's backup API and checks integrity. It can run while the workbench is open. To restore:

1. Stop the workbench and any process that owns the destination library.
2. Keep the current library directory as a separate backup.
3. Create a new private data directory, copy the backup into it as `library.sqlite3`, and set directory/file permissions to 0700/0600.
4. Start `once-actions studio --data-dir /path/to/restored-library`.
5. Inspect history. Runs left `running` in a backup become `interrupted`; they are not replayed.

Forgetting saved browser state removes its active database row. It does not revoke a website's session, erase existing backups, or promise forensic erasure of SQLite pages. Revoke sessions at the website when needed.

## Troubleshooting

- **Browser cannot launch:** run `once-actions doctor`, then `python -m playwright install chromium`. Linux may also need `python -m playwright install --with-deps chromium`.
- **Port already in use:** start with `--port 8781` and use the printed URL. Do not kill unrelated processes.
- **Library already open:** close the other workbench using that data directory. Do not delete the owner-lock file to bypass the lock.
- **Wrong host or stale control token:** use the exact IP URL printed by the workbench and reload after a restart. Reconnect MCP after a workbench restart.
- **Connection lost during a run:** inspect history. Reuse the same run ID and inputs through MCP to retrieve its status; do not generate a new ID just to retry a lost response.
- **A named input does not match:** use distinct example values exactly. Discard the recording and start again after correcting the examples.
- **Outcome not found:** choose text that becomes uniquely visible only after completion. Generic success text is not proof of a durable backend write.

## Upgrade and rollback

Stop the workbench, make a backup, install the new version, and run `doctor` before reopening the library. Version 0.2 creates persistent-library format 1 and refuses unknown newer formats. Future incompatible changes need explicit migrations. Roll back both the software and a compatible backup together; preserve newer data separately. Exported v1 skills remain usable through the standalone CLI, while the workbench requires v2.
