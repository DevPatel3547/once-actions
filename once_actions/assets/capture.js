// Capture semantic actions, not coordinates or generated executable code.
(() => {
  const label = (el) => {
    const labelled = el.getAttribute("aria-labelledby");
    return (
      el.getAttribute("aria-label") ||
      (labelled
        ? labelled
            .split(/\s+/)
            .map((id) => document.getElementById(id)?.textContent || "")
            .join(" ")
        : "") ||
      (el.labels
        ? [...el.labels].map((label) => label.textContent).join(" ")
        : "") ||
      el.textContent ||
      ""
    )
      .replace(/\s+/g, " ")
      .trim();
  };
  const target = (el, role) => {
    const value = { role, name: label(el) };
    const group = el.closest("fieldset");
    const legend = group?.querySelector(":scope > legend");
    if (legend) value.group = legend.textContent.trim();
    return value;
  };
  const emit = (detail) => {
    // The selected same-origin parent receives values only to bind parameters in memory.
    // The compiler never persists literal field values in a skill.
    if (window.parent !== window)
      window.parent.postMessage(
        { type: "once-demonstration", ...detail },
        location.origin,
      );
    if (typeof window.__onceCapture === "function")
      window.__onceCapture(detail);
  };
  document.addEventListener(
    "change",
    (event) => {
      const el = event.target;
      if (el instanceof HTMLSelectElement)
        emit({
          action: "select",
          target: target(el, "combobox"),
          value: el.value,
        });
      else if (
        el instanceof HTMLTextAreaElement ||
        (el instanceof HTMLInputElement &&
          ["text", "email", "number", "search", "tel", "url"].includes(el.type))
      ) {
        emit({
          action: "fill",
          target: target(el, el.type === "number" ? "spinbutton" : "textbox"),
          value: el.value,
        });
      }
    },
    true,
  );
  document.addEventListener(
    "click",
    (event) => {
      const el = event.target.closest('button,[role="button"]');
      if (el) emit({ action: "click", target: target(el, "button") });
    },
    true,
  );
})();
