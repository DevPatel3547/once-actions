const $ = (id) => document.getElementById(id);
let token = "",
  library = [],
  selected = null,
  activeRun = null,
  recordTimer = null,
  jobTimer = null,
  recordHash = null;
const message = (id, text, kind = "") => {
  const el = $(id);
  el.hidden = false;
  el.textContent = text;
  el.className = kind;
};
async function api(path, data) {
  const response = await fetch(
    path,
    data === undefined
      ? {}
      : {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "X-Once-Token": token,
          },
          body: JSON.stringify(data),
        },
  );
  const value = await response.json();
  if (!response.ok) {
    const error = Error(value.error || "The request failed");
    error.status = response.status;
    throw error;
  }
  return value;
}
const guarded = (fn) => async () => {
  try {
    await fn();
  } catch (error) {
    message("notice", error.message, "error");
  }
};
const describe = (step) =>
  `${step.action} “${step.target.name || step.target.placeholder}”${step.parameter ? " using " + step.parameter : ""}${step.key ? " (" + step.key + ")" : ""}`;
function showSteps(id, steps) {
  $(id).replaceChildren();
  steps.forEach((step) => {
    const li = document.createElement("li");
    li.textContent = describe(step);
    $(id).append(li);
  });
}
function teach() {
  $("teach").hidden = false;
  $("teach").scrollIntoView({ behavior: "smooth" });
}
$("new").onclick = teach;
$("empty-teach").onclick = teach;
$("hide-teach").onclick = () => {
  $("teach").hidden = true;
};
async function refresh() {
  library = await api("/api/library");
  $("library").replaceChildren();
  if (!library.length) $("library").textContent = "No saved workflows yet.";
  for (const item of library) {
    const b = document.createElement("button");
    b.className = selected?.id === item.id ? "active" : "";
    b.textContent = item.skill.name;
    b.dataset.id = item.id;
    const small = document.createElement("small");
    small.textContent = `Revision ${item.revision} · ${item.skill.steps.length} steps`;
    b.append(small);
    b.onclick = () => select(item);
    $("library").append(b);
  }
  await history();
}
function select(item) {
  item = {
    ...item,
    remembers_browser:
      item.remembers_browser ??
      library.find((row) => row.id === item.id)?.remembers_browser ??
      false,
  };
  selected = item;
  $("empty").hidden = true;
  $("selected").hidden = false;
  $("skill-name").textContent = item.skill.name;
  $("revision").textContent = "Revision " + item.revision;
  $("destination").textContent = item.skill.start_url;
  $("outcome").textContent =
    `Outcome: ${item.skill.success.kind === "parameter" ? "input " : ""}${item.skill.success.value} becomes visible`;
  showSteps("skill-steps", item.skill.steps);
  $("inputs").replaceChildren();
  for (const key of item.skill.parameters) {
    const label = document.createElement("label");
    label.textContent = key;
    const input = document.createElement("input");
    input.dataset.parameter = key;
    input.autocomplete = "off";
    label.append(input);
    $("inputs").append(label);
  }
  $("correction-step").replaceChildren();
  item.skill.steps.forEach((step, i) => {
    const option = document.createElement("option");
    option.value = i;
    option.textContent = `${i + 1}. ${describe(step)}`;
    $("correction-step").append(option);
  });
  setCorrection();
  $("agent-command").value =
    `once-actions mcp-live --studio ${location.origin} --skill-id ${item.id} --revision ${item.revision}`;
  $("session-status").textContent = item.remembers_browser
    ? "Browser state is saved privately for this workflow."
    : "Each run starts without saved cookies or local storage.";
  $("forget-session").hidden = !item.remembers_browser;
  $("run-status").hidden = true;
  for (const button of $("library").children)
    if (button.tagName === "BUTTON")
      button.classList.toggle("active", button.dataset.id === item.id);
}
function setCorrection() {
  if (!selected) return;
  const target =
    selected.skill.steps[Number($("correction-step").value)].target;
  $("target-name").value = target.name || target.placeholder;
  $("target-group").value = target.group || "";
  $("correction-diff").textContent =
    "Current target: " + JSON.stringify(target);
}
$("correction-step").onchange = setCorrection;
$("correct").onclick = guarded(async () => {
  if (!selected) return;
  const original =
    selected.skill.steps[Number($("correction-step").value)].target;
  const changed = original.placeholder
    ? { placeholder: $("target-name").value }
    : { role: original.role, name: $("target-name").value };
  if ($("target-group").value) changed.group = $("target-group").value;
  const saved = await api("/api/skills/correct", {
    id: selected.id,
    revision: selected.revision,
    index: Number($("correction-step").value),
    target: changed,
  });
  await refresh();
  select(saved);
  message(
    "notice",
    "Correction saved as a new revision. Review the workflow before running it.",
    "good",
  );
});
$("record").onclick = guarded(async () => {
  const data = {
    name: $("name").value,
    url: $("url").value,
    examples: exampleValues(),
    success: { kind: $("check-kind").value, value: $("check-value").value },
    remember: $("remember").checked,
  };
  await api("/api/record/start", data);
  $("record").disabled = true;
  $("finish").disabled = false;
  $("save").hidden = true;
  message("record-status", "Opening the recording browser…");
  clearTimeout(recordTimer);
  pollRecording();
});
async function pollRecording() {
  try {
    const state = await api("/api/recording");
    showSteps("record-steps", state.steps);
    if (["opening", "preparing", "recording"].includes(state.status)) {
      $("arm").hidden = state.status !== "preparing";
      message(
        "record-status",
        state.status === "opening"
          ? "Opening the browser…"
          : state.status === "preparing"
            ? "Prepare the page or sign in, then choose Start capturing. Setup actions are not recorded."
            : "Recording. Perform the task in the new browser, then choose Finish recording here.",
      );
      recordTimer = setTimeout(pollRecording, 600);
    } else {
      $("record").disabled = false;
      $("finish").disabled = true;
      $("save").hidden = state.status !== "review";
      $("arm").hidden = true;
      recordHash = state.hash;
      message(
        "record-status",
        state.error ||
          "Recording finished. Review each step, then save the workflow.",
        state.status === "error" ? "error" : "good",
      );
    }
  } catch (error) {
    message("record-status", error.message, "error");
    $("record").disabled = false;
  }
}
$("finish").onclick = guarded(async () => {
  await api("/api/record/finish", {});
  $("finish").disabled = true;
  message("record-status", "Finishing the recording…");
});
$("save").onclick = guarded(async () => {
  const saved = await api("/api/record/save", { hash: recordHash });
  $("save").hidden = true;
  $("teach").hidden = true;
  await refresh();
  select(saved);
  message(
    "notice",
    "Workflow saved locally. Enter new values to run it.",
    "good",
  );
});
$("demo").onclick = guarded(async () => {
  const boot = await api("/api/bootstrap");
  $("url").value = boot.demo_url;
  $("name").value = "create_client_request";
  examples({
    customer: "River FC",
    request: "Update the match announcement",
    priority: "urgent",
  });
  $("check-kind").value = "text";
  $("check-value").value = "Request saved";
});
$("run").onclick = guarded(async () => {
  if (activeRun) throw Error("Wait for the active run to finish");
  const parameters = Object.fromEntries(
    [...$("inputs").querySelectorAll("input")].map((input) => [
      input.dataset.parameter,
      input.value,
    ]),
  );
  const id = crypto.randomUUID();
  activeRun = id;
  $("run").disabled = true;
  $("cancel").hidden = false;
  try {
    await api("/api/runs", {
      id,
      skill_id: selected.id,
      revision: selected.revision,
      parameters,
    });
    pollJob();
  } catch (error) {
    if (error.status >= 400 && error.status < 500) {
      activeRun = null;
      $("run").disabled = false;
      $("cancel").hidden = true;
      throw error;
    }
    // A failed response may follow a committed run claim. Inspect that same ID.
    message(
      "run-status",
      "The connection was interrupted. Checking the saved run before allowing another write.",
      "error",
    );
    pollJob();
  }
});
async function pollJob() {
  if (!activeRun) return;
  try {
    const job = await api("/api/job?id=" + encodeURIComponent(activeRun));
    const workflow =
      library.find((item) => item.id === job.skill_id)?.skill.name ||
      job.skill_id;
    message(
      "run-status",
      job.status === "running"
        ? `${workflow} · revision ${job.revision}: Running in Chromium…`
        : `${workflow} · revision ${job.revision}: ${job.status.replaceAll("_", " ")} — ${job.result?.reason || "The process stopped before it could confirm an outcome. Check application state."}`,
      job.status === "verified"
        ? "good"
        : job.status === "running"
          ? ""
          : "error",
    );
    if (job.status === "running") jobTimer = setTimeout(pollJob, 600);
    else {
      activeRun = null;
      $("run").disabled = false;
      $("cancel").hidden = true;
      await history();
    }
  } catch (error) {
    message(
      "run-status",
      "Connection lost. Refresh to inspect the persisted run; do not submit it again blindly.",
      "error",
    );
  }
}
$("cancel").onclick = guarded(async () => {
  if (activeRun) await api("/api/runs/cancel", { id: activeRun });
});
async function history() {
  const rows = await api("/api/history");
  $("history").replaceChildren();
  if (!rows.length) $("history").textContent = "No runs yet.";
  for (const run of rows) {
    const div = document.createElement("div");
    div.className = "run-row";
    const title = document.createElement("div");
    const strong = document.createElement("strong");
    strong.textContent =
      library.find((item) => item.id === run.skill_id)?.skill.name ||
      run.skill_id;
    const small = document.createElement("small");
    small.textContent = `Revision ${run.revision} · ${new Date(run.created * 1000).toLocaleString()} · ${run.id.slice(0, 8)}`;
    title.append(strong, small);
    const status = document.createElement("span");
    status.className = "badge";
    status.textContent = run.status.replaceAll("_", " ");
    div.append(title, status);
    if (run.result?.reason) {
      const reason = document.createElement("small");
      reason.textContent = run.result.reason;
      title.append(reason);
    }
    $("history").append(div);
  }
  if (!activeRun) {
    const running = rows.find((row) => row.status === "running");
    if (running) {
      if (!selected) {
        const item = library.find((row) => row.id === running.skill_id);
        if (item) select(item);
      }
      activeRun = running.id;
      $("run").disabled = true;
      $("cancel").hidden = false;
      pollJob();
    }
  }
}
$("export").onclick = () => {
  if (!selected) return;
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(selected.skill, null, 2)], {
      type: "application/json",
    }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = selected.skill.name + ".skill.json";
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
$("import").onchange = guarded(async () => {
  const file = $("import").files[0];
  if (!file) return;
  if (file.size > 100000) throw Error("Skill files must be under 100 KB");
  const saved = await api("/api/skills/import", JSON.parse(await file.text()));
  await refresh();
  select(saved);
  message(
    "notice",
    "Imported. Review the destination and actions before running.",
  );
  $("import").value = "";
});
guarded(async () => {
  const boot = await api("/api/bootstrap");
  token = boot.token;
  $("url").value = boot.demo_url;
  await refresh();
  const state = await api("/api/recording");
  if (["opening", "preparing", "recording", "review"].includes(state.status)) {
    teach();
    $("record").disabled = state.status !== "review";
    $("finish").disabled = state.status === "review";
    pollRecording();
  }
})();

$("arm").onclick = guarded(async () => {
  await api("/api/record/arm", {});
  $("arm").hidden = true;
});
$("forget-session").onclick = guarded(async () => {
  if (!selected) return;
  await api("/api/skills/forget-session", { id: selected.id });
  await refresh();
  select(library.find((item) => item.id === selected.id));
  message(
    "notice",
    "Saved cookies and local storage removed from this library. Existing site sessions may still need revocation at the website.",
  );
});

function addExample(name = "", value = "") {
  const row = document.createElement("div");
  row.className = "example-row";
  for (const [caption, val] of [
    ["Input name", name],
    ["Example value", value],
  ]) {
    const label = document.createElement("label");
    label.textContent = caption;
    const input = document.createElement("input");
    input.value = val;
    input.autocomplete = "off";
    label.append(input);
    row.append(label);
  }
  const remove = document.createElement("button");
  remove.className = "secondary";
  remove.textContent = "Remove";
  remove.onclick = () => row.remove();
  row.append(remove);
  $("example-list").append(row);
}
function examples(values) {
  $("example-list").replaceChildren();
  Object.entries(values).forEach(([key, value]) => addExample(key, value));
}
function exampleValues() {
  const values = {};
  for (const row of $("example-list").children) {
    const [name, value] = [...row.querySelectorAll("input")].map(
      (el) => el.value,
    );
    if (Object.hasOwn(values, name))
      throw Error("Each input needs a different name");
    Object.defineProperty(values, name, { value, enumerable: true });
  }
  return values;
}
$("add-example").onclick = () => addExample();
examples({
  customer: "River FC",
  request: "Update the match announcement",
  priority: "urgent",
});
