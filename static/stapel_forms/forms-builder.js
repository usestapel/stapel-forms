/* Admin form builder for stapel-forms.
 *
 * What this file is NOT: a field-config editor. Per-kind config (minLength,
 * options, step, allowCustom, …) is rendered by stapel-attributes' shipped
 * `mountConfigEditor`, read off the hidden ConfigEditorWidget this page
 * renders alongside the builder. That is the whole reuse argument: the
 * eleven config widget kinds, their quirks and their translations live in
 * one place upstream, and a kind added there reaches this builder with no
 * release of stapel-forms.
 *
 * What this file IS: the list around those editors — add, remove, reorder,
 * slug, label, required — plus the schema meta, and one POST that publishes
 * the result as a new version of the SAME form.
 */
(function () {
  "use strict";

  var dataEl = document.getElementById("stapel-forms-builder-data");
  var mount = document.getElementById("stapel-forms-builder-mount");
  if (!dataEl || !mount) return;

  var payload = JSON.parse(dataEl.textContent);
  var schema = payload.schema || { fields: [], meta: {} };
  if (!Array.isArray(schema.fields)) schema.fields = [];
  if (!schema.meta || typeof schema.meta !== "object") schema.meta = {};

  // The attributes widget publishes its declarations, locale and message
  // catalogues into its own json_script block. Read them rather than
  // shipping a second copy that drifts.
  var attrData = null;
  var probe = document.getElementById("id___stapel_forms_probe-data");
  if (probe) {
    try {
      attrData = JSON.parse(probe.textContent);
    } catch (err) {
      attrData = null;
    }
  }
  var declarations = (attrData && attrData.declarations) || {};
  var messages = (attrData && attrData.messages) || {};
  var locale = (attrData && attrData.locale) || "en";

  var allowed = payload.allowedKinds || [];
  function slugify(text) {
    return String(text || "")
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 48);
  }

  function el(tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (key) {
      if (key === "style") node.setAttribute("style", attrs[key]);
      else if (key.slice(0, 2) === "on") node.addEventListener(key.slice(2), attrs[key]);
      else if (key === "text") node.textContent = attrs[key];
      else node.setAttribute(key, attrs[key]);
    });
    (children || []).forEach(function (child) {
      if (child) node.appendChild(child);
    });
    return node;
  }

  function uniqueSlug(base, index) {
    var slug = base || "field";
    var taken = {};
    schema.fields.forEach(function (f, i) {
      if (i !== index) taken[f.slug] = true;
    });
    var candidate = slug;
    var n = 2;
    while (taken[candidate]) candidate = slug + "_" + n++;
    return candidate;
  }

  function render() {
    mount.textContent = "";

    // ── schema meta ────────────────────────────────────────────────
    var meta = el("fieldset", { class: "module aligned", style: "padding:12px;margin-bottom:16px" }, [
      el("h3", { text: "Form text", style: "margin-top:0" }),
    ]);
    [
      ["title", "Title"],
      ["description", "Description"],
      ["submit_label", "Submit button"],
      ["confirmation_text", "Thank-you text"],
    ].forEach(function (pair) {
      var input = el("input", {
        type: "text",
        value: schema.meta[pair[0]] || "",
        style: "width:100%;max-width:520px",
        oninput: function (e) {
          schema.meta[pair[0]] = e.target.value;
        },
      });
      meta.appendChild(
        el("div", { style: "margin-bottom:8px" }, [
          el("label", { text: pair[1], style: "display:block;font-size:11px;text-transform:uppercase;color:#666" }),
          input,
        ])
      );
    });
    mount.appendChild(meta);

    // ── the field list ─────────────────────────────────────────────
    schema.fields.forEach(function (field, index) {
      mount.appendChild(renderField(field, index));
    });

    // ── add ────────────────────────────────────────────────────────
    var adder = el("div", { style: "margin:16px 0;padding:12px;border:1px dashed #bbb;border-radius:4px" }, [
      el("strong", { text: "Add a question: " }),
    ]);
    allowed.forEach(function (kind) {
      adder.appendChild(
        el("button", {
          type: "button",
          class: "button",
          text: kind,
          style: "margin:2px 4px",
          onclick: function () {
            if (schema.fields.length >= payload.maxFields) {
              window.alert("This form already has the maximum of " + payload.maxFields + " fields.");
              return;
            }
            schema.fields.push({
              slug: uniqueSlug(slugify(kind), -1),
              name: kind,
              mandatory: false,
              config: { type: kind },
            });
            render();
          },
        })
      );
    });
    mount.appendChild(adder);

    // ── publish ────────────────────────────────────────────────────
    var note = el("p", {
      class: "help",
      text:
        "Publishing creates version " +
        ((payload.activeVersion || 0) + 1) +
        " of this same form. The public link does not change and old responses stay readable.",
    });
    var publish = el("button", {
      type: "button",
      class: "default",
      text: "Publish these questions",
      onclick: submit,
    });
    mount.appendChild(el("div", { style: "margin-top:16px" }, [note, publish]));
  }

  function renderField(field, index) {
    var box = el("div", {
      style:
        "border:1px solid #ddd;border-radius:4px;padding:12px;margin-bottom:10px;background:#fff",
    });

    var head = el("div", { style: "display:flex;gap:8px;align-items:center;flex-wrap:wrap" });
    head.appendChild(el("span", { text: "#" + (index + 1), style: "color:#999;font-weight:600" }));

    head.appendChild(
      el("input", {
        type: "text",
        value: field.name || "",
        placeholder: "Question label",
        style: "flex:1;min-width:200px",
        oninput: function (e) {
          field.name = e.target.value;
        },
      })
    );

    head.appendChild(
      el("input", {
        type: "text",
        value: field.slug || "",
        placeholder: "slug",
        style: "width:150px;font-family:monospace",
        title:
          "The storage key. Changing it on a published question starts a NEW column — old answers stay under the old key.",
        oninput: function (e) {
          field._slugTouched = true;
          field.slug = e.target.value;
        },
      })
    );

    if ((field.config || {}).type !== "header") {
      var req = el("input", {
        type: "checkbox",
        onchange: function (e) {
          field.mandatory = e.target.checked;
        },
      });
      req.checked = !!field.mandatory;
      head.appendChild(el("label", { style: "white-space:nowrap" }, [req, document.createTextNode(" required")]));
    }

    head.appendChild(el("span", { text: (field.config || {}).type || "?", style: "color:#666;font-family:monospace" }));

    ["↑", "↓", "✕"].forEach(function (glyph, which) {
      head.appendChild(
        el("button", {
          type: "button",
          class: "button",
          text: glyph,
          style: "padding:2px 8px",
          onclick: function () {
            if (which === 2) schema.fields.splice(index, 1);
            else {
              var to = index + (which === 0 ? -1 : 1);
              if (to < 0 || to >= schema.fields.length) return;
              var moved = schema.fields.splice(index, 1)[0];
              schema.fields.splice(to, 0, moved);
            }
            render();
          },
        })
      );
    });

    box.appendChild(head);

    // Per-kind config — rendered by the upstream editor, not by this file.
    var configHost = el("div", { style: "margin-top:10px" });
    box.appendChild(configHost);
    mountConfig(configHost, field);

    return box;
  }

  // Set once the stapel-attributes bundle fails to load, so the page SAYS
  // the config editors are missing instead of just drawing fewer controls.
  // Silent degradation is the exact failure this release argues against:
  // the builder would look complete while a `select` had nowhere to type
  // its options. `stapel_forms.W004` is the server-side half of this.
  var configEditorUnavailable = false;

  function reportConfigEditorUnavailable() {
    if (configEditorUnavailable) return;
    configEditorUnavailable = true;
    var note = el("p", {
      class: "errornote",
      text:
        "The field-type settings editor could not be loaded, so per-field " +
        "options (choices, min/max, length limits) cannot be edited here. " +
        "Everything else on this page works. This is a deployment issue: " +
        "the stapel-attributes admin bundle is not being served — see the " +
        "stapel_forms.W004 system check.",
    });
    mount.insertBefore(note, mount.firstChild);
  }

  function mountConfig(host, field) {
    var kind = (field.config || {}).type;
    var declaration = declarations[kind];
    if (!declaration || !(declaration.fields || []).length) {
      return; // A kind with no config form (e.g. convertible_unit).
    }
    import(payload.attributesBundle)
      .then(function (mod) {
        if (!mod || !mod.mountConfigEditor) {
          reportConfigEditorUnavailable();
          return;
        }
        mod.mountConfigEditor(host, {
          declaration: declaration,
          slug: kind,
          config: field.config,
          locale: locale,
          messages: messages,
          prefixName: "",
          translateMode: "all",
          onChange: function (cfg) {
            // Keep `type`: the editor edits the params of a kind, it does
            // not own which kind this is.
            cfg.type = kind;
            field.config = cfg;
          },
        });
      })
      .catch(function () {
        // The rest of the builder still works — but say so, do not just
        // render fewer controls and let an author conclude the product
        // has no options editor.
        reportConfigEditorUnavailable();
      });
  }

  function submit() {
    var clean = {
      fields: schema.fields.map(function (f) {
        return {
          slug: f.slug,
          name: f.name,
          mandatory: !!f.mandatory,
          config: f.config || {},
        };
      }),
      meta: schema.meta,
    };
    var form = el("form", { method: "post", action: payload.publishUrl });
    form.appendChild(el("input", { type: "hidden", name: "schema", value: JSON.stringify(clean) }));
    var token = document.querySelector("[name=csrfmiddlewaretoken]");
    if (token) {
      form.appendChild(el("input", { type: "hidden", name: "csrfmiddlewaretoken", value: token.value }));
    }
    document.body.appendChild(form);
    form.submit();
  }

  render();
})();
