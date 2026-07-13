/**
 * Shared API origin resolver for web and Electron desktop builds.
 *
 * Electron: preload exposes window.electronAPI.getPort() synchronously.
 * Browser: falls back to window.location.origin (FastAPI static hosting).
 */
(function (global) {
  "use strict";

  var FALLBACK_ORIGIN = "http://127.0.0.1:8000";
  var LANG_KEY = "botbuilder_lang";
  var SUPPORTED_LANGS = { en: true, ru: true, es: true };

  function getApiOrigin() {
    if (global.electronAPI) {
      if (typeof global.electronAPI.getApiOrigin === "function") {
        return global.electronAPI.getApiOrigin();
      }
      if (typeof global.electronAPI.getPort === "function") {
        return "http://127.0.0.1:" + global.electronAPI.getPort();
      }
    }
    if (global.location && global.location.origin && global.location.origin !== "null") {
      return global.location.origin.replace(/\/$/, "");
    }
    return FALLBACK_ORIGIN;
  }

  function getApiBase() {
    return getApiOrigin() + "/api";
  }

  function apiUrl(path) {
    var p = path.charAt(0) === "/" ? path : "/" + path;
    if (p.indexOf("/api/") === 0) {
      return getApiOrigin() + p;
    }
    return getApiBase() + p;
  }

  var DEFAULT_USER_ID = 1;

  function getUserId() {
    return String(DEFAULT_USER_ID);
  }

  function readAcceptLanguage() {
    try {
      var lang = global.localStorage.getItem(LANG_KEY);
      if (SUPPORTED_LANGS[lang]) return lang;
    } catch (e) {
      /* ignore */
    }
    return "en";
  }

  function apiHeaders(extra) {
    var headers = { "Accept-Language": readAcceptLanguage() };
    var token = global.localStorage && global.localStorage.getItem("access_token");
    if (token) headers.Authorization = "Bearer " + token;
    if (extra) {
      for (var k in extra) {
        if (Object.prototype.hasOwnProperty.call(extra, k)) headers[k] = extra[k];
      }
    }
    return headers;
  }

  function jsonApiHeaders(extra) {
    return apiHeaders(Object.assign({ "Content-Type": "application/json" }, extra || {}));
  }

  function apiFetch(path, options) {
    options = options || {};
    var url = path.indexOf("http") === 0 ? path : apiUrl(path);
    var merged = Object.assign({}, options.headers || {});
    var base = apiHeaders();
    for (var key in base) {
      if (merged[key] == null) merged[key] = base[key];
    }
    options.headers = merged;
    return global.fetch(url, options);
  }

  global.DEFAULT_USER_ID = DEFAULT_USER_ID;
  global.getUserId = getUserId;
  global.getApiOrigin = getApiOrigin;
  global.getApiBase = getApiBase;
  global.apiUrl = apiUrl;
  global.apiHeaders = apiHeaders;
  global.jsonApiHeaders = jsonApiHeaders;
  global.apiFetch = apiFetch;

  var DEFAULT_UNDO_STEPS = 30;

  function getUndoSteps() {
    if (global.electronAPI && typeof global.electronAPI.getUndoSteps === "function") {
      return global.electronAPI.getUndoSteps();
    }
    return DEFAULT_UNDO_STEPS;
  }

  global.DEFAULT_UNDO_STEPS = DEFAULT_UNDO_STEPS;
  global.getUndoSteps = getUndoSteps;
})(typeof window !== "undefined" ? window : globalThis);
