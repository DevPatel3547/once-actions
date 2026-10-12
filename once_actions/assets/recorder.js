// Installed only in the operator-selected browser context.
(() => {
  if (window.__onceInstalled) return;
  window.__onceInstalled = true;
  const pending = new Map();
  const name = (el) =>
    (
      el.getAttribute("aria-label") ||
      (el.getAttribute("aria-labelledby") || "")
        .split(/\s+/)
        .map((id) => document.getElementById(id)?.textContent || "")
        .join(" ")
        .trim() ||
      (el.labels
        ? [...el.labels].map((label) => label.textContent).join(" ")
        : "") ||
      (el instanceof HTMLInputElement && ["submit", "button"].includes(el.type)
        ? el.value
        : el.textContent) ||
      ""
    )
      .replace(/\s+/g, " ")
      .trim();
  const target = (el, role) => {
    const label = name(el);
    const result =
      !label && el.placeholder && ["textbox", "spinbutton"].includes(role)
        ? { placeholder: el.placeholder }
        : { role, name: label };
    const legend = el.closest("fieldset")?.querySelector(":scope > legend");
    if (legend?.textContent.trim()) result.group = legend.textContent.trim();
    return result;
  };
  const emit = (detail) => window.__onceRecord?.(detail).catch(() => {});
  const flush = () => {
    for (const [el, detail] of pending) {
      emit(detail);
      pending.delete(el);
    }
  };
  const textInput = (el) =>
    el instanceof HTMLTextAreaElement ||
    (el instanceof HTMLInputElement &&
      ["text", "email", "number", "search", "tel", "url"].includes(el.type));
  document.addEventListener(
    "input",
    (e) => {
      if (textInput(e.target))
        pending.set(e.target, {
          action: "fill",
          target: target(
            e.target,
            e.target.type === "number" ? "spinbutton" : "textbox",
          ),
          value: e.target.value,
        });
    },
    true,
  );
  document.addEventListener(
    "change",
    (e) => {
      const el = e.target;
      if (textInput(el)) {
        flush();
      } else if (el instanceof HTMLSelectElement) {
        flush();
        emit({
          action: "select",
          target: target(el, "combobox"),
          value: el.value,
        });
      } else if (el instanceof HTMLInputElement && el.type === "checkbox") {
        flush();
        emit({
          action: el.checked ? "check" : "uncheck",
          target: target(el, "checkbox"),
        });
      }
    },
    true,
  );
  document.addEventListener(
    "keydown",
    (e) => {
      if (
        e.key === "Enter" &&
        e.target instanceof HTMLInputElement &&
        textInput(e.target)
      ) {
        flush();
        emit({
          action: "press",
          target: target(
            e.target,
            e.target.type === "number" ? "spinbutton" : "textbox",
          ),
          key: "Enter",
        });
      }
    },
    true,
  );
  document.addEventListener(
    "click",
    (e) => {
      flush();
      const el = e.target.closest(
        'button,[role="button"],input[type="submit"],input[type="button"],a[href]',
      );
      if (el)
        emit({
          action: "click",
          target: target(el, el.matches("a[href]") ? "link" : "button"),
        });
    },
    true,
  );
  window.__onceFlush = flush;
})();
