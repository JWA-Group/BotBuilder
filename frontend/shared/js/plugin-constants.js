/**

 * Встроенные плагины и определение id (совпадает с backend).

 */

(function (global) {

  "use strict";



  var BUILTIN_PLUGIN_IDS = [

    "start_node",

    "command_node",

    "send_message",

    "menu_node",

    "data_node",

    "condition_node",

    "weather_node",

    "note_node",

  ];



  /** type из ui.json → папка в /plugins (если API не отдаёт pluginId). */

  var BUILTIN_TYPE_TO_ID = {

    start: "start_node",

    command: "command_node",

    message: "send_message",

    menu: "menu_node",

    data: "data_node",

    condition: "condition_node",

    weather: "weather_node",

    note: "note_node",

  };



  function resolvePluginId(plugin) {

    if (!plugin) return "";

    if (plugin.pluginId) return String(plugin.pluginId);

    if (plugin.id) return String(plugin.id);

    var type = String(plugin.type || "");

    if (BUILTIN_TYPE_TO_ID[type]) return BUILTIN_TYPE_TO_ID[type];

    if (plugin.custom === true) return type;

    if (BUILTIN_PLUGIN_IDS.indexOf(type) >= 0) return type;

    return type;

  }



  function isBuiltinPluginId(pluginId, meta) {

    var id = String(pluginId || "");

    if (meta && meta.builtin === true) return true;

    if (meta && meta.builtin === false) return false;

    if (BUILTIN_PLUGIN_IDS.indexOf(id) >= 0) return true;

    if (meta) {

      var resolved = resolvePluginId(meta);

      if (resolved && BUILTIN_PLUGIN_IDS.indexOf(resolved) >= 0) return true;

    }

    return false;

  }



  function findPluginInList(plugins, pluginId) {

    var target = String(pluginId || "");

    if (!target) return null;

    var list = plugins || [];

    for (var i = 0; i < list.length; i++) {

      var p = list[i];

      if (resolvePluginId(p) === target) return p;

      if (String(p.type || "") === target) return p;

    }

    return null;

  }



  global.BUILTIN_PLUGIN_IDS = BUILTIN_PLUGIN_IDS;

  global.BUILTIN_TYPE_TO_ID = BUILTIN_TYPE_TO_ID;

  global.resolvePluginId = resolvePluginId;

  global.isBuiltinPluginId = isBuiltinPluginId;

  global.findPluginInList = findPluginInList;

})(typeof window !== "undefined" ? window : globalThis);

