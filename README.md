![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?logo=python)
![aiogram](https://img.shields.io/badge/aiogram-v3.4+-blue?logo=telegram)
![Electron](https://img.shields.io/badge/Electron-33-47848F?logo=electron)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688?logo=fastapi)
![License](https://img.shields.io/badge/license-Elastic%20v2-orange)
# BotBuilder

| Field | Value |
|-------|-------|
| License | Elastic License v2 |
| Operating System | Windows 10 / 11 (x64) |
| Core Stack | Electron 33, FastAPI, Python 3 (embedded), SQLite |
| Active Channel | Telegram |

Desktop IDE for designing, compiling, and deploying Telegram chat bots from visual node-based scenarios. Build complex, local-first automations without subscription fees.

[![Download Windows](https://img.shields.io/badge/Download-Latest%20Release%20(Windows%20x64)-brightgreen?style=for-the-badge&logo=windows)](https://github.com/JWA-Group/BotBuilder/releases/latest)

---

## Why BotBuilder for Freelancers & Developers?

- **No Vendor Lock-in (Clean Code Generator):** Visual workflows are compiled directly into clean, human-readable **aiogram 3.x** Python code. Modify the generated `main.py` manually or hand it over to your clients without binding them to a proprietary SaaS platform.
- **100% Privacy & Local-First:** Your scenarios, bot tokens, databases, and client data stay securely on your machine (`%AppData%`). Zero cloud telemetry, no third-party servers.
- **All-in-One Telegram SMM Suite:** Stop paying for multiple services. BotBuilder includes a Scenario Editor, Channel Moderation Hub, Post Studio with live preview, and Audience Broadcast tools in one standalone app.
- **One-Click Hand-off & Deploy:** Export finished projects as ready-to-run Docker bundles or deploy directly to your or your client's VPS via SSH.

---

## Technical Overview

BotBuilder is a hybrid desktop application: an Electron shell hosts the user interface while a local FastAPI sidecar provides the API, compilation pipeline, and data layer. All network traffic between the renderer and backend is confined to `127.0.0.1`.

### Core Capabilities

| Capability | Description |
|------------|-------------|
| **Node Editor** | Visual scenario editor with drag-and-drop blocks, connection routing, undo history, and live property editing in a dedicated sidebar. |
| **Post Studio** | Telegram post publisher featuring dual-mode (Visual & Raw HTML) editor, inline keyboard builder, media album management, post scheduling, live Telegram preview, and real-time post editing/deletion. |
| **Channel Manager & Moderation** | Telegram administration engine with comprehensive channel analytics, anti-flood limits, entity-level link shield, automated warning decay, and live comment moderation. |
| **Dashboard & SVG Engine** | Lightweight zero-dependency Vanilla JS SVG icon architecture integrated into a dark glassmorphism dashboard layout. |
| **Ecosystem Sync** | Bundled plugin catalog, user-authored custom blocks, template library, and cloud marketplace packs share a unified import and deployment workflow. |
| **Data Privacy** | User projects, databases, plugins, and settings are stored under `%AppData%\botbuilder-desktop\` and are never written into the installation directory. |
| **Localization Engine** | Full UI localization (English, Russian, Spanish) with runtime language switching, cross-window IPC synchronization, and plugin metadata translation. |

---

## System Architecture

The diagram below illustrates BotBuilder's hybrid architecture, showing the data flow and process isolation between the Electron shell, FastAPI sidecar, local AppData storage, and embedded Python runtime environment:

```mermaid
flowchart LR
  subgraph ELECTRON["Electron Shell"]
    direction TB
    MAIN["Electron Main · main.js<br/>Sidecar spawn · windows<br/>port 127.0.0.1 · IPC · settings"]
    PRE["Preload · contextBridge<br/>electronAPI · lang sync"]
    UI["UI Renderer · Vanilla SPA<br/>Canvas RAF · SVG Engine<br/>Post Studio · Hub · Editor"]
    MAIN --> PRE --> UI
  end

  subgraph FASTAPI["FastAPI Sidecar"]
    direction TB
    API["REST Router<br/>/api/bots · scenario<br/>publisher · channel · broadcast"]
    COMP["Jinja2 Compiler<br/>scenario → main.py aiogram 3"]
    RUN["Bot Runner<br/>PID · start/stop · logs"]
    SMM["SMM Engines<br/>Channel Hub · Publisher<br/>Bots Broadcast Studio"]
    API --> COMP
    API --> RUN
    API --> SMM
  end

  subgraph DATA["Data · %AppData%/botbuilder-desktop/data"]
    direction TB
    APPDB["App DB · db.sqlite3<br/>bots · users · metadata"]
    BOTDB["Per-Bot · user_data.db<br/>hub · posts · bans · inventory"]
    FS["FS · plugins/ · bot_{id}/<br/>ui.json · jinja · main.py"]
  end

  subgraph RUNTIME["Isolated Runtime"]
    direction TB
    EMBED["python_embed CPython"]
    BOT["bot_{id}/main.py<br/>aiogram 3.4 · poll/webhook"]
    EMBED -->|"executes"| BOT
  end

  TG["Telegram Bot API<br/>HTTPS"]

  MAIN -->|"spawn · health · shutdown"| API
  UI -->|"HTTP REST 127.0.0.1"| API
  API -->|"SQLAlchemy"| APPDB
  SMM -->|"SQLite"| BOTDB
  COMP -->|"Jinja2 codegen"| FS
  RUN -->|"spawn PID"| EMBED
  BOT -->|"SQLite"| BOTDB
  SMM -->|"Bot API HTTP"| TG
  BOT -->|"aiogram"| TG

  classDef electron fill:#2b2d31,color:#fff,stroke:#64B5F6,stroke-width:2px
  classDef fastapi fill:#2b2d31,color:#fff,stroke:#4DB6AC,stroke-width:2px
  classDef data fill:#2b2d31,color:#fff,stroke:#BA68C8,stroke-width:2px
  classDef runtime fill:#2b2d31,color:#fff,stroke:#FFB74D,stroke-width:2px
  classDef telegram fill:#2b2d31,color:#fff,stroke:#81C784,stroke-width:2px

  class MAIN,PRE,UI electron
  class API,COMP,RUN,SMM fastapi
  class APPDB,BOTDB,FS data
  class EMBED,BOT runtime
  class TG telegram

  style ELECTRON fill:#1e1f22,stroke:#3f4248,color:#fff
  style FASTAPI fill:#1e1f22,stroke:#3f4248,color:#fff
  style DATA fill:#1e1f22,stroke:#3f4248,color:#fff
  style RUNTIME fill:#1e1f22,stroke:#3f4248,color:#fff
```
<p align="center">
  <sub><b>Figure 1:</b> High-level architecture, IPC bridges, and runtime execution isolation model.</sub>
</p>

---

## Visual Demonstration

<p align="center">
  <img src="docs/assets/Dashboard_New.png" alt="Redesigned Dashboard" width="85%">
  <br><sub>Redesigned Dashboard with native Vanilla JS SVG icons</sub>
</p>

<br>

<table width="100%">
  <tr>
    <td align="center" width="50%">
      <img src="docs/assets/Post_Editor.png" alt="Post Studio & Live Preview" width="100%">
      <br><sub>Telegram Post Studio & Live Preview</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/assets/Channel_Manager.png" alt="Channel Manager & Moderation" width="100%">
      <br><sub>Channel Manager & Moderation</sub>
    </td>
  </tr>
</table>

<br>

<table width="100%">
  <tr>
    <td align="center" width="50%">
      <img src="docs/assets/demo-scenario-editor.png" alt="Scenario Editor" width="100%">
      <br><sub>Scenario editor</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/assets/BotBuilder_Library.png" alt="BotBuilder Library" width="100%">
      <br><sub>Template library</sub>
    </td>
  </tr>
</table>

<br>

<p align="center">
  <img src="docs/assets/BotBuilder_Log.png" alt="BotBuilder Logs" width="85%">
  <br><sub>Control & logging center</sub>
</p>

<br>

<table width="100%">
  <tr>
    <td align="center" width="50%">
      <img src="docs/assets/BotBuilder_Plugins.png" alt="BotBuilder Plugins" width="100%">
      <br><sub>Plugins</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/assets/BotBuilder_componentWizard.png" alt="Component Wizard" width="100%">
      <br><sub>Component wizard</sub>
    </td>
  </tr>
</table>

---

## For Users

### Quick Start

1. Download `BotBuilder-Setup-{version}.exe` from the release artifacts.
2. Run the installer. Read and accept the End User License Agreement (EULA) on the mandatory license page before proceeding.
3. Choose an installation directory (default: `C:\Program Files\BotBuilder`).
4. Launch BotBuilder from the desktop shortcut or Start Menu.
5. On first run, select your interface language and appearance theme, then click **Continue**.
6. Open **Bots**, create a bot, and launch the **Scenario Editor** or **Post Studio** to begin building your workflow.

For detailed installation steps, interface reference, and marketplace usage, see [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

---

## For Developers

### Architectural Highlights

| Component | Summary |
|-----------|---------|
| **Asynchronous IPC Bridge** | Electron Main spawns and supervises a FastAPI sidecar process. The renderer communicates exclusively via HTTP to `127.0.0.1:{port}/api`. Health checks, graceful shutdown, and port conflict resolution are handled in the main process. |
| **Zero-Dependency Runtime** | Customer bot scripts execute through a bundled `python_embed` interpreter shipped with the installer. No system-wide Python installation is required in production. |
| **Dynamic Plugin Subsystem** | Block plugins are discovered at runtime from filesystem directories. Each plugin exposes `ui.json` metadata and a Jinja2 code template; user plugins override bundled definitions without recompilation of the shell. |
| **Layout Performance** | The scenario canvas batches DOM and SVG updates through `requestAnimationFrame`, coalesces connection redraws, and applies transform-based pan/zoom to avoid layout thrashing during drag operations. |

Full system design, path isolation model, and frontend performance strategy: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

### Build Commands

```bash
npm install
npm run build:prod
```

Output: `dist-electron/BotBuilder-Setup-{version}.exe`

---

## 🗺️ Roadmap

We are actively expanding BotBuilder to become the ultimate multi-channel visual automation hub. 

- [x] **Phase 1:** Core Node Engine & Runtime compiler (Telegram Support)
- [x] **Phase 1.1: Post Studio, Channel Analytics & Auto-Moderation Engine
- [ ] **Phase 2:** Linux & macOS cross-platform support (AppImage / DMG builds)
- [ ] **Phase 3:** **WhatsApp Business API** integration layer
- [ ] **Phase 4:** **Instagram Graph API** direct messaging nodes
- [ ] **Phase 5:** Native Telegram WebApps (Mini Apps) drag-and-drop builder

---

## License Summary

BotBuilder is distributed under the **Elastic License v2**. You may use, copy, and modify the software subject to the license terms. Redistribution of the compiled installer for commercial resale is prohibited without a separate agreement.

Third-party dependency licenses are bundled in the installer at `resources/licenses/ThirdPartyNotices.txt`. The installer EULA presented during setup is located at `backend/build/LICENSE.txt`.

For the complete license text, refer to the [Elastic License 2.0](https://www.elastic.co/licensing/elastic-license) or the EULA displayed during installation.
