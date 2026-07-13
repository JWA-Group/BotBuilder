/**
 * Lightweight i18n: data-i18n DOM scan + localStorage (botbuilder_lang).
 * Language selector lives only in Settings (no header injection).
 */
(function (global) {
  "use strict";

  var LANG_KEY = "botbuilder_lang";
  var SUPPORTED = { en: true, ru: true, es: true };
  var DEFAULT_LANG = "en";

  function normalizeLang(lang) {
    var code = String(lang || "")
      .trim()
      .toLowerCase()
      .slice(0, 2);
    return SUPPORTED[code] ? code : DEFAULT_LANG;
  }

  function readStoredLang() {
    try {
      var fromStorage = global.localStorage.getItem(LANG_KEY);
      if (fromStorage && SUPPORTED[normalizeLang(fromStorage)]) {
        return normalizeLang(fromStorage);
      }
    } catch (e) {
      /* ignore */
    }
    return null;
  }

  function getLang() {
    var stored = readStoredLang();
    if (stored) return stored;
    return DEFAULT_LANG;
  }

  function setLang(lang) {
    var code = normalizeLang(lang);
    try {
      global.localStorage.setItem(LANG_KEY, code);
    } catch (e) {
      /* ignore */
    }
    global.document.documentElement.lang = code;
    return code;
  }

  function dictFor(lang) {
    var locales = global.BB_LOCALES || {};
    var code = normalizeLang(lang);
    return locales[code] || locales[DEFAULT_LANG] || {};
  }

  function interpolate(text, params) {
    if (!params || !text) return text;
    return String(text).replace(/\{(\w+)\}/g, function (_m, key) {
      return params[key] != null ? String(params[key]) : "";
    });
  }

  function t(key, params, lang) {
    var dict = dictFor(lang != null ? lang : getLang());
    var val = dict[key];
    if (val == null) {
      var fallback = (global.BB_LOCALES && global.BB_LOCALES[DEFAULT_LANG]) || {};
      val = fallback[key] != null ? fallback[key] : key;
    }
    return interpolate(val, params);
  }

  function applyToElement(el, lang) {
    var key = el.getAttribute("data-i18n");
    if (key) {
      if (el.tagName === "INPUT" || el.tagName === "TEXTAREA") {
        if (el.hasAttribute("data-i18n-placeholder")) {
          el.placeholder = t(el.getAttribute("data-i18n-placeholder"), null, lang);
        }
      } else {
        el.textContent = t(key, null, lang);
      }
    }
    var htmlKey = el.getAttribute("data-i18n-html");
    if (htmlKey) {
      el.innerHTML = t(htmlKey, null, lang);
    }
    var phKey = el.getAttribute("data-i18n-placeholder");
    if (phKey && (el.tagName === "INPUT" || el.tagName === "TEXTAREA")) {
      el.placeholder = t(phKey, null, lang);
    }
    var ariaKey = el.getAttribute("data-i18n-aria");
    if (ariaKey) {
      el.setAttribute("aria-label", t(ariaKey, null, lang));
    }
    var titleKey = el.getAttribute("data-i18n-title");
    if (titleKey) {
      el.setAttribute("title", t(titleKey, null, lang));
    }
  }

  function notifyMainProcess(lang) {
    if (global.electronAPI && typeof global.electronAPI.setAppLanguage === "function") {
      global.electronAPI.setAppLanguage(lang).catch(function () {});
    }
    if (global.settingsBridge && typeof global.settingsBridge.notifyLang === "function") {
      global.settingsBridge.notifyLang(lang);
    }
  }

  function applyLanguage(lang, options) {
    options = options || {};
    var code = setLang(lang);
    var nodes = global.document.querySelectorAll(
      "[data-i18n], [data-i18n-placeholder], [data-i18n-aria], [data-i18n-title], [data-i18n-html]"
    );
    for (var i = 0; i < nodes.length; i++) {
      applyToElement(nodes[i], code);
    }
    var select = global.document.getElementById("lang-select");
    if (select && select.value !== code) {
      select.value = code;
    }
    if (!options.silent && !options.fromBroadcast) {
      notifyMainProcess(code);
    }
    try {
      global.dispatchEvent(new CustomEvent("botbuilder:langchange", { detail: { lang: code } }));
    } catch (e) {
      /* ignore */
    }
    return code;
  }

  global.__applyLanguageFromMain = function (lang) {
    applyLanguage(lang, { silent: true, fromBroadcast: true });
  };

  if (global.addEventListener) {
    global.addEventListener("storage", function (ev) {
      if (!ev || ev.key !== LANG_KEY || !ev.newValue) return;
      var next = normalizeLang(ev.newValue);
      if (next === getLang()) return;
      applyLanguage(next, { silent: true, fromBroadcast: true });
    });
  }

  function bindLangSelect(select) {
    if (!select || select.__i18nBound) return;
    select.__i18nBound = true;
    select.value = getLang();
    select.addEventListener("change", function () {
      applyLanguage(select.value);
    });
  }

  function initLangSelectOnly() {
    var existing = global.document.getElementById("lang-select");
    if (existing) bindLangSelect(existing);
  }

  function resolveInitialLang() {
    if (global.settingsBridge && global.settingsBridge.initialLang) {
      return Promise.resolve(normalizeLang(global.settingsBridge.initialLang));
    }
    // localStorage reflects the latest user choice (updated on save / lang change).
    // --app-lang in argv is fixed at window creation and must not override it on navigation.
    var stored = readStoredLang();
    if (stored) return Promise.resolve(stored);
    if (global.electronAPI && typeof global.electronAPI.getAppLanguage === "function") {
      var fromApp = global.electronAPI.getAppLanguage();
      if (fromApp) return Promise.resolve(normalizeLang(fromApp));
    }
    return Promise.resolve(DEFAULT_LANG);
  }

  function initI18n() {
    var run = function (lang) {
      global.document.documentElement.lang = lang;
      initLangSelectOnly();
      applyLanguage(lang, { silent: true });
    };
    var maybePromise = resolveInitialLang();
    if (maybePromise && typeof maybePromise.then === "function") {
      maybePromise.then(run);
    } else {
      run(maybePromise || getLang());
    }
  }

  if (global.document.readyState === "loading") {
    global.document.addEventListener("DOMContentLoaded", initI18n);
  } else {
    initI18n();
  }

  global.getLang = getLang;
  global.setLang = setLang;
  global.t = t;
  global.applyLanguage = applyLanguage;
})(typeof window !== "undefined" ? window : globalThis);
