# Once Actions

**Teach a browser task. Save it as a checked tool an agent can call.**

Once Actions is a local workflow workbench for macOS and Linux. Demonstrate a task in a separate Chromium browser, review its parameterized steps, save an immutable revision, then run it with new inputs. Runs have durable identities and history. An MCP bridge lets an agent use the same reviewed revision and journal.

![Once Actions workbench](docs/studio.png)

**Release status: local beta, with a defined supported scope.** The complete record → review → save → run → verify → correct → export/MCP path is implemented and tested. This is not an arbitrary-website automation service or independently audited production platform. See [support and limits](docs/operations.md).

## Install and start

Python 3.10+ on macOS or Linux. No model API key, account, or paid service is required.

```sh
git clone https://github.com/DevPatel3547/once-actions.git
cd once-actions
python -m venv .venv
source .venv/bin/activate
pip install -e '.[mcp]'
python -m playwright install chromium
once-actions doctor
once-actions studio
```

On Linux, `python -m playwright install --with-deps chromium` also installs browser system dependencies. Use a desktop session for recording; the automated checks use headless Chromium.

Open **http://127.0.0.1:8780**. The workbench stores its library in `~/.local/share/once-actions`; `--data-dir /private/location` selects another directory. Only one process may own a library.

## Teach your first workflow

1. Choose **Teach a workflow**, then **Use the practice app**. The included example has three named inputs and an outcome of `Request saved`.
2. Choose **Open recording browser**. Prepare the page or sign in if needed. Setup actions are ignored until you choose **Start capturing** in the workbench.
3. In the recording browser, enter the exact example values and click Save. **Teaching performs real actions**, including writes.
4. Choose **Finish recording**, inspect the steps, and **Save reviewed workflow**.
5. Enter new values in the saved workflow and select **Run workflow**. Inspect the outcome and run history.

For another supported application, supply its URL and named example values. Text inputs, textareas, native selects, buttons, links, checkboxes, and Enter submission are supported. The recorder binds exact example values to parameter names; it rejects unknown values rather than embedding them in a skill.

**Keep browser state** is optional and off by default. It saves cookies and local storage privately for this workflow, which can support same-origin sign-in sessions and apps using local storage. It does not persist arbitrary JavaScript memory, session storage, or IndexedDB. Saved state can contain credentials and application data; it is not encrypted by Once Actions and is excluded from skill exports. The workbench provides **Forget saved browser state**.

## Correct a changed control

When a required target is missing or ambiguous, execution stops. Open **Correct one target**, choose the affected step, update its label or placeholder and optional field group, and save a new revision. The action type, parameters, URL, and outcome check remain unchanged. Earlier revisions remain in the library, and run records point to the exact revision used.

A correction does not resume a partially completed run. Inspect application state before starting a new run; earlier actions may already have changed it.

## Connect an agent through MCP

In a saved workflow, open **Connect an agent**. Use its command with an MCP host, replacing the executable with the absolute path to your installed `once-actions`:

```sh
/absolute/path/to/.venv/bin/once-actions mcp-live \
  --studio http://127.0.0.1:8780 \
  --skill-id YOUR_SAVED_SKILL_ID --revision 1
```

Keep the workbench running. The bridge exposes one reviewed revision. Its arguments are:

```json
{
  "run_id": "d4d7b658-8b14-4e0d-a3ca-af6319d7d934",
  "inputs": {
    "customer": "Harbor FC",
    "request": "Publish the updated schedule",
    "priority": "normal"
  }
}
```

Use a **new UUID for an intentional new run**. After a lost response, reuse the same ID and identical inputs: the workbench returns the existing run instead of executing again. Reusing an ID with different inputs or a different revision is rejected. Interrupted runs remain interrupted and are not replayed automatically. This is request deduplication, not an exactly-once guarantee for a remote service.

The bridge uses the [official MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk). Tests exercise a real SDK client and server subprocess, browser execution, and reconnecting with the same run ID. They do not measure language-model planning.

## Export, CLI, and backup

An exported v2 skill contains its fixed application URL and outcome check. It contains no browser session. Run it without the workbench:

```sh
once-actions run create_client_request.skill.json --parameters new-request.json
once-actions tool create_client_request.skill.json
once-actions mcp create_client_request.skill.json
```

These standalone commands use a fresh browser context and do **not** use the workbench journal or saved browser state. Prefer `mcp-live` for durable agent runs. Legacy v1 files still work with an explicit `--url` and report actions executed without outcome verification.

Create a consistent private backup, including saved browser state if enabled:

```sh
once-actions backup --output /private/location/once-backup.sqlite3
```

The destination must not already exist. See [restore and troubleshooting](docs/operations.md) before replacing a library.

## Evidence and limits

The suite covers recording, replay, exact database writes, immutable revisions, stale-edit rejection, duplicate run requests, restart recovery, browser-state persistence, backup/restore, scope enforcement, desktop/mobile UI, and both MCP modes.

Two independent application checks run without modifying their UI code:

- **sqlite-web 0.8.2:** record its native insert form, replay different input, then query its SQLite database to verify the exact row.
- **TodoMVC JavaScript ES6:** record Enter submission against a pinned upstream bundle with provenance hashes. This particular build stores tasks only in memory; this test establishes UI execution, not persistent storage.

```sh
pip install -e '.[mcp,dev,integration]'
python -m playwright install chromium
ruff check .
ruff format --check .
python -m unittest discover -v
python -m build
```

These are acceptance tests, not evidence that Once Actions beats a well-written Playwright script or works reliably across arbitrary sites. [Design and trust boundaries](docs/design.md), [evidence](docs/validation.md), and [future evaluation](docs/next-experiment.md) describe the practical limits.

Browser recording and workflow automation already exist, including [workflow-use](https://github.com/browser-use/workflow-use) and [Skyvern](https://www.skyvern.com/products). This project does not claim to invent them. Its current contribution is an integrated local workflow lifecycle with reviewable revisions, explicit outcome checks, and durable tool-call handling. Comparative advantage, adoption, and research novelty remain unproven.

MIT licensed. Vendored TodoMVC test files retain their upstream license and provenance.
