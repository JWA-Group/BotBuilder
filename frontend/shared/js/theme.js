/**
 * Global theme switcher — localStorage key: app_theme (light | dark).
 * Applies class on <html> and <body> for full-app coverage.
 */
(function (global) {
  "use strict";

  var LS_KEY = "app_theme";
  var applying = false;

  function normalize(theme) {
    return theme === "dark" ? "dark" : "light";
  }

  function getTheme() {
    try {
      return normalize(global.localStorage.getItem(LS_KEY));
    } catch (e) {
      return "light";
    }
  }

  function setRootClass(t) {
    var doc = global.document;
    if (!doc) return;
    var roots = [doc.documentElement];
    if (doc.body) roots.push(doc.body);
    roots.forEach(function (el) {
      el.classList.remove("theme-light", "theme-dark");
      el.classList.add("theme-" + t);
    });
  }

  /**
   * @param {string} theme
   * @param {{ silent?: boolean }} [options]
   */
  function applyTheme(theme, options) {
    var t = normalize(theme);
    var root = global.document && global.document.documentElement;
    if (!root) return t;

    var prev = root.classList.contains("theme-dark")
      ? "dark"
      : root.classList.contains("theme-light")
        ? "light"
        : null;
    var silent = !!(options && options.silent);

    if (prev === t) {
      setRootClass(t);
      try {
        global.localStorage.setItem(LS_KEY, t);
      } catch (e) {}
      return t;
    }

    if (applying) return t;
    applying = true;
    try {
      setRootClass(t);
      try {
        global.localStorage.setItem(LS_KEY, t);
      } catch (e) {}
      try {
        global.dispatchEvent(new CustomEvent("appthemechange", { detail: { theme: t } }));
      } catch (e2) {}
      if (
        !silent &&
        global.electronAPI &&
        typeof global.electronAPI.notifyThemeChange === "function"
      ) {
        global.electronAPI.notifyThemeChange(t);
      }
    } finally {
      applying = false;
    }
    return t;
  }

  function toggleTheme() {
    return applyTheme(getTheme() === "dark" ? "light" : "dark");
  }

  // Boot before paint when possible; never notify Electron on initial load.
  applyTheme(getTheme(), { silent: true });
  if (global.document && !global.document.body) {
    global.document.addEventListener("DOMContentLoaded", function () {
      setRootClass(getTheme());
    });
  }

  global.AppTheme = {
    get: getTheme,
    apply: applyTheme,
    toggle: toggleTheme,
  };
})(typeof window !== "undefined" ? window : globalThis);
