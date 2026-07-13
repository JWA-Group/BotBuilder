/**
 * Localize plugin ui.json metadata (name, fields, options, defaults) via BB_LOCALES keys.
 */
(function (global) {
  "use strict";

  function tr(key, fallback, lang) {
    if (typeof global.t === "function") {
      var val = global.t(key, null, lang);
      if (val != null && val !== key) return val;
    }
    return fallback != null ? fallback : key;
  }

  function resolvePid(plugin) {
    if (typeof global.resolvePluginId === "function") return global.resolvePluginId(plugin);
    return String(plugin.pluginId || plugin.id || plugin.type || "");
  }

  function localizeDefaults(pid, defaults, lang) {
    if (!defaults || typeof defaults !== "object") return defaults;
    var out = JSON.parse(JSON.stringify(defaults));
    var prefix = "plugin." + pid + ".default.";
    Object.keys(out).forEach(function (k) {
      var val = out[k];
      if (typeof val === "string") {
        out[k] = tr(prefix + k, val, lang);
      } else if (k === "buttons" && Array.isArray(val)) {
        out[k] = val.map(function (btn, idx) {
          if (!btn || typeof btn !== "object") return btn;
          var copy = Object.assign({}, btn);
          if (copy.text) {
            copy.text = tr(prefix + "button_text", copy.text, lang);
          }
          return copy;
        });
      }
    });
    return out;
  }

  function localizePlugin(plugin, lang) {
    if (!plugin) return plugin;
    var copy = JSON.parse(JSON.stringify(plugin));
    var pid = resolvePid(plugin);
    if (!pid) return copy;
    var prefix = "plugin." + pid + ".";

    copy.name = tr(prefix + "name", copy.name, lang);
    if (copy.description) copy.description = tr(prefix + "desc", copy.description, lang);
    if (copy.defaults) copy.defaults = localizeDefaults(pid, copy.defaults, lang);

    (copy.fields || []).forEach(function (field, idx) {
      var fkey = field.key;
      if (fkey) {
        if (field.label) field.label = tr(prefix + "field." + fkey + ".label", field.label, lang);
        if (field.hint) field.hint = tr(prefix + "field." + fkey + ".hint", field.hint, lang);
        if (field.placeholder) {
          field.placeholder = tr(prefix + "field." + fkey + ".placeholder", field.placeholder, lang);
        }
        if (field.text) field.text = tr(prefix + "field." + fkey + ".text", field.text, lang);
        if (field.options) {
          field.options.forEach(function (opt) {
            opt.label = tr(prefix + "option." + fkey + "." + opt.value, opt.label, lang);
          });
        }
      } else if (field.type === "info") {
        var infoId = "i" + idx;
        if (field.label) field.label = tr(prefix + "info." + infoId + ".label", field.label, lang);
        if (field.text) field.text = tr(prefix + "info." + infoId + ".text", field.text, lang);
      }
    });

    return copy;
  }

  function localizePluginRegistry(plugins, lang) {
    var code = lang;
    if (code == null && typeof global.getLang === "function") code = global.getLang();
    return (plugins || []).map(function (p) {
      return localizePlugin(p, code);
    });
  }

  global.PluginI18n = {
    localizePlugin: localizePlugin,
    localizePluginRegistry: localizePluginRegistry,
  };
})(typeof window !== "undefined" ? window : globalThis);
