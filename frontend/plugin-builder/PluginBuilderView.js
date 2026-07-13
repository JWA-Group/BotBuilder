/**
 * PluginBuilderView — custom block (plugin) creation wizard.
 */
(function (global) {
  "use strict";

  var ALLOWED_FIELD_TYPES = ["text", "textarea", "select", "checkbox", "number"];

  function tr(key, params) {
    return typeof global.t === "function" ? global.t(key, params) : key;
  }

  function fieldTypeLabel(type) {
    return tr("plugin_builder.field_type." + type) || type;
  }

  function getPageTitleText() {
    var nameEl = state.root && state.root.querySelector("#pb-node-name");
    var name = nameEl ? String(nameEl.value || "").trim() : "";
    if (state.readonly && state.existingPluginId) {
      return tr("plugin_builder.view_title", { name: name || state.existingPluginId });
    }
    if (state.existingPluginId) {
      return tr("plugin_builder.edit_title", { name: name || state.existingPluginId });
    }
    return tr("plugin_builder.title");
  }

  function updatePageTitle() {
    var title = state.root && state.root.querySelector("#pb-page-title");
    if (title) title.textContent = getPageTitleText();
  }

  function updateToolbarLabels() {
    if (!state.root) return;
    var saveBtn = state.root.querySelector("#pb-save-btn");
    if (saveBtn && !state.saving) saveBtn.textContent = tr("plugin_builder.save_publish");
    var resetBtn = state.root.querySelector("#pb-reset-template");
    if (resetBtn) resetBtn.textContent = tr("plugin_builder.reset_template");
    var deleteBtn = state.root.querySelector("#pb-delete-btn");
    if (deleteBtn) deleteBtn.textContent = tr("plugin_builder.delete");
    var addBtn = state.root.querySelector(".pb-add-field-submit");
    if (addBtn) addBtn.textContent = tr("plugin_builder.add_field");
    var back = state.root.querySelector("#pb-back-link");
    if (back) back.setAttribute("aria-label", tr("plugin_builder.back_aria"));
    var banner = state.root.querySelector("#pb-readonly-banner");
    if (banner) banner.textContent = tr("plugin_builder.readonly_banner");
    var typeSel = state.root.querySelector("#pb-new-field-type");
    if (typeSel) {
      typeSel.innerHTML = selectOptions(typeSel.value || "text");
    }
  }

  function applyStaticTranslations() {
    if (!state.root) return;
    updatePageTitle();
    updateToolbarLabels();
    var zones = [
      ["#pb-zone-a .pb-zone-head h2", "plugin_builder.zone1_title"],
      ["#pb-zone-a .pb-zone-head p", "plugin_builder.zone1_desc"],
      ["#pb-zone-b .pb-zone-head h2", "plugin_builder.zone2_title"],
      ["#pb-zone-b .pb-zone-head p", "plugin_builder.zone2_desc"],
      ["#pb-zone-c .pb-zone-head h2", "plugin_builder.zone3_title"],
      ["#pb-zone-c .pb-zone-head p", "plugin_builder.zone3_desc"],
    ];
    zones.forEach(function (item) {
      var el = state.root.querySelector(item[0]);
      if (el) el.textContent = tr(item[1]);
    });
    var labels = [
      ["label[for='pb-node-name']", "plugin_builder.block_name"],
      ["label[for='pb-plugin-id']", "plugin_builder.plugin_id"],
      ["label[for='pb-node-icon']", "plugin_builder.icon"],
      ["label[for='pb-node-color']", "plugin_builder.accent_color"],
      ["label[for='pb-new-field-label']", "plugin_builder.field_label"],
      ["label[for='pb-new-field-key']", "plugin_builder.field_key"],
      ["label[for='pb-new-field-type']", "plugin_builder.field_type"],
    ];
    labels.forEach(function (item) {
      var el = state.root.querySelector(item[0]);
      if (el) el.textContent = tr(item[1]);
    });
    var hints = [
      ["#pb-node-name + .pb-hint, #pb-node-name ~ .pb-hint", "plugin_builder.block_name_hint"],
    ];
    var nameInput = state.root.querySelector("#pb-node-name");
    if (nameInput) {
      nameInput.placeholder = tr("plugin_builder.block_name_ph");
      var hint = nameInput.parentElement && nameInput.parentElement.querySelector(".pb-hint");
      if (hint) hint.textContent = tr("plugin_builder.block_name_hint");
    }
    var idInput = state.root.querySelector("#pb-plugin-id");
    if (idInput) {
      idInput.placeholder = tr("plugin_builder.plugin_id_ph");
      var idHint = idInput.parentElement && idInput.parentElement.querySelector(".pb-hint");
      if (idHint) idHint.textContent = tr("plugin_builder.plugin_id_hint");
    }
    var lblInput = state.root.querySelector("#pb-new-field-label");
    if (lblInput) {
      lblInput.placeholder = tr("plugin_builder.field_label_ph");
      var lblHint = lblInput.parentElement && lblInput.parentElement.querySelector(".pb-hint");
      if (lblHint) lblHint.textContent = tr("plugin_builder.field_label_hint");
    }
    var keyInput = state.root.querySelector("#pb-new-field-key");
    if (keyInput) {
      keyInput.placeholder = tr("plugin_builder.field_key_ph");
      var keyHint = keyInput.parentElement && keyInput.parentElement.querySelector(".pb-hint");
      if (keyHint) keyHint.textContent = tr("plugin_builder.field_key_hint");
    }
    var intro = state.root.querySelector(".pb-form-intro");
    if (intro) intro.innerHTML = tr("plugin_builder.form_intro");
    renderFieldRows();
    updateCheatsheet();
    updatePreview();
  }

  var state = {
    root: null,
    fields: [],
    editor: null,
    monacoReady: false,
    saving: false,
    returnUrl: "/dashboard/index.html",
    existingPluginId: null,
    readonly: false,
    isBuiltin: false,
    pendingPluginData: null,
  };

  function getApiBase() {
    if (typeof global.getApiBase === "function") return global.getApiBase();
    if (global.location && global.location.origin) return global.location.origin + "/api";
    return "http://127.0.0.1:8000/api";
  }

  function getApiOrigin() {
    if (typeof global.getApiOrigin === "function") return global.getApiOrigin();
    if (global.location && global.location.origin) return global.location.origin.replace(/\/$/, "");
    return "http://127.0.0.1:8000";
  }

  function pluginBuiltin(pluginId, meta) {
    if (typeof global.isBuiltinPluginId === "function") {
      return global.isBuiltinPluginId(pluginId, meta);
    }
    return !!(meta && meta.builtin);
  }

  function pluginFilesUrl(pluginId, filename) {
    return getApiOrigin() + "/api/plugin-files/" + encodeURIComponent(pluginId) + "/" + filename;
  }

  function slugifyId(value) {
    return String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[\s]+/g, "_")
      .replace(/[^a-z0-9_-]/g, "")
      .replace(/_node$/, "");
  }

  function generateFieldKey(label) {
    var key = slugifyId(label).replace(/-/g, "_");
    if (key) return key;
    var used = {};
    state.fields.forEach(function (f) {
      used[f.key] = true;
    });
    var n = state.fields.length + 1;
    while (used["field_" + n]) n += 1;
    return "field_" + n;
  }

  function isValidFieldKey(key) {
    return /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(key || "");
  }

  function handlerName(blockType) {
    return "_type_handler_" + String(blockType || "").replace(/-/g, "_");
  }

  function blockTypeFromPluginId(pluginId) {
    return String(pluginId || "").replace(/-/g, "_");
  }

  function generatePluginId(name) {
    var id = slugifyId(name);
    if (id) return id;
    var n = 1;
    while (n < 10000) {
      var candidate = "plugin_" + n;
      n += 1;
      if (candidate !== "plugin") return candidate;
    }
    return "plugin_" + Date.now();
  }

  function pluginsCreateUrl() {
    if (typeof global.apiUrl === "function") return global.apiUrl("/plugins/create-custom");
    return getApiBase().replace(/\/$/, "") + "/plugins/create-custom";
  }

  function pluginDetailUrl(pluginId) {
    if (typeof global.apiUrl === "function") return global.apiUrl("/plugins/" + encodeURIComponent(pluginId));
    return getApiBase().replace(/\/$/, "") + "/plugins/" + encodeURIComponent(pluginId);
  }

  function pluginCodeUrl(pluginId) {
    if (typeof global.apiUrl === "function") return global.apiUrl("/plugins/" + encodeURIComponent(pluginId) + "/code");
    return getApiBase().replace(/\/$/, "") + "/plugins/" + encodeURIComponent(pluginId) + "/code";
  }

  function fetchText(url) {
    return fetch(url).then(function (res) {
      return res.text().then(function (text) {
        return { ok: res.ok, status: res.status, text: text };
      });
    });
  }

  function fetchPluginCode(pluginId) {
    return fetchText(pluginCodeUrl(pluginId)).then(function (result) {
      if (result.ok) return result.text;
      return fetchText(pluginFilesUrl(pluginId, "code.py.jinja2")).then(function (fallback) {
        return fallback.ok ? fallback.text : "";
      });
    });
  }

  function fetchPluginUiJson(pluginId) {
    return fetchText(pluginFilesUrl(pluginId, "ui.json")).then(function (result) {
      if (!result.ok || !result.text) return null;
      try {
        return JSON.parse(result.text);
      } catch (e) {
        return null;
      }
    });
  }

  function ensureHandlerNameInCode(code, pluginId) {
    var expected = handlerName(blockTypeFromPluginId(pluginId));
    if ((code || "").indexOf("async def " + expected) >= 0) return code;
    return String(code || "").replace(/async def _type_handler_[a-zA-Z0-9_]+/g, "async def " + expected);
  }

  function defaultTemplate(pluginId, fields) {
    var type = blockTypeFromPluginId(pluginId || "svoy_blok");
    var handler = handlerName(type);
    var firstKey = fields.length ? fields[0].key : "message";
    return [
      "# Обработчик пользовательского блока: " + type,
      "async def " + handler + "(bot, chat_id, user_id, block_id, ctx, data, disable):",
      '    text = (data.get("' + firstKey + '") or "Блок выполнен.").strip()',
      "    await bot.send_message(chat_id, text, disable_web_page_preview=disable)",
      "    next_id = get_next_block(block_id, 0)",
      "    if next_id:",
      "        await execute_block(bot, chat_id, user_id, next_id, ctx)",
    ].join("\n");
  }

  function readMeta() {
    var nameEl = state.root.querySelector("#pb-node-name");
    var idEl = state.root.querySelector("#pb-plugin-id");
    var colorEl = state.root.querySelector("#pb-node-color");
    var iconEl = state.root.querySelector("#pb-node-icon");
    var name = (nameEl && nameEl.value) || "";
    var pluginId = slugifyId((idEl && idEl.value) || "");
    if (!pluginId && name) pluginId = generatePluginId(name);
    return {
      name: name,
      plugin_id: pluginId,
      color: (colorEl && colorEl.value) || "#2563eb",
      icon: ((iconEl && iconEl.value) || "🧩").trim() || "🧩",
    };
  }

  function updatePreview() {
    var meta = readMeta();
    var badge = state.root.querySelector("#pb-preview-badge");
    var metaLine = state.root.querySelector("#pb-preview-meta");
    if (badge) {
      badge.textContent = meta.icon + " " + (meta.name || tr("plugin_builder.new_block"));
      badge.style.background = meta.color;
    }
    if (metaLine) {
      metaLine.textContent = tr("plugin_builder.preview_meta", {
        type: blockTypeFromPluginId(meta.plugin_id) || "—",
        id: meta.plugin_id || "—",
      });
    }
  }

  function renderReadOnlyFieldsList(fields) {
    var list = state.root.querySelector("#pb-fields-list");
    if (!list) return;
    list.innerHTML = "";

    if (!fields || !fields.length) {
      list.innerHTML = '<div class="pb-empty-fields">' + escapeHtml(tr("plugin_builder.no_fields_json")) + "</div>";
      return;
    }

    fields.forEach(function (field) {
      var row = document.createElement("div");
      row.className = "pb-field-row pb-field-row-readonly";
      var label = field.label || field.text || field.key || tr("plugin_builder.field_default");
      var meta = tr("plugin_builder.field_meta", { type: field.type || "—" });
      if (field.key) meta += tr("plugin_builder.field_meta_key", { key: field.key });
      row.innerHTML =
        '<div class="pb-field-row-title">' + escapeHtml(label) + "</div>" +
        '<div class="pb-readonly-meta">' + escapeHtml(meta) + "</div>" +
        (field.hint ? '<div class="pb-hint">' + escapeHtml(field.hint) + "</div>" : "") +
        (field.text ? '<div class="pb-hint">' + escapeHtml(field.text) + "</div>" : "");
      list.appendChild(row);
    });
  }

  function renderFieldRows() {
    var list = state.root.querySelector("#pb-fields-list");
    if (!list) return;
    list.innerHTML = "";

    if (!state.fields.length) {
      var empty = document.createElement("div");
      empty.className = "pb-empty-fields";
      empty.textContent = tr("plugin_builder.no_fields_added");
      list.appendChild(empty);
      updateCheatsheet();
      syncEditorTemplateIfPristine();
      return;
    }

    state.fields.forEach(function (field, index) {
      var row = document.createElement("div");
      row.className = "pb-field-row";
      row.innerHTML =
        '<div class="pb-field-row-head">' +
        '<span class="pb-field-row-title">' + escapeHtml(field.label || field.key || tr("plugin_builder.field_default")) + "</span>" +
        '<button type="button" class="pb-field-row-remove" data-index="' + index + '">' + escapeHtml(tr("common.delete")) + "</button>" +
        "</div>" +
        '<div class="pb-field-grid">' +
        fieldEditorHtml(field, index) +
        "</div>";
      list.appendChild(row);
    });

    list.querySelectorAll(".pb-field-row-remove").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var idx = parseInt(btn.getAttribute("data-index"), 10);
        state.fields.splice(idx, 1);
        renderFieldRows();
      });
    });

    list.querySelectorAll("[data-field-index]").forEach(function (input) {
      input.addEventListener("change", onFieldInputChange);
      input.addEventListener("input", onFieldInputChange);
    });

    updateCheatsheet();
    syncEditorTemplateIfPristine();
  }

  function fieldEditorHtml(field, index) {
    var optionsHtml =
      field.type === "select"
        ? '<div class="pb-field"><label>' + escapeHtml(tr("plugin_builder.select_options_label")) + '</label><textarea data-field-index="' +
          index +
          '" data-prop="optionsText" rows="3">' +
          escapeHtml(optionsToText(field.options)) +
          "</textarea></div>"
        : "";

    return (
      '<div class="pb-field"><label>' + escapeHtml(tr("plugin_builder.field_label")) + '</label><input type="text" data-field-index="' +
      index +
      '" data-prop="label" value="' +
      escapeHtml(field.label || "") +
      '" /></div>' +
      '<div class="pb-field"><label>' + escapeHtml(tr("plugin_builder.field_key")) + '</label><input type="text" data-field-index="' +
      index +
      '" data-prop="key" value="' +
      escapeHtml(field.key || "") +
      '" /></div>' +
      '<div class="pb-field"><label>' + escapeHtml(tr("plugin_builder.field_type")) + '</label><select data-field-index="' +
      index +
      '" data-prop="type">' +
      selectOptions(field.type) +
      "</select></div>" +
      optionsHtml
    );
  }

  function selectOptions(current) {
    var types = ["text", "textarea", "select", "checkbox", "number"];
    return types
      .map(function (t) {
        var label = fieldTypeLabel(t);
        return '<option value="' + t + '"' + (t === current ? " selected" : "") + ">" + label + "</option>";
      })
      .join("");
  }

  function optionsToText(options) {
    if (!Array.isArray(options) || !options.length) return tr("plugin_builder.default_options_text");
    return options
      .map(function (opt) {
        return String(opt.value || "") + "|" + String(opt.label || opt.value || "");
      })
      .join("\n");
  }

  function textToOptions(text) {
    return String(text || "")
      .split(/\r?\n/)
      .map(function (line) {
        line = line.trim();
        if (!line) return null;
        var parts = line.split("|");
        var value = (parts[0] || "").trim();
        var label = (parts[1] || value).trim();
        if (!value) return null;
        return { value: value, label: label };
      })
      .filter(Boolean);
  }

  function onFieldInputChange(event) {
    var el = event.target;
    var index = parseInt(el.getAttribute("data-field-index"), 10);
    var prop = el.getAttribute("data-prop");
    if (isNaN(index) || !prop || !state.fields[index]) return;

    if (prop === "optionsText") {
      state.fields[index].options = textToOptions(el.value);
    } else {
      state.fields[index][prop] = el.value;
    }

    if (prop === "label" || prop === "key" || prop === "type") {
      renderFieldRows();
    } else {
      updateCheatsheet();
    }
  }

  function escapeHtml(value) {
    return String(value || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function updateCheatsheet() {
    var box = state.root.querySelector("#pb-cheatsheet-content");
    if (!box) return;

    var meta = readMeta();
    var type = blockTypeFromPluginId(meta.plugin_id);
    var handler = handlerName(type);
    var fieldLines = state.fields.map(function (field) {
      return 'data.get("' + field.key + '")  ·  {{ data.' + field.key + " }}";
    });

    var html =
      "<section><h3>" + escapeHtml(tr("plugin_builder.cheatsheet.handler")) + "</h3><code>async def " +
      handler +
      "(bot, chat_id, user_id, block_id, ctx, data, disable):</code></section>" +
      "<section><h3>" + escapeHtml(tr("plugin_builder.cheatsheet.context_title")) + "</h3><ul>" +
      "<li>" + escapeHtml(tr("plugin_builder.cheatsheet.context_plugin")) + "</li>" +
      "<li>" + escapeHtml(tr("plugin_builder.cheatsheet.context_block")) + "</li>" +
      "<li>" + escapeHtml(tr("plugin_builder.cheatsheet.context_data")) + "</li>" +
      "<li>" + escapeHtml(tr("plugin_builder.cheatsheet.context_scenario")) + "</li>" +
      "</ul></section>";

    if (fieldLines.length) {
      html += "<section><h3>" + escapeHtml(tr("plugin_builder.cheatsheet.fields_title")) + "</h3><code>" + fieldLines.join("\n") + "</code></section>";
    } else {
      html += "<section><h3>" + escapeHtml(tr("plugin_builder.cheatsheet.fields_title")) + "</h3><p>" + escapeHtml(tr("plugin_builder.cheatsheet.fields_empty")) + "</p></section>";
    }

    html +=
      "<section><h3>" + escapeHtml(tr("plugin_builder.cheatsheet.helpers_title")) + "</h3><code>get_next_block(block_id, output_index)\nexecute_block(...)\nget_user_field(user_id, field)\nset_user_field(user_id, field, value)\nresolve_text(text, user_id)</code></section>";

    box.innerHTML = html;
  }

  function syncEditorTemplateIfPristine() {
    if (!state.editor || !state.editorIsPristine) return;
    var meta = readMeta();
    var template = defaultTemplate(meta.plugin_id || "svoy_blok", state.fields);
    state.editor.setValue(template);
  }

  function showStatus(message, kind) {
    if (kind === "success") {
      message = "";
      kind = "";
    }
    var bar = state.root.querySelector("#pb-status-bar");
    if (bar) {
      bar.textContent = message || "";
      bar.className = "pb-status" + (kind ? " " + kind : "");
    }
    // Toasts near toolbar buttons are disabled — status lives in #pb-status-bar only.
    var toast = state.root.querySelector("#pb-toast");
    if (toast) {
      toast.textContent = "";
      toast.className = "pb-toast";
      toast.hidden = true;
    }
  }

  function collectPayload() {
    var meta = readMeta();
    if (!meta.name.trim()) throw new Error(tr("plugin_builder.err.name_required"));

    var idEl = state.root.querySelector("#pb-plugin-id");
    if (!meta.plugin_id) {
      meta.plugin_id = generatePluginId(meta.name);
      if (idEl) idEl.value = meta.plugin_id;
    }
    if (!meta.plugin_id) throw new Error(tr("plugin_builder.err.id_required"));

    var fields = state.fields.map(function (field) {
      var item = {
        key: String(field.key || "").trim(),
        type: String(field.type || "text").trim(),
        label: String(field.label || "").trim(),
      };
      if (field.type === "select") {
        item.options =
          field.options && field.options.length
            ? field.options
            : [{ value: "variant1", label: tr("plugin_builder.default_variant") }];
      }
      return item;
    });

    for (var i = 0; i < fields.length; i++) {
      if (!fields[i].key) throw new Error(tr("plugin_builder.err.field_key_required"));
      if (!fields[i].label) throw new Error(tr("plugin_builder.err.field_label_required"));
    }

    var template_code = state.editor ? state.editor.getValue() : defaultTemplate(meta.plugin_id, fields);
    template_code = ensureHandlerNameInCode(template_code, meta.plugin_id);
    if (state.editor && state.editor.getValue() !== template_code) {
      state.editor.setValue(template_code);
    }
    if (!template_code.trim()) throw new Error(tr("plugin_builder.err.template_empty"));

    var expectedHandler = handlerName(blockTypeFromPluginId(meta.plugin_id));
    if (template_code.indexOf("async def " + expectedHandler) < 0) {
      throw new Error(
        tr("plugin_builder.err.handler_required", { handler: expectedHandler })
      );
    }

    return {
      plugin_id: meta.plugin_id,
      name: meta.name.trim(),
      color: meta.color,
      icon: meta.icon,
      fields: fields,
      template_code: template_code,
    };
  }

  function formatApiError(detail) {
    if (!detail) return null;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map(function (d) {
          if (typeof d === "string") return d;
          if (d && d.msg) return d.msg;
          return JSON.stringify(d);
        })
        .join("; ");
    }
    return String(detail);
  }

  function saveAndPublish() {
    if (state.saving) return;
    var payload;
    try {
      payload = collectPayload();
    } catch (err) {
      showStatus(err.message || String(err), "error");
      return;
    }

    state.saving = true;
    var saveBtn = state.root.querySelector("#pb-save-btn");
    if (saveBtn) {
      saveBtn.disabled = true;
      saveBtn.textContent = tr("plugin_builder.publishing");
    }
    showStatus(tr("plugin_builder.status.saving"), "");

    var saveUrl = state.existingPluginId && !state.readonly
      ? pluginDetailUrl(state.existingPluginId)
      : pluginsCreateUrl();
    var saveMethod = state.existingPluginId && !state.readonly ? "PUT" : "POST";

    fetch(saveUrl, {
      method: saveMethod,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (res) {
        return res.text().then(function (text) {
          var data = null;
          try {
            data = text ? JSON.parse(text) : null;
          } catch (parseErr) {
            data = { detail: text || tr("plugin_builder.status.server_json") };
          }
          return { ok: res.ok, status: res.status, data: data };
        });
      })
      .then(function (result) {
        state.saving = false;
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.textContent = tr("plugin_builder.save_publish");
        }
        if (!result.ok) {
          var detail = formatApiError(result.data && result.data.detail);
          if (result.status === 405) {
            detail = tr("plugin_builder.err.backend_stale");
          }
          throw new Error(detail || tr("plugin_builder.err.save", { status: result.status }));
        }

        showStatus(tr("plugin_builder.status.published", { name: result.data.name || payload.name }), "success");
        var target =
          state.returnUrl +
          (state.returnUrl.indexOf("?") >= 0 ? "&" : "?") +
          "plugin_created=" +
          encodeURIComponent(result.data.type || payload.plugin_id);
        setTimeout(function () {
          global.location.href = target;
        }, 700);
      })
      .catch(function (err) {
        state.saving = false;
        if (saveBtn) {
          saveBtn.disabled = false;
          saveBtn.textContent = tr("plugin_builder.save_publish");
        }
        showStatus(err.message || tr("plugin_builder.err.publish_failed"), "error");
      });
  }

  function bindMetaInputs() {
    ["#pb-node-name", "#pb-plugin-id", "#pb-node-color", "#pb-node-icon"].forEach(function (selector) {
      var el = state.root.querySelector(selector);
      if (!el) return;
      el.addEventListener("input", function () {
        if (selector === "#pb-node-name") {
          var idEl = state.root.querySelector("#pb-plugin-id");
          if (idEl && !idEl.dataset.manual) {
            idEl.value = generatePluginId(el.value);
          }
        }
        updatePreview();
        updateCheatsheet();
        if (selector === "#pb-plugin-id") syncEditorTemplateIfPristine();
      });
    });

    var idEl = state.root.querySelector("#pb-plugin-id");
    if (idEl) {
      idEl.addEventListener("input", function () {
        idEl.dataset.manual = "1";
      });
    }
  }

  function addFieldFromForm() {
    var labelEl = state.root.querySelector("#pb-new-field-label");
    var keyEl = state.root.querySelector("#pb-new-field-key");
    var typeEl = state.root.querySelector("#pb-new-field-type");
    if (!labelEl || !keyEl || !typeEl) return;

    var label = String(labelEl.value || "").trim();
    var key = String(keyEl.value || "").trim();
    var type = String(typeEl.value || "text").trim().toLowerCase();

    if (!label) {
      showStatus(tr("plugin_builder.err.field_label_missing"), "error");
      labelEl.focus();
      return;
    }
    if (!key) {
      key = generateFieldKey(label);
      keyEl.value = key;
    }
    if (!isValidFieldKey(key)) {
      showStatus(tr("plugin_builder.err.field_key_invalid"), "error");
      keyEl.focus();
      return;
    }
    if (state.fields.some(function (f) { return f.key === key; })) {
      showStatus(tr("plugin_builder.err.field_key_duplicate", { key: key }), "error");
      keyEl.focus();
      return;
    }
    if (["text", "textarea", "select", "checkbox", "number"].indexOf(type) < 0) type = "text";

    var field = { key: key, label: label, type: type };
    if (type === "select") {
      field.options = [{ value: "variant1", label: tr("plugin_builder.default_variant") }];
    }
    state.fields.push(field);
    labelEl.value = "";
    keyEl.value = "";
    keyEl.dataset.manual = "";
    typeEl.value = "text";
    renderFieldRows();
    showStatus(tr("plugin_builder.status.field_added", { label: label }), "success");
  }

  function bindAddFieldForm() {
    var form = state.root.querySelector("#pb-add-field-form");
    var labelEl = state.root.querySelector("#pb-new-field-label");
    var keyEl = state.root.querySelector("#pb-new-field-key");
    if (!form || !labelEl || !keyEl) return;

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      addFieldFromForm();
    });

    labelEl.addEventListener("input", function () {
      if (!keyEl.dataset.manual) {
        keyEl.value = generateFieldKey(labelEl.value);
      }
    });

    keyEl.addEventListener("input", function () {
      keyEl.dataset.manual = keyEl.value ? "1" : "";
    });
  }

  function mountLayout(root) {
    root.innerHTML =
      '<div class="pb-shell">' +
      '<header class="dashboard-header">' +
      '<a class="header-back" id="pb-back-link" href="/plugins/">←</a>' +
      '<h1 class="page-title" id="pb-page-title"></h1>' +
      "</header>" +
      '<div class="pb-toolbar">' +
      '<p id="pb-readonly-banner" class="pb-readonly-banner" hidden></p>' +
      '<div class="pb-header-actions">' +
      '<div id="pb-toast" class="pb-toast" aria-live="polite"></div>' +
      '<button type="button" class="pb-btn pb-btn-danger" id="pb-delete-btn" hidden></button>' +
      '<button type="button" class="pb-btn" id="pb-reset-template"></button>' +
      '<button type="button" class="pb-btn pb-btn-primary" id="pb-save-btn"></button>' +
      "</div></div>" +
      '<main class="pb-main">' +
      '<section class="pb-zone" id="pb-zone-a">' +
      '<div class="pb-zone-head"><h2></h2><p></p></div>' +
      '<div class="pb-zone-body">' +
      '<div class="pb-field"><label for="pb-node-name"></label><input id="pb-node-name" type="text" value="' +
      escapeHtml(tr("plugin_builder.default_block")) +
      '" /><div class="pb-hint"></div></div>' +
      '<div class="pb-field"><label for="pb-plugin-id"></label><input id="pb-plugin-id" type="text" value="svoy_blok" /><div class="pb-hint"></div></div>' +
      '<div class="pb-field"><label for="pb-node-icon"></label><input id="pb-node-icon" type="text" maxlength="4" value="🧩" /></div>' +
      '<div class="pb-field"><label for="pb-node-color"></label><input id="pb-node-color" type="color" value="#2563eb" /></div>' +
      '<div class="pb-preview-card"><div id="pb-preview-badge" class="pb-preview-badge"></div><div id="pb-preview-meta" class="pb-preview-meta"></div></div>' +
      "</div></section>" +
      '<section class="pb-zone" id="pb-zone-b">' +
      '<div class="pb-zone-head"><h2></h2><p></p></div>' +
      '<div class="pb-zone-body">' +
      '<form id="pb-add-field-form" class="pb-add-field-form">' +
      '<p class="pb-form-intro"></p>' +
      '<div class="pb-field"><label for="pb-new-field-label"></label><input id="pb-new-field-label" type="text" autocomplete="off" /><div class="pb-hint"></div></div>' +
      '<div class="pb-field"><label for="pb-new-field-key"></label><input id="pb-new-field-key" type="text" autocomplete="off" /><div class="pb-hint"></div></div>' +
      '<div class="pb-field"><label for="pb-new-field-type"></label><select id="pb-new-field-type"></select></div>' +
      '<button type="submit" class="pb-btn pb-btn-primary pb-add-field-submit"></button>' +
      "</form>" +
      '<div class="pb-fields-list" id="pb-fields-list"></div>' +
      "</div></section>" +
      '<section class="pb-zone" id="pb-zone-c">' +
      '<div class="pb-zone-head"><h2></h2><p></p></div>' +
      '<div class="pb-code-layout">' +
      '<div class="pb-editor-wrap"><div id="pb-monaco-editor" class="pb-editor"></div></div>' +
      '<aside class="pb-cheatsheet"><div id="pb-cheatsheet-content"></div></aside>' +
      "</div></section>" +
      "</main>" +
      '<div id="pb-status-bar" class="pb-status"></div>' +
      "</div>";

    var params = new URLSearchParams(global.location.search || "");
    if (params.get("edit") || params.get("view")) {
      state.returnUrl = "/plugins/";
    } else {
      state.returnUrl = params.get("return") || "/dashboard/index.html";
    }

    var back = root.querySelector("#pb-back-link");
    if (back) {
      back.setAttribute("href", state.returnUrl);
    }

    root.querySelector("#pb-save-btn").addEventListener("click", saveAndPublish);
    var deleteBtn = root.querySelector("#pb-delete-btn");
    if (deleteBtn) deleteBtn.addEventListener("click", deleteExistingPlugin);
    bindAddFieldForm();
    root.querySelector("#pb-reset-template").addEventListener("click", function () {
      if (!state.editor) return;
      var meta = readMeta();
      state.editor.setValue(defaultTemplate(meta.plugin_id || "svoy_blok", state.fields));
      state.editorIsPristine = true;
      showStatus(tr("plugin_builder.status.template_reset"), "");
    });

    bindMetaInputs();
    applyStaticTranslations();
    renderFieldRows();
    updatePreview();
  }

  function checkPluginBuilderApi() {
    fetch(pluginsCreateUrl(), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: "{}",
    })
      .then(function (res) {
        if (res.status === 405) {
          showStatus(tr("plugin_builder.err.backend_stale"), "error");
        }
      })
      .catch(function () {});
  }

  function initMonaco() {
    var host = state.root.querySelector("#pb-monaco-editor");
    if (!host || !global.require) {
      showStatus(tr("plugin_builder.err.monaco_unavailable"), "error");
      return;
    }

    global.require.config({
      paths: {
        vs: "https://cdn.jsdelivr.net/npm/monaco-editor@0.45.0/min/vs",
      },
    });

    global.require(["vs/editor/editor.main"], function () {
      var meta = readMeta();
      var initial = defaultTemplate(meta.plugin_id || "svoy_blok", state.fields);
      var monacoTheme =
        typeof global.AppTheme !== "undefined" && global.AppTheme.get() === "light"
          ? "vs"
          : "vs-dark";
      state.editor = global.monaco.editor.create(host, {
        value: initial,
        language: "python",
        theme: monacoTheme,
        automaticLayout: true,
        minimap: { enabled: false },
        fontSize: 13,
        scrollBeyondLastLine: false,
        wordWrap: "on",
        readOnly: state.readonly,
      });
      state.editorIsPristine = true;
      state.monacoReady = true;
      state.editor.onDidChangeModelContent(function () {
        state.editorIsPristine = false;
      });
      if (!state._themeListenerBound) {
        state._themeListenerBound = true;
        global.document.addEventListener("appthemechange", function (ev) {
          if (!state.editor || !global.monaco) return;
          var t = ev && ev.detail && ev.detail.theme === "light" ? "vs" : "vs-dark";
          global.monaco.editor.setTheme(t);
        });
      }
      updateCheatsheet();
      if (state.pendingPluginData) {
        applyLoadedPlugin(state.pendingPluginData);
        state.pendingPluginData = null;
      }
    });
  }

  function applyReadOnlyUi() {
    if (!state.readonly) return;
    var banner = state.root.querySelector("#pb-readonly-banner");
    if (banner) banner.hidden = false;

    state.root.querySelectorAll("input, select, textarea, button.pb-add-field-submit").forEach(function (el) {
      if (el.id === "pb-back-link") return;
      el.disabled = true;
    });
    var saveBtn = state.root.querySelector("#pb-save-btn");
    var resetBtn = state.root.querySelector("#pb-reset-template");
    var deleteBtn = state.root.querySelector("#pb-delete-btn");
    var addForm = state.root.querySelector("#pb-add-field-form");
    if (saveBtn) saveBtn.hidden = true;
    if (resetBtn) resetBtn.hidden = true;
    if (deleteBtn) deleteBtn.hidden = true;
    if (addForm) addForm.hidden = true;
    if (state.editor && state.editor.updateOptions) {
      state.editor.updateOptions({ readOnly: true });
    }
  }

  function loadPluginFallback(pluginId) {
    var listUrl = getApiBase().replace(/\/$/, "") + "/plugins";
    return fetch(listUrl)
      .then(function (r) {
        return r.ok ? r.json() : { plugins: [] };
      })
      .then(function (data) {
        var meta = null;
        if (typeof global.findPluginInList === "function") {
          meta = global.findPluginInList(data.plugins, pluginId);
        } else {
          meta = (data.plugins || []).find(function (p) {
            return (p.pluginId || p.id || p.type) === pluginId;
          });
        }
        return Promise.all([Promise.resolve(meta), fetchPluginUiJson(pluginId), fetchPluginCode(pluginId)]).then(
          function (parts) {
            var listMeta = parts[0];
            var uiJson = parts[1];
            var code = parts[2];
            var ui = uiJson || listMeta || {};
            if (!listMeta && !uiJson) {
              throw new Error(tr("plugin_builder.err.plugin_not_found", { id: pluginId }));
            }
            var builtin = pluginBuiltin(pluginId, ui);
            return {
              pluginId: pluginId,
              type: ui.type || listMeta && listMeta.type || pluginId,
              name: ui.name || (listMeta && listMeta.name) || pluginId,
              color: ui.color || (listMeta && listMeta.color),
              icon: ui.icon || (listMeta && listMeta.icon),
              ui: uiJson || ui,
              fields: (uiJson && uiJson.fields) || (listMeta && listMeta.fields) || ui.fields || [],
              defaults: (uiJson && uiJson.defaults) || (listMeta && listMeta.defaults) || ui.defaults || {},
              template_code: code,
              builtin: builtin,
              editable: !builtin,
            };
          }
        );
      });
  }

  function loadPluginWithFallback(pluginId) {
    return fetch(pluginDetailUrl(pluginId))
      .then(function (res) {
        return res.text().then(function (text) {
          var data = null;
          try {
            data = text ? JSON.parse(text) : null;
          } catch (e) {
            data = null;
          }
          return { ok: res.ok, status: res.status, data: data };
        });
      })
      .then(function (result) {
        if (result.ok && result.data && result.data.pluginId) {
          if (!result.data.template_code) {
            return fetchPluginCode(pluginId).then(function (code) {
              result.data.template_code = code;
              return result.data;
            });
          }
          return result.data;
        }
        return loadPluginFallback(pluginId);
      });
  }

  function applyLoadedPlugin(data) {
    state.isBuiltin = pluginBuiltin(data.pluginId, data);
    state.readonly = state.isBuiltin || !!data.readonly || data.editable === false;

    var nameEl = state.root.querySelector("#pb-node-name");
    var idEl = state.root.querySelector("#pb-plugin-id");
    var colorEl = state.root.querySelector("#pb-node-color");
    var iconEl = state.root.querySelector("#pb-node-icon");
    var ui = data.ui || {};

    if (nameEl) nameEl.value = data.name || ui.name || data.pluginId || "";
    if (idEl) {
      idEl.value = data.pluginId || "";
      idEl.dataset.manual = "1";
      idEl.disabled = true;
    }
    if (colorEl) colorEl.value = ui.color || data.color || "#2563eb";
    if (iconEl) iconEl.value = ui.icon || data.icon || "🧩";

    var allFields = data.fields || ui.fields || [];
    if (state.readonly) {
      renderReadOnlyFieldsList(allFields);
    } else {
      state.fields = allFields
        .filter(function (f) {
          return f && f.key && ALLOWED_FIELD_TYPES.indexOf(f.type) >= 0;
        })
        .map(function (f) {
          return {
            key: f.key,
            label: f.label || f.key,
            type: f.type,
            options: f.options,
          };
        });
      renderFieldRows();
    }

    var title = state.root.querySelector("#pb-page-title");
    if (title) title.textContent = getPageTitleText();

    var deleteBtn = state.root.querySelector("#pb-delete-btn");
    if (deleteBtn) deleteBtn.hidden = state.readonly;

    updatePreview();
    updateCheatsheet();

    if (state.editor) {
      state.editor.setValue(data.template_code || "");
      state.editorIsPristine = true;
      if (state.readonly && state.editor.updateOptions) {
        state.editor.updateOptions({ readOnly: true });
      }
      if (!data.template_code && state.isBuiltin) {
        showStatus(tr("plugin_builder.err.template_not_loaded"), "error");
      } else {
        showStatus("", "");
      }
    } else if (state.monacoReady === false && (global.location.search || "").match(/[?&](edit|view)=/)) {
      state.pendingPluginData = data;
    }

    applyReadOnlyUi();
  }

  function maybeLoadExistingPlugin() {
    var params = new URLSearchParams(global.location.search || "");
    var editId = params.get("edit");
    var viewId = params.get("view");
    var pluginId = editId || viewId;
    if (!pluginId) return;

    state.existingPluginId = pluginId;
    state.readonly = !!viewId;
    if (editId && !viewId && !pluginBuiltin(pluginId, null)) {
      state.readonly = false;
    }

    loadPluginWithFallback(pluginId)
      .then(function (data) {
        if (pluginBuiltin(pluginId, data)) {
          state.readonly = true;
        } else if (editId && !viewId) {
          state.readonly = false;
        }
        applyLoadedPlugin(data);
      })
      .catch(function (err) {
        var msg = err && err.message ? err.message : tr("plugin_builder.err.load_failed");
        if (msg === "Not Found") {
          msg = tr("plugin_builder.err.plugin_not_found_restart");
        }
        showStatus(msg, "error");
      });
  }

  function startExistingPluginLoadIfNeeded() {
    var params = new URLSearchParams(global.location.search || "");
    if (params.get("edit") || params.get("view")) {
      maybeLoadExistingPlugin();
    }
  }

  function deleteExistingPlugin() {
    if (!state.existingPluginId || state.readonly) return;
    if (!confirm(tr("plugin_builder.delete_confirm", { id: state.existingPluginId }))) return;

    fetch(pluginDetailUrl(state.existingPluginId), { method: "DELETE" })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          throw new Error((result.data && result.data.detail) || tr("plugin_builder.err.delete_failed"));
        }
        global.location.href = "/plugins/?deleted=" + encodeURIComponent(state.existingPluginId);
      })
      .catch(function (err) {
        showStatus(err.message || tr("plugin_builder.err.delete"), "error");
      });
  }

  function init(options) {
    options = options || {};
    state.root = options.root || document.getElementById("plugin-builder-root");
    if (!state.root) return;
    var params = new URLSearchParams(global.location.search || "");
    if (params.get("edit") || params.get("view")) {
      state.returnUrl = "/plugins/";
    } else {
      state.returnUrl = params.get("return") || "/dashboard/index.html";
    }
    mountLayout(state.root);
    checkPluginBuilderApi();
    startExistingPluginLoadIfNeeded();
    initMonaco();
    if (!state._langBound) {
      state._langBound = true;
      document.addEventListener("botbuilder:langchange", function () {
        applyStaticTranslations();
      });
    }
  }

  global.PluginBuilderView = {
    init: init,
    defaultTemplate: defaultTemplate,
    slugifyId: slugifyId,
  };
})(typeof window !== "undefined" ? window : globalThis);
