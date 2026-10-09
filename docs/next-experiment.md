# What would make this worth expanding?

The useful question is whether demonstrating and correcting a workflow is easier than writing or maintaining its automation. Passing our own form tests cannot answer that.

## Next evidence gate

Choose three independently maintained, locally runnable applications with repeatable data-entry tasks. Pin their revisions and publish setup instructions. Teach each through a general capture surface without adding application-specific logic to the runner. Keep at least one application out of development until the evaluation.

For each task, compare:

1. A straightforward Playwright script using role-and-name locators.
2. The demonstrated Once Actions skill.
3. A model-driven browser agent, only when a model budget and credentials are explicitly configured.

Measure correct final application state, unintended writes, time spent teaching or repairing, human interventions, execution latency, and model usage where applicable. Preserve failures. Run the same task inputs and changes for each method; do not handicap the scripted baseline with brittle generated IDs when stronger locators are available.

## The product hypothesis

A person should be able to correct a changed workflow by showing the changed step, review the resulting difference, and reuse that correction without reteaching every step. The correction must remain narrow: changing one field label must not authorize unrelated controls. Incremental correction and its evaluation are **not implemented in this release**; currently the user teaches the sequence again.

Build that feature only with repeatable tasks that expose its value. If a short script is equally easy to maintain, acknowledge that result and change the approach. If external tasks repeatedly require fragile special cases, do not hide them behind a polished demo.

## Release claims

This prototype establishes a demonstration → parameterized plan → browser execution → MCP tool path. It does not establish novel research, external adoption, arbitrary-site reliability, or a hiring outcome. Those require separate evidence.
