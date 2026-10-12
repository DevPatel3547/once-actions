# Next evidence gate

The useful question is whether demonstrating and correcting a workflow is easier than writing or maintaining its automation. A complete local application and passing integration checks do not answer that comparison.

## Implemented now

The v0.2 workbench records outside the practice app, persists reviewed revisions, executes named inputs, checks visible outcomes and exposes the same journal over MCP. A person can edit one target label or group as a new revision; old revisions remain unchanged. This is manual target editing, not correction learned from another demonstration. Pinned unmodified TodoMVC and sqlite-web exercise the general path; see [validation](validation.md).

## Next measurement

Select a third independently maintained application and held-out tasks before changing the runner for them. Publish definitions, revisions and setup instructions. Include realistic application changes and preserve failures instead of adding hidden app-specific logic.

Compare the same tasks, inputs and changes using:

1. Straightforward Playwright scripts with strong role/name locators.
2. Demonstrated workflows and reviewed target corrections.
3. A model-driven agent only after a concrete budget and credentials are authorized.

Measure correct final application state, unintended writes, human teaching/repair time, interventions, latency and model usage where applicable. Use application data rather than success toasts as the oracle where possible. Do not handicap scripts with deliberately brittle selectors.

There is no current comparative result. If a short script is equally easy to maintain, report it. Broader usefulness requires people completing recurring tasks, repeat usage and independently reproduced results. None are implied by the present tests or by adding more features.
