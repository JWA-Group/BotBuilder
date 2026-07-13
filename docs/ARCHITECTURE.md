# BotBuilder Architecture Specification

This document describes the system architecture of BotBuilder for senior engineers and technical reviewers evaluating the codebase.

---

## 1. High-Level System Architecture

BotBuilder follows a **desktop shell + local API sidecar** pattern. The Electron main process owns process lifecycle, window management, and OS integration. The renderer is a static SPA served by FastAPI. Inter-process communication between the UI and business logic uses HTTP over the loopback interface, not direct Node-to-Python bindings.

### 1.1 Process Topology

```
+---------------------------+       spawn / supervise        +---------------------------+
|   Electron Main Process   | --------------------------->   |   FastAPI Sidecar         |
|   (main.js)               |       health / shutdown      |   (botbuilder-backend)    |
+---------------------------+                                +---------------------------+
          |                                                              |
          | BrowserWindow + preload.js                                   | StaticFiles
          v                                                              v
+---------------------------+       HTTP 127.0.0.1:{port}/api     +---------------------------+
|   Electron Renderer       | <----------------------------->   |   REST + SPA Router       |
|   (frontend SPA)          |       fetch / JSON payloads       |   (backend/main.py)       |
+---------------------------+                                   +---------------------------+
```

### 1.2 Responsibility Boundaries

| Layer | Responsibilities |
|-------|------------------|
| **Electron Main** | Sidecar spawn, port selection, settings persistence, multi-window orchestration, native dialogs, graceful shutdown, first-run setup, uninstall-safe userData path (`%AppData%\botbuilder-desktop`). |
| **Preload Bridge** | Exposes `electronAPI` via `contextBridge`: API origin, port, undo depth, language, settings invocation. Subscribes to `app:lang-changed` IPC for cross-window locale sync. |
| **FastAPI Sidecar** | Authentication, bot CRUD, scenario persistence, plugin registry, template catalog, compilation, bot process management, SQLite access. |
| **Renderer SPA** | Scenario canvas, property editors, analytics dashboards, deployment UI. Stateless with respect to filesystem; all mutations go through REST. |

### 1.3 IPC Bridge Semantics

The bridge is **asynchronous and HTTP-based**:

1. Main process starts the sidecar with environment variables `BOTBUILDER_APP_ROOT` and `BOTBUILDER_DATA_DIR`.
2. Main polls `GET /api/health` until the server reports ready (90 s timeout).
3. Renderer receives `--api-port={port}` via Chromium `additionalArguments` and constructs `http://127.0.0.1:{port}/api` as the API base.
4. On application exit, main sends `POST /api/shutdown` before terminating the sidecar child process.

Port conflicts trigger a settings dialog loop: the user selects an alternate port, settings are persisted, and the sidecar is respawned.

### 1.4 Packaged Layout

In production builds (electron-builder + NSIS):

| Path | Contents |
|------|----------|
| `resources/app.asar` | Electron main, preload scripts, electron shell HTML |
| `resources/app/frontend/` | SPA static assets (extraResources) |
| `resources/app/plugins/` | Bundled block plugin definitions |
| `resources/app/python_embed/` | Embedded CPython for bot execution |
| `resources/botbuilder-backend/` | PyInstaller-compiled FastAPI binary |

This separation keeps the ASAR archive read-only while allowing hot-path assets and the backend to live outside it.

---

## 2. Embedded Python Runtime Execution Engine

BotBuilder ships a **self-contained Python distribution** (`python_embed/`) so end-user machines do not require a system Python installation.

### 2.1 Path Isolation Model

Environment variables define a strict read/write split:

| Variable | Production Value | Purpose |
|----------|------------------|---------|
| `BOTBUILDER_APP_ROOT` | `{install}/resources/app` | Read-only: frontend, bundled plugins, catalog templates, `python_embed` |
| `BOTBUILDER_DATA_DIR` | `%AppData%\botbuilder-desktop\data` | Writable: projects, user plugins, SQLite DB, local templates, logs |

The Electron main process sets `userData` to `%AppData%\botbuilder-desktop` before `app.ready`. Settings (`settings.json`) live at the userData root; operational data lives under `data/`.

Implementation reference: `backend/core/app_paths.py`, `main.js` (`getAppRoot`, `getDataDir`, `ensureUserDataDirs`).

### 2.2 Directory Layout Under DATA_DIR

```
%AppData%\botbuilder-desktop\
  settings.json
  data\
    projects\          bot_{id}\main.py, scenario.json
    plugins\           user-authored block definitions
    databases\         db.sqlite3
    templates\local\   exported .bbpack files
    logs\
```

### 2.3 Sidecar vs Bot Runtime

Two distinct Python execution contexts exist:

| Context | Binary | Role |
|---------|--------|------|
| **API Sidecar** | `resources/botbuilder-backend/botbuilder-backend.exe` | PyInstaller-frozen FastAPI server; serves API and compiles scenarios |
| **Bot Worker** | `resources/app/python_embed/python.exe` | Runs generated `main.py` for each bot with aiogram and project dependencies |

`core/runner.py` resolves the embedded interpreter through a candidate chain (`python_embed/python.exe` under `BOTBUILDER_APP_ROOT`). In desktop mode it refuses to fall back to system Python, preventing silent dependency failures.

### 2.4 Bot Lifecycle

1. User saves a scenario graph (JSON).
2. Compiler (`backend/core/compiler.py`) traverses the graph, renders per-block Jinja2 templates from the plugin registry, and writes `projects/bot_{id}/main.py`.
3. `BotRunner` spawns `python_embed/python.exe main.py` as a subprocess with `cwd` set to the bot directory.
4. Monitor endpoints report process state; stop requests terminate the subprocess tree.

### 2.5 Reinstall Safety

On packaged startup, the main process retires stale sidecar instances bound to the configured port and respawns a fresh backend binary. This prevents orphaned processes from a previous installation session from serving outdated code after an upgrade.

---

## 3. Asynchronous Plugin Subsystem

The plugin subsystem provides **runtime-discovered, filesystem-backed block extensions** without rebuilding the Electron shell.

### 3.1 Discovery Model

`PluginManager` (`backend/core/plugin_manager.py`) scans ordered directories:

1. `%AppData%/.../data/plugins/` (user; takes precedence)
2. `{APP_ROOT}/plugins/` (bundled)

Each plugin folder must contain:

| File | Purpose |
|------|---------|
| `ui.json` | Block metadata: type, name, icon, color, fields, defaults |
| `code.py.jinja2` | Jinja2 template rendered into the compiled bot script |

Discovery is lazy: `_plugins` and `_by_type` caches are populated on first `list_plugins()` call. `reload()` invalidates the Jinja environment and rescans disk.

### 3.2 Dynamic Loading and importlib Alignment

Block plugins are not compiled into the backend binary. Instead, the subsystem mirrors **importlib-style dynamic module semantics**:

- **Enumeration** — `Path.iterdir()` walks plugin roots at runtime; no static registry in source code.
- **Late binding** — `BlockPlugin.render_code()` resolves templates through a `ChoiceLoader` spanning all plugin directories only when compilation requests a block type.
- **Override resolution** — User plugins with the same `type` field replace bundled definitions because user directories are scanned first.
- **Fault isolation** — Malformed `ui.json` files are skipped per-folder (`try/except` on parse); a single corrupt plugin does not prevent others from loading.

For bot execution, generated `main.py` files use standard Python `import` statements (aiogram, asyncio). Each bot runs in an **isolated subprocess**, providing process-level error containment distinct from the API sidecar.

### 3.3 Lifecycle Management

| Stage | Mechanism |
|-------|-----------|
| **Create** | `POST /api/plugins` writes `ui.json` + `code.py.jinja2` to `USER_PLUGINS_DIR` |
| **Update** | `PUT /api/plugins/{id}` for user plugins; builtins are read-only |
| **Delete** | `DELETE /api/plugins/{id}` removes the folder; `PluginManager.reload()` refreshes cache |
| **Catalog sync** | `GET /api/plugins` returns merged registry to the scenario editor toolbar |

The Plugin Builder frontend generates starter templates validated server-side (`backend/core/plugins.py`: field schema, reserved IDs, template syntax checks).

### 3.4 Compilation Integration

During scenario compilation, the compiler resolves each block's `type` to a `BlockPlugin`, calls `render_code()` with block data and scenario context, and concatenates the output into the bot's `main.py`. Executable types are tracked in `get_executable_types()` to distinguish flow-control blocks from annotation nodes.

---

## 4. Frontend State and DOM Performance

The scenario editor (`frontend/editor/scenario/`) manipulates a large DOM subtree (blocks, ports, SVG edges) during pan, zoom, and drag operations. Performance strategy centers on **minimizing layout recalculation** and **coalescing paint work**.

### 4.1 Transform-Based Viewport

`CanvasView.js` applies pan and zoom via CSS `transform: translate() scale()` on the graph stage element. Pointer handlers update transform values directly without triggering reflow of individual block positions during viewport navigation.

Wheel zoom recalculates pan offset relative to the cursor pivot, keeping the focal point stable. `requestAnimationFrame` defers initial `fitToView` until after the stage is attached to the DOM.

### 4.2 Connection Redraw Coalescing

`main.js` maintains a `_drawConnectionsRaf` guard:

```javascript
if (_drawConnectionsRaf) return;
_drawConnectionsRaf = window.requestAnimationFrame(function () {
  _drawConnectionsRaf = 0;
  drawConnections();
});
```

Multiple block-move events within a single frame produce one SVG path update, preventing O(n) redraw storms during drag.

### 4.3 Drag-and-Drop Optimization

Block and button drag operations use these patterns:

- **Pointer capture semantics** — `mousedown` / `mousemove` / `mouseup` on `document` for canvas pan; drag state flags prevent spurious handlers.
- **Class-based visual feedback** — `.dragging`, `.drag-over`, `.cv-graph-viewport-dragging` toggle CSS states instead of inline style mutation on every mousemove.
- **Passive listener control** — Wheel handlers use `{ passive: false }` only where `preventDefault` is required for zoom; toolbar scroll uses RAF-batched `tickToolbarScroll` to decouple scroll position reads from writes.

### 4.4 Layout Thrashing Prevention

| Technique | Application |
|-----------|-------------|
| **Read/write separation** | Geometry reads (`getBoundingClientRect`, `clientWidth`) occur in dedicated layout passes; transform writes happen in subsequent frames. |
| **RAF scheduling** | Toolbar scroll sync, connection drawing, and graph fit operations are scheduled through `requestAnimationFrame` with cancellation on teardown. |
| **Targeted invalidation** | Selecting a block updates sidebar content only; the full canvas is not re-rendered on property edits. |
| **SVG edge layer** | Connections live in a separate `<svg>` overlay decoupled from block DOM reflows. |

### 4.5 State Management

Editor state (blocks array, connections, selection, undo stack) resides in `main.js` module scope. Persistence is explicit via save API calls rather than continuous auto-sync, reducing backend load during interactive editing. Undo depth is injected from main process settings (`--undo-steps`).

### 4.6 Internationalization Performance

`i18n.js` applies translations through `data-i18n` / `data-i18n-html` attribute scans. Language changes dispatch a `botbuilder:langchange` event; views subscribe and re-render text nodes without full page reload. Cross-window sync uses Electron IPC (`app:lang-changed`) to avoid stale locale state in secondary windows.

---

## Appendix: Key Source Locations

| Concern | Path |
|---------|------|
| Electron main / sidecar lifecycle | `main.js` |
| Preload API bridge | `preload.js` |
| Path resolution | `backend/core/app_paths.py` |
| Plugin discovery | `backend/core/plugin_manager.py` |
| Scenario compiler | `backend/core/compiler.py` |
| Bot subprocess runner | `core/runner.py` |
| Scenario canvas | `frontend/editor/scenario/main.js`, `CanvasView.js` |
| Build pipeline | `package.json`, `scripts/build-prod.js` |

---

## Related Documentation

- [README.md](../README.md) — Project overview
- [USER_GUIDE.md](USER_GUIDE.md) — End-user installation and operation guide
