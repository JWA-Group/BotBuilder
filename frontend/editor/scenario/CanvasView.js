/**
 * CanvasView — dynamic block palette and properties panel driven by /plugins ui.json.
 */
(function (global) {
  "use strict";

  var registry = [];
  var rawRegistry = [];

  function tr(key, params) {
    return typeof global.t === "function" ? global.t(key, params) : key;
  }

  function localizeRegistryFromRaw() {
    if (typeof PluginI18n !== "undefined" && PluginI18n.localizePluginRegistry) {
      registry = PluginI18n.localizePluginRegistry(rawRegistry);
    } else {
      registry = rawRegistry.slice();
    }
    return registry;
  }

  var BLOCK_COLOR_PRESETS = [
    { id: "soft-blue", label: "Soft Blue", color: "#7BA7D8" },
    { id: "mint", label: "Mint Green", color: "#7BC9A6" },
    { id: "amber", label: "Warning Amber", color: "#E8C078" },
    { id: "lavender", label: "Lavender", color: "#B39DDB" },
    { id: "coral", label: "Coral Rose", color: "#E89B9B" },
    { id: "slate", label: "Cool Slate", color: "#94A3B8" },
    { id: "peach", label: "Soft Peach", color: "#F0B8A8" },
    { id: "default", labelKey: "editor.color_default", color: "" },
  ];

  function colorPresetLabel(preset) {
    if (preset.labelKey) return tr(preset.labelKey);
    return preset.label || "";
  }

  function getBlockAccentColor(blockData, pluginMeta) {
    if (blockData && blockData.data && blockData.data.color) {
      return blockData.data.color;
    }
    if (pluginMeta && pluginMeta.color) {
      return pluginMeta.color;
    }
    return "";
  }

  function applyBlockAccent(el, blockData, pluginMeta) {
    if (!el || !blockData) return;
    var color = getBlockAccentColor(blockData, pluginMeta);
    if (color) {
      el.style.setProperty("--block-accent", color);
    } else {
      el.style.removeProperty("--block-accent");
    }
  }

  function renderBlockColorPickerHtml(blockId, currentColor) {
    var html =
      '<section class="editor-section block-color-section" id="block-color-section-' +
      blockId +
      '"><h4 class="editor-section-title">' +
      tr("editor.block_color_title") +
      "</h4>" +
      '<p class="editor-hint">' +
      tr("editor.block_color_hint") +
      '</p><div class="block-color-palette" role="listbox" aria-label="' +
      tr("editor.block_color_aria") +
      '">';
    BLOCK_COLOR_PRESETS.forEach(function (preset) {
      var presetLabel = colorPresetLabel(preset);
      var active =
        (!currentColor && !preset.color) || currentColor === preset.color ? " is-active" : "";
      var cls = "block-color-swatch" + active + (preset.color ? "" : " is-default");
      var preview = preset.color || "transparent";
      html +=
        '<button type="button" class="' +
        cls +
        '" role="option" data-color="' +
        (preset.color || "") +
        '" title="' +
        presetLabel +
        '" aria-label="' +
        presetLabel +
        '" style="background-color:' +
        preview +
        ';background:' +
        preview +
        '"></button>';
    });
    html += "</div></section>";
    return html;
  }

  function bindBlockColorPicker(container, blockData, ctx) {
    if (!container || !blockData) return;
    var section = container.querySelector("#block-color-section-" + blockData.id);
    if (!section) return;
    section.querySelectorAll(".block-color-swatch").forEach(function (btn) {
      btn.onclick = function () {
        var color = btn.getAttribute("data-color") || "";
        if (color) blockData.data.color = color;
        else delete blockData.data.color;
        section.querySelectorAll(".block-color-swatch").forEach(function (b) {
          b.classList.toggle("is-active", b === btn);
        });
        if (typeof ctx.onUpdate === "function") ctx.onUpdate(blockData);
        else if (typeof ctx.renderBlock === "function") ctx.renderBlock(blockData);
      };
    });
  }

  function getApiBase() {
    if (typeof global.getApiBase === "function") return global.getApiBase();
    if (global.location && global.location.origin) return global.location.origin + "/api";
    return "http://127.0.0.1:8000/api";
  }

  function getPluginByType(type, list) {
    var plugins = list || registry;
    for (var i = 0; i < plugins.length; i++) {
      if (plugins[i].type === type) return plugins[i];
    }
    return null;
  }

  function isPhantomType(type, list) {
    if (!type) return true;
    return !getPluginByType(type, list);
  }

  function getInstalledTypes(list) {
    var types = {};
    (list || registry).forEach(function (plugin) {
      if (plugin && plugin.type) types[plugin.type] = true;
    });
    return types;
  }

  function listPhantomTypes(blocks, list) {
    var seen = {};
    var missing = [];
    (blocks || []).forEach(function (block) {
      var type = block && block.type;
      if (!type || seen[type]) return;
      seen[type] = true;
      if (isPhantomType(type, list)) missing.push(type);
    });
    return missing.sort();
  }

  function computeRequiredPlugins(blocks) {
    var types = {};
    (blocks || []).forEach(function (block) {
      if (block && block.type) types[block.type] = true;
    });
    return Object.keys(types).sort();
  }

  function renderPhantomBlockHtml(type, escapeHtmlFn) {
    var esc = typeof escapeHtmlFn === "function" ? escapeHtmlFn : function (v) { return String(v || ""); };
    return (
      '<div class="title phantom-title">Phantom: ' +
      esc(type) +
      " (Missing)</div>" +
      '<div class="preview-text phantom-preview">Missing plugin — locked for editing</div>' +
      '<div class="output" data-index="0"></div>'
    );
  }

  function renderPhantomPropertiesPanel(container, blockData, ctx) {
    if (!container || !blockData) return;
    ctx = ctx || {};
    var esc = typeof ctx.escapeHtml === "function" ? ctx.escapeHtml : function (v) { return String(v || ""); };
    container.innerHTML =
      '<section class="editor-section phantom-panel-notice">' +
      '<h4 class="editor-section-title">Phantom: ' +
      esc(blockData.type) +
      "</h4>" +
      '<p class="editor-hint phantom-notice-text">This block is currently locked because its parent plugin is missing from your system. Install the plugin to edit or delete this node to run compilation.</p>' +
      "</section>";
  }

  function deepClone(obj) {
    return JSON.parse(JSON.stringify(obj || {}));
  }

  function applyDefaults(type, data, list) {
    var plugin = getPluginByType(type, list);
    var out = deepClone(plugin && plugin.defaults ? plugin.defaults : {});
    if (data && typeof data === "object") {
      Object.keys(data).forEach(function (k) {
        if (data[k] !== undefined) out[k] = data[k];
      });
    }
    normalizeData(type, out, list);
    return out;
  }

  function normalizeData(type, data, list) {
    if (!data) return;
    if (type === "menu" && Array.isArray(data.buttons)) {
      data.buttons = data.buttons.map(function (b) {
        if (typeof b === "string") return { text: b, url: "" };
        var o = { text: b.text || "", url: b.url || "" };
        if (b.request_contact) o.request_contact = true;
        if (b.request_location) o.request_location = true;
        return o;
      });
    }
    if (type === "message") {
      if (!data.media) data.media = { type: null, files: [] };
      if (!Array.isArray(data.inlineButtons)) data.inlineButtons = [];
      if (!Array.isArray(data.inlineButtonRowBreaks)) data.inlineButtonRowBreaks = [0];
    }
    if (type === "menu" && !Array.isArray(data.buttonRowBreaks)) {
      data.buttonRowBreaks = [0];
    }
    var plugin = getPluginByType(type, list);
    if (plugin && plugin.defaults) {
      Object.keys(plugin.defaults).forEach(function (k) {
        if (data[k] === undefined) data[k] = deepClone(plugin.defaults[k]);
      });
    }
  }

  function fieldVisible(field, data) {
    if (field.hideWhen) {
      var hk = Object.keys(field.hideWhen);
      for (var hi = 0; hi < hk.length; hi++) {
        var hv = field.hideWhen[hk[hi]];
        var cur = data[hk[hi]];
        if (Array.isArray(hv) ? hv.indexOf(cur) >= 0 : cur === hv) return false;
      }
    }
    if (field.showWhen) {
      var sk = Object.keys(field.showWhen);
      for (var si = 0; si < sk.length; si++) {
        var sv = field.showWhen[sk[si]];
        var val = data[sk[si]];
        if (Array.isArray(sv)) {
          if (sv.indexOf(val) < 0) return false;
        } else if (val !== sv) {
          return false;
        }
      }
    }
    return true;
  }

  function setNested(obj, key, value) {
    obj[key] = value;
  }

  function getNested(obj, key) {
    return obj == null ? undefined : obj[key];
  }

  function loadPlugins() {
    var url = getApiBase().replace(/\/$/, "") + "/plugins";
    return fetch(url)
      .then(function (res) {
        if (!res.ok) throw new Error("Failed to load plugins");
        return res.json();
      })
      .then(function (body) {
        rawRegistry = body.plugins || [];
        localizeRegistryFromRaw();
        return registry;
      })
      .catch(function () {
        rawRegistry = [];
        registry = [];
        return registry;
      });
  }

  function buildPalette(container, plugins, onAddNode, options) {
    if (!container) return;
    options = options || {};
    var keep = options.preserveSelectors || ["#ai-scenario-btn", "#custom-plugins-toggle", "#history-mode-btn", ".toolbar-save", "#save-scenario-btn"];
    var preserved = [];
    keep.forEach(function (sel) {
      var el = container.querySelector(sel);
      if (el) preserved.push({ parent: el.parentNode, node: el });
    });

    container.innerHTML = "";

    preserved.forEach(function (p) {
      if (p.node.id === "save-scenario-btn" || p.node.classList.contains("toolbar-save")) return;
      container.appendChild(p.node);
    });

    var showCustom = options.showCustomPlugins !== false;
    var list = plugins || registry;
    list.forEach(function (plugin) {
      if (plugin.palette === false) return;
      var isCustom = plugin.custom === true || plugin.builtin === false;
      if (isCustom && !showCustom) return;
      var labelText = plugin.name || plugin.type || "";
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "tool-btn tool-circle" + (isCustom ? " tool-custom" : "");
      btn.setAttribute("data-tool", plugin.type);
      if (isCustom) btn.setAttribute("data-custom-plugin", "1");
      btn.removeAttribute("title");
      if (plugin.color) btn.style.setProperty("--tool-accent", plugin.color);
      btn.onclick = function () {
        if (typeof onAddNode === "function") onAddNode(plugin.type);
      };
      var icon = document.createElement("span");
      icon.className = "tool-icon-circle";
      icon.textContent = plugin.icon || "🔧";
      btn.appendChild(icon);
      var label = document.createElement("span");
      label.className = "tool-label";
      label.textContent = labelText;
      btn.appendChild(label);
      container.appendChild(btn);
    });

    if (typeof options.onDatabaseTool === "function") {
      var dbBtn = document.createElement("button");
      dbBtn.type = "button";
      dbBtn.className = "tool-btn tool-circle";
      dbBtn.removeAttribute("title");
      dbBtn.onclick = options.onDatabaseTool;
      var dbIcon = document.createElement("span");
      dbIcon.className = "tool-icon-circle";
      dbIcon.textContent = "🗄️";
      dbBtn.appendChild(dbIcon);
      var dbLabel = document.createElement("span");
      dbLabel.className = "tool-label";
      dbLabel.textContent = tr("editor.database_tool");
      dbBtn.appendChild(dbLabel);
      container.appendChild(dbBtn);
    }

    preserved.forEach(function (p) {
      if (p.node.id === "save-scenario-btn" || p.node.classList.contains("toolbar-save")) {
        container.appendChild(p.node);
      }
    });
  }

  function renderTagSelect(blockId, field, data, ctx) {
    var tagOpts = (ctx.scenarioTags || [])
      .map(function (t) {
        var sel = (data.tagId || data.tag) === t.id ? " selected" : "";
        return (
          '<option value="' +
          ctx.escapeHtml(t.id) +
          '"' +
          sel +
          ">" +
          ctx.escapeHtml(t.name) +
          "</option>"
        );
      })
      .join("");
    var html =
      '<section class="editor-section"><h4 class="editor-section-title">' +
      ctx.escapeHtml(field.label || tr("plugin.send_message.field.tagId.label")) +
      "</h4>";
    if (field.hint) html += '<p class="editor-hint">' + ctx.escapeHtml(field.hint) + "</p>";
    html +=
      '<select class="editor-field" id="field-' +
      field.key +
      "-" +
      blockId +
      '"><option value="">' +
      tr("editor.tag_none") +
      "</option>" +
      tagOpts +
      '</select><div class="editor-tag-actions">' +
      '<button type="button" class="editor-btn secondary" data-tag-action="create">' +
      tr("editor.tag_create") +
      '</button><button type="button" class="editor-btn secondary" data-tag-action="edit">' +
      tr("editor.tag_edit") +
      '</button><button type="button" class="editor-btn secondary" data-tag-action="delete">' +
      tr("editor.tag_delete") +
      "</button>" +
      "</div></section>";
    return html;
  }

  function bindTagActions(container, blockId, ctx) {
    container.querySelectorAll("[data-tag-action]").forEach(function (btn) {
      btn.onclick = function () {
        var action = btn.getAttribute("data-tag-action");
        if (action === "create" && ctx.createTagFromBlock) ctx.createTagFromBlock(blockId);
        if (action === "edit" && ctx.editTagFromBlock) ctx.editTagFromBlock(blockId);
        if (action === "delete" && ctx.deleteTagFromBlock) ctx.deleteTagFromBlock(blockId);
      };
    });
    var sel = container.querySelector('[id^="field-tagId-"]');
    if (sel) {
      sel.onchange = function () {
        if (ctx.updateBlockTagId) ctx.updateBlockTagId(blockId, this.value);
        else if (ctx.onFieldChange) ctx.onFieldChange("tagId", this.value);
      };
    }
  }

  function renderPropertiesPanel(container, blockData, plugin, ctx) {
    if (!container || !blockData || !plugin) return;
    ctx = ctx || {};
    var id = blockData.id;
    var data = blockData.data;
    var html = "";
    var fields = plugin.fields || [];

    if (blockData.type === "command" && ctx.connections && ctx.blocks) {
      var conn = ctx.connections.find(function (c) {
        return c.from === id && String(c.outputIndex) === "0";
      });
      if (conn) {
        var targetBlock = ctx.blocks.find(function (b) {
          return b.id === conn.to;
        });
        if (targetBlock && (targetBlock.data.tagId || targetBlock.data.tag)) {
          blockData.data.tagId = targetBlock.data.tagId || targetBlock.data.tag;
        }
      }
    }

    html += renderBlockColorPickerHtml(id, data.color || "");

    fields.forEach(function (field) {
      if (!fieldVisible(field, data)) return;

      if (field.type === "info") {
        html +=
          '<section class="editor-section"><h4 class="editor-section-title">' +
          ctx.escapeHtml(field.label || "") +
          '</h4><p class="editor-hint">' +
          ctx.escapeHtml(field.text || "") +
          "</p></section>";
        return;
      }

      if (field.type === "tag_select") {
        html += renderTagSelect(id, field, data, ctx);
        return;
      }

      if (field.type === "media") {
        html +=
          '<section class="editor-section"><h4 class="editor-section-title">' +
          ctx.escapeHtml(field.label || tr("plugin.send_message.field.media.label")) +
          "</h4>";
        if (field.hint) html += '<p class="editor-hint">' + ctx.escapeHtml(field.hint) + "</p>";
        var mediaType = (data.media && data.media.type) || "";
        html +=
          '<select class="editor-field" id="msg-media-type-' +
          id +
          '"><option value="">' +
          tr("editor.media_none") +
          '</option><option value="photo"' +
          (mediaType === "photo" ? " selected" : "") +
          ">" +
          tr("editor.media_photo") +
          '</option><option value="video"' +
          (mediaType === "video" ? " selected" : "") +
          ">" +
          tr("editor.media_video") +
          '</option><option value="document"' +
          (mediaType === "document" ? " selected" : "") +
          ">" +
          tr("editor.media_document") +
          '</option><option value="audio"' +
          (mediaType === "audio" ? " selected" : "") +
          ">" +
          tr("editor.media_audio") +
          '</option></select><div class="media-upload-zone" id="msg-media-zone-' +
          id +
          '"><input type="file" id="msg-media-input-' +
          id +
          '" style="display:none"/><span class="media-zone-text">' +
          tr("editor.media_upload") +
          '</span></div><div class="media-files-list" id="msg-media-files-' +
          id +
          '"></div></section>';
        return;
      }

      if (field.type === "inline_buttons") {
        html +=
          '<section class="editor-section"><h4 class="editor-section-title">' +
          ctx.escapeHtml(field.label || tr("plugin.send_message.field.inlineButtons.label")) +
          "</h4>";
        if (field.hint) html += '<p class="editor-hint">' + ctx.escapeHtml(field.hint) + "</p>";
        html +=
          '<div id="msg-inline-' +
          id +
          '"></div><button type="button" class="editor-btn add-btn-single" id="add-inline-' +
          id +
          '">' +
          tr("editor.add_button") +
          "</button></section>";
        return;
      }

      if (field.type === "menu_buttons") {
        html +=
          '<section class="editor-section"><h4 class="editor-section-title">' +
          ctx.escapeHtml(field.label || tr("plugin.menu_node.field.buttons.label")) +
          "</h4>";
        if (field.hint) html += '<p class="editor-hint">' + ctx.escapeHtml(field.hint) + "</p>";
        html +=
          '<div id="menu-btns-' +
          id +
          '"></div><button type="button" class="editor-btn add-btn-single" id="add-menu-btn-' +
          id +
          '">' +
          tr("editor.add_button") +
          "</button></section>";
        return;
      }

      if (field.type === "field_autocomplete") {
        html +=
          '<section class="editor-section"><h4 class="editor-section-title">' +
          ctx.escapeHtml(field.label || field.key) +
          "</h4>";
        if (field.hint) html += '<p class="editor-hint">' + ctx.escapeHtml(field.hint) + "</p>";
        html +=
          '<div class="field-name-autocomplete-wrap"><input class="editor-field" type="text" id="field-' +
          field.key +
          "-" +
          id +
          '" value="' +
          ctx.escapeHtml(getNested(data, field.key) || "") +
          '" placeholder="' +
          ctx.escapeHtml(field.placeholder || "") +
          '" autocomplete="off"/><div class="field-name-dropdown" id="field-' +
          field.key +
          "-dropdown-" +
          id +
          '"></div></div></section>';
        return;
      }

      html += '<section class="editor-section"><h4 class="editor-section-title">' + ctx.escapeHtml(field.label || field.key) + "</h4>";
      if (field.hint) html += '<p class="editor-hint">' + ctx.escapeHtml(field.hint) + "</p>";

      var val = getNested(data, field.key);
      var fid = "field-" + field.key + "-" + id;

      if (field.type === "textarea") {
        html +=
          '<textarea class="editor-field" id="' +
          fid +
          '" rows="' +
          (field.rows || 4) +
          '" placeholder="' +
          ctx.escapeHtml(field.placeholder || "") +
          '"' +
          (field.maxLength ? ' maxlength="' + field.maxLength + '"' : "") +
          ">" +
          ctx.escapeHtml(val || "") +
          "</textarea>";
        if (field.maxLength) {
          html += '<span class="char-counter" id="' + fid + '-counter">' + (val || "").length + "/" + field.maxLength + "</span>";
        }
      } else if (field.type === "checkbox") {
        html +=
          '<label class="editor-checkbox"><input type="checkbox" id="' +
          fid +
          '"' +
          (val ? " checked" : "") +
          "/> " +
          ctx.escapeHtml(field.label || field.key) +
          "</label>";
      } else if (field.type === "select") {
        html += '<select class="editor-field" id="' + fid + '">';
        (field.options || []).forEach(function (opt) {
          var selected = val === opt.value ? " selected" : "";
          html +=
            '<option value="' +
            ctx.escapeHtml(opt.value) +
            '"' +
            selected +
            ">" +
            ctx.escapeHtml(opt.label) +
            "</option>";
        });
        html += "</select>";
      } else {
        var inputType = field.type === "number" ? "number" : "text";
        html +=
          '<input class="editor-field" type="' +
          inputType +
          '" id="' +
          fid +
          '" value="' +
          ctx.escapeHtml(val == null ? "" : String(val)) +
          '" placeholder="' +
          ctx.escapeHtml(field.placeholder || "") +
          '"/>';
      }
      html += "</section>";
    });

    container.innerHTML = html;
    bindTagActions(container, id, ctx);
    bindBlockColorPicker(container, blockData, ctx);

    fields.forEach(function (field) {
      if (!field.key || !fieldVisible(field, data)) return;
      if (
        field.type === "tag_select" ||
        field.type === "info" ||
        field.type === "media" ||
        field.type === "inline_buttons" ||
        field.type === "menu_buttons"
      ) {
        return;
      }

      var fid = "field-" + field.key + "-" + id;
      var el = document.getElementById(fid);
      if (!el) return;

      function notify() {
        if (typeof ctx.onUpdate === "function") ctx.onUpdate(blockData);
        else if (typeof ctx.renderBlock === "function") ctx.renderBlock(blockData);
      }

      if (field.type === "textarea") {
        el.oninput = function () {
          var v = field.maxLength ? this.value.slice(0, field.maxLength) : this.value;
          setNested(data, field.key, v);
          var counter = document.getElementById(fid + "-counter");
          if (counter && field.maxLength) counter.textContent = v.length + "/" + field.maxLength;
          notify();
        };
      } else if (field.type === "checkbox") {
        el.onchange = function () {
          setNested(data, field.key, this.checked);
          notify();
        };
      } else if (field.type === "select") {
        el.onchange = function () {
          setNested(data, field.key, this.value);
          notify();
          if (typeof ctx.refreshPanel === "function") ctx.refreshPanel(blockData);
        };
      } else if (field.type === "field_autocomplete") {
        el.oninput = function () {
          setNested(data, field.key, this.value);
          notify();
        };
        if (ctx.setupFieldNameAutocomplete) {
          ctx.setupFieldNameAutocomplete(id, "field-" + field.key, "field-" + field.key + "-dropdown-" + id, field.key);
        }
      } else if (field.key === "command") {
        el.oninput = function () {
          var v = "/" + (this.value || "").replace(/^\/+/, "").slice(0, 64);
          setNested(data, field.key, v || "/help");
          notify();
        };
      } else {
        el.oninput = el.onchange = function () {
          setNested(data, field.key, this.value);
          notify();
        };
      }
    });

    if (ctx.setupMessageMediaEditor) ctx.setupMessageMediaEditor(id);
    if (ctx.renderInlineEditor) ctx.renderInlineEditor(id);
    if (ctx.renderMenuButtonsEditor) ctx.renderMenuButtonsEditor(id);

    var addInline = document.getElementById("add-inline-" + id);
    if (addInline && ctx.addInlineButton) addInline.onclick = function () { ctx.addInlineButton(id); };
    var addMenu = document.getElementById("add-menu-btn-" + id);
    if (addMenu && ctx.addButton) addMenu.onclick = function () { ctx.addButton(id); };

    if (blockData.type === "command" && ctx.updateCommandTagId) {
      var tagSel = container.querySelector('[id^="field-tagId-"]');
      if (tagSel) tagSel.onchange = function () { ctx.updateCommandTagId(id, this.value); };
    }
  }

  function getBlockTitle(plugin) {
    if (!plugin) return tr("editor.block_default_title");
    return (plugin.icon ? plugin.icon + " " : "") + (plugin.name || plugin.type);
  }

  function refreshPluginLocales() {
    localizeRegistryFromRaw();
    return registry;
  }

  var PREVIEW_BLOCK_W = 160;
  var PREVIEW_BLOCK_H = 56;
  var PREVIEW_PAD = 48;

  function computeGraphBounds(blocks) {
    var minX = Infinity;
    var minY = Infinity;
    var maxX = -Infinity;
    var maxY = -Infinity;
    (blocks || []).forEach(function (block) {
      var x = Number(block.x) || 0;
      var y = Number(block.y) || 0;
      minX = Math.min(minX, x);
      minY = Math.min(minY, y);
      maxX = Math.max(maxX, x + PREVIEW_BLOCK_W);
      maxY = Math.max(maxY, y + PREVIEW_BLOCK_H);
    });
    if (!isFinite(minX)) {
      minX = 0;
      minY = 0;
      maxX = PREVIEW_BLOCK_W;
      maxY = PREVIEW_BLOCK_H;
    }
    return {
      minX: minX,
      minY: minY,
      width: Math.max(PREVIEW_BLOCK_W, maxX - minX),
      height: Math.max(PREVIEW_BLOCK_H, maxY - minY),
    };
  }

  function blockStagePosition(block, bounds) {
    return {
      x: (Number(block.x) || 0) - bounds.minX + PREVIEW_PAD,
      y: (Number(block.y) || 0) - bounds.minY + PREVIEW_PAD,
    };
  }

  function drawGraphConnectionsSvg(svg, blocks, connections, bounds) {
    var blockMap = {};
    (blocks || []).forEach(function (block) {
      blockMap[block.id] = block;
    });
    var paths = "";
    (connections || []).forEach(function (conn) {
      var from = blockMap[conn.from];
      var to = blockMap[conn.to];
      if (!from || !to) return;
      var fp = blockStagePosition(from, bounds);
      var tp = blockStagePosition(to, bounds);
      var x1 = fp.x + PREVIEW_BLOCK_W / 2;
      var y1 = fp.y + PREVIEW_BLOCK_H;
      var x2 = tp.x + PREVIEW_BLOCK_W / 2;
      var y2 = tp.y;
      paths +=
        '<path d="M' +
        x1 +
        " " +
        y1 +
        " C " +
        (x1 + 40) +
        " " +
        y1 +
        ", " +
        (x2 - 40) +
        " " +
        y2 +
        ", " +
        x2 +
        " " +
        y2 +
        '" fill="none" stroke="#94a3b8" stroke-width="2"/>';
    });
    svg.innerHTML = paths;
  }

  function buildGraphStageHtml(blocks, connections) {
    blocks = blocks || [];
    connections = connections || [];
    var bounds = computeGraphBounds(blocks);
    var stageW = bounds.width + PREVIEW_PAD * 2;
    var stageH = bounds.height + PREVIEW_PAD * 2;

    var wrap = document.createElement("div");
    wrap.className = "cv-graph-stage";
    wrap.style.width = stageW + "px";
    wrap.style.height = stageH + "px";

    var grid = document.createElement("div");
    grid.className = "cv-graph-grid";
    wrap.appendChild(grid);

    var svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "cv-graph-connections");
    svg.setAttribute("width", String(stageW));
    svg.setAttribute("height", String(stageH));
    drawGraphConnectionsSvg(svg, blocks, connections, bounds);
    wrap.appendChild(svg);

    var layer = document.createElement("div");
    layer.className = "cv-graph-blocks";
    blocks.forEach(function (block) {
      var pos = blockStagePosition(block, bounds);
      var plugin = getPluginByType(block.type);
      var color = (plugin && plugin.color) || "#6366f1";
      var node = document.createElement("div");
      node.className = "cv-graph-block";
      node.style.left = pos.x + "px";
      node.style.top = pos.y + "px";
      node.style.width = PREVIEW_BLOCK_W + "px";
      node.style.height = PREVIEW_BLOCK_H + "px";
      node.style.background = color;
      var title = getBlockTitle(plugin) || block.type || tr("editor.block_default_title");
      node.innerHTML =
        '<div class="cv-graph-block-title">' +
        escapeHtmlShort(title.slice(0, 22)) +
        '</div><div class="cv-graph-block-type">' +
        escapeHtmlShort(block.type || "") +
        "</div>";
      layer.appendChild(node);
    });
    wrap.appendChild(layer);

    return { stage: wrap, width: stageW, height: stageH, bounds: bounds };
  }

  function escapeHtmlShort(v) {
    return String(v == null ? "" : v)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }

  function mountInteractiveGraphPreview(container, blocks, connections, options) {
    options = options || {};
    if (!container) return null;
    container.innerHTML = "";
    container.classList.add("cv-graph-viewport");

    var built = buildGraphStageHtml(blocks, connections);
    var stage = built.stage;
    var viewport = container;

    var view = {
      zoom: 1,
      panX: 0,
      panY: 0,
      dragging: false,
      dragStartX: 0,
      dragStartY: 0,
      panStartX: 0,
      panStartY: 0,
    };

    function applyTransform() {
      stage.style.transform =
        "translate(" + view.panX + "px, " + view.panY + "px) scale(" + view.zoom + ")";
    }

    function clampZoom(z) {
      return Math.max(0.12, Math.min(4, z));
    }

    function setZoom(next, pivotX, pivotY) {
      var rect = viewport.getBoundingClientRect();
      var px = pivotX != null ? pivotX - rect.left : rect.width / 2;
      var py = pivotY != null ? pivotY - rect.top : rect.height / 2;
      var worldX = (px - view.panX) / view.zoom;
      var worldY = (py - view.panY) / view.zoom;
      view.zoom = clampZoom(next);
      view.panX = px - worldX * view.zoom;
      view.panY = py - worldY * view.zoom;
      applyTransform();
      if (typeof options.onZoomChange === "function") options.onZoomChange(view.zoom);
    }

    function fitToView() {
      var vw = viewport.clientWidth || 1;
      var vh = viewport.clientHeight || 1;
      view.zoom = clampZoom(Math.min(vw / built.width, vh / built.height) * 0.92);
      view.panX = (vw - built.width * view.zoom) / 2;
      view.panY = (vh - built.height * view.zoom) / 2;
      applyTransform();
      if (typeof options.onZoomChange === "function") options.onZoomChange(view.zoom);
    }

    viewport.appendChild(stage);
    applyTransform();
    requestAnimationFrame(fitToView);

    function onWheel(e) {
      if (options.interactive === false) return;
      e.preventDefault();
      var factor = e.deltaY > 0 ? 0.92 : 1.08;
      setZoom(view.zoom * factor, e.clientX, e.clientY);
    }

    function onPointerDown(e) {
      if (options.interactive === false) return;
      if (e.button !== 0 && e.button !== 1) return;
      view.dragging = true;
      view.dragStartX = e.clientX;
      view.dragStartY = e.clientY;
      view.panStartX = view.panX;
      view.panStartY = view.panY;
      viewport.classList.add("cv-graph-viewport-dragging");
      e.preventDefault();
    }

    function onPointerMove(e) {
      if (!view.dragging) return;
      view.panX = view.panStartX + (e.clientX - view.dragStartX);
      view.panY = view.panStartY + (e.clientY - view.dragStartY);
      applyTransform();
    }

    function onPointerUp() {
      view.dragging = false;
      viewport.classList.remove("cv-graph-viewport-dragging");
    }

    viewport.addEventListener("wheel", onWheel, { passive: false });
    viewport.addEventListener("mousedown", onPointerDown);
    global.addEventListener("mousemove", onPointerMove);
    global.addEventListener("mouseup", onPointerUp);

    return {
      fitToView: fitToView,
      setZoom: function (z) {
        setZoom(z);
      },
      zoomBy: function (delta) {
        setZoom(view.zoom * (delta > 0 ? 1.1 : 0.9));
      },
      reset: function () {
        fitToView();
      },
      destroy: function () {
        viewport.removeEventListener("wheel", onWheel);
        viewport.removeEventListener("mousedown", onPointerDown);
        global.removeEventListener("mousemove", onPointerMove);
        global.removeEventListener("mouseup", onPointerUp);
        container.innerHTML = "";
        container.classList.remove("cv-graph-viewport", "cv-graph-viewport-dragging");
      },
      getZoom: function () {
        return view.zoom;
      },
    };
  }

  function captureGraphPreview(blocks, connections, options) {
    options = options || {};
    blocks = blocks || [];
    connections = connections || [];
    var built = buildGraphStageHtml(blocks, connections);
    var stageW = built.width;
    var stageH = built.height;
    var maxThumb = options.maxThumbWidth || 0;

    var canvas = document.createElement("canvas");
    canvas.width = stageW;
    canvas.height = stageH;
    var ctx = canvas.getContext("2d");
    if (!ctx) return "";

    ctx.fillStyle = "#f8fafc";
    ctx.fillRect(0, 0, stageW, stageH);

    ctx.strokeStyle = "rgba(148, 163, 184, 0.35)";
    ctx.lineWidth = 1;
    for (var gx = 0; gx < stageW; gx += 20) {
      ctx.beginPath();
      ctx.moveTo(gx, 0);
      ctx.lineTo(gx, stageH);
      ctx.stroke();
    }
    for (var gy = 0; gy < stageH; gy += 20) {
      ctx.beginPath();
      ctx.moveTo(0, gy);
      ctx.lineTo(stageW, gy);
      ctx.stroke();
    }

    var blockMap = {};
    blocks.forEach(function (block) {
      blockMap[block.id] = block;
    });
    ctx.strokeStyle = "#94a3b8";
    ctx.lineWidth = 2;
    connections.forEach(function (conn) {
      var from = blockMap[conn.from];
      var to = blockMap[conn.to];
      if (!from || !to) return;
      var fp = blockStagePosition(from, built.bounds);
      var tp = blockStagePosition(to, built.bounds);
      var x1 = fp.x + PREVIEW_BLOCK_W / 2;
      var y1 = fp.y + PREVIEW_BLOCK_H;
      var x2 = tp.x + PREVIEW_BLOCK_W / 2;
      var y2 = tp.y;
      ctx.beginPath();
      ctx.moveTo(x1, y1);
      ctx.bezierCurveTo(x1 + 40, y1, x2 - 40, y2, x2, y2);
      ctx.stroke();
    });

    blocks.forEach(function (block) {
      var plugin = getPluginByType(block.type);
      var color = (plugin && plugin.color) || "#6366f1";
      var pos = blockStagePosition(block, built.bounds);
      ctx.fillStyle = color;
      ctx.strokeStyle = "rgba(15, 23, 42, 0.12)";
      ctx.lineWidth = 1;
      roundRect(ctx, pos.x, pos.y, PREVIEW_BLOCK_W, PREVIEW_BLOCK_H, 8);
      ctx.fill();
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.font = "bold 12px sans-serif";
      var title = getBlockTitle(plugin) || block.type || tr("editor.block_default_title");
      ctx.fillText(title.slice(0, 18), pos.x + 8, pos.y + 22);
      ctx.font = "10px sans-serif";
      ctx.fillStyle = "rgba(255,255,255,0.85)";
      ctx.fillText(block.type || "", pos.x + 8, pos.y + 38);
    });

    if (maxThumb > 0 && stageW > maxThumb) {
      var scale = maxThumb / stageW;
      var thumb = document.createElement("canvas");
      thumb.width = Math.max(1, Math.round(stageW * scale));
      thumb.height = Math.max(1, Math.round(stageH * scale));
      var tctx = thumb.getContext("2d");
      if (tctx) {
        tctx.drawImage(canvas, 0, 0, thumb.width, thumb.height);
        return thumb.toDataURL("image/png");
      }
    }
    return canvas.toDataURL("image/png");
  }

  function setHistoryGhostMode(active, options) {
    options = options || {};
    var wrap = document.getElementById("canvas-wrapper");
    if (!wrap) return;
    wrap.classList.toggle("history-ghost-mode", !!active);
    var banner = document.getElementById("history-ghost-banner");
    if (!active) {
      if (banner) banner.remove();
      return;
    }
    if (!banner) {
      banner = document.createElement("div");
      banner.id = "history-ghost-banner";
      banner.className = "history-ghost-banner";
      banner.setAttribute("role", "status");
      banner.innerHTML =
        '<div class="history-ghost-banner-text">' +
        '<span class="history-ghost-banner-icon" aria-hidden="true">H</span>' +
        '<span id="history-ghost-banner-label"></span>' +
        "</div>" +
        '<div class="history-ghost-banner-actions">' +
        '<button type="button" class="history-ghost-apply" id="history-ghost-apply">' +
        tr("editor.history_apply") +
        '</button><button type="button" class="history-ghost-restore" id="history-ghost-restore">' +
        tr("editor.history_restore") +
        '</button><button type="button" class="history-ghost-exit" id="history-ghost-exit">' +
        tr("editor.history_exit") +
        "</button>" +
        "</div>";
      wrap.appendChild(banner);
    }
    var label = document.getElementById("history-ghost-banner-label");
    if (label) {
      label.textContent = options.label || tr("editor.history_view_label");
    }
  }

  function roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  global.CanvasView = {
    loadPlugins: loadPlugins,
    refreshPluginLocales: refreshPluginLocales,
    getRegistry: function () { return registry; },
    setRegistry: function (list) {
      rawRegistry = list || [];
      localizeRegistryFromRaw();
    },
    getPluginByType: getPluginByType,
    isPhantomType: isPhantomType,
    getInstalledTypes: getInstalledTypes,
    listPhantomTypes: listPhantomTypes,
    computeRequiredPlugins: computeRequiredPlugins,
    renderPhantomBlockHtml: renderPhantomBlockHtml,
    renderPhantomPropertiesPanel: renderPhantomPropertiesPanel,
    applyDefaults: applyDefaults,
    normalizeData: normalizeData,
    buildPalette: buildPalette,
    renderPropertiesPanel: renderPropertiesPanel,
    getBlockTitle: getBlockTitle,
    fieldVisible: fieldVisible,
    captureGraphPreview: captureGraphPreview,
    mountInteractiveGraphPreview: mountInteractiveGraphPreview,
    computeGraphBounds: computeGraphBounds,
    setHistoryGhostMode: setHistoryGhostMode,
    BLOCK_COLOR_PRESETS: BLOCK_COLOR_PRESETS,
    getBlockAccentColor: getBlockAccentColor,
    applyBlockAccent: applyBlockAccent,
  };
})(typeof window !== "undefined" ? window : globalThis);
