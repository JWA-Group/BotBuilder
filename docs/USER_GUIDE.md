# BotBuilder User Guide

This document provides end-user instructions for installing, configuring, and operating BotBuilder on Windows.

---

## 1. System Requirements

| Requirement | Minimum |
|-------------|---------|
| Operating System | Windows 10 (64-bit) or Windows 11 |
| Processor | x64-compatible CPU |
| Memory | 4 GB RAM (8 GB recommended) |
| Disk Space | 500 MB for application; additional space for bot projects and databases |
| Network | Required for marketplace downloads and bot API connectivity; the local IDE operates offline after installation |
| Display | 1280 x 720 minimum resolution |

BotBuilder installs per-machine (all users). Administrator privileges may be required depending on the chosen installation directory.

---

## 2. Detailed Installation Walkthrough

### 2.1 Obtain the Installer

Download the latest `BotBuilder-Setup-{version}.exe` from your distribution channel or release page.

### 2.2 Run the Installer

1. Double-click the installer executable.
2. If Windows SmartScreen prompts for confirmation, select **More info** then **Run anyway** (for unsigned development builds) or proceed normally for signed releases.
3. The installer wizard opens.

### 2.3 End User License Agreement (EULA)

Before any files are copied, the installer presents a **mandatory license agreement page**.

1. Read the full End User License Agreement text displayed in the installer window.
2. You must scroll through and acknowledge the terms to enable the **Next** or **Install** button.
3. If you do not agree with the terms, cancel the installation. BotBuilder cannot be installed without accepting the EULA.

The EULA defines permitted use of the software, commercial rights over bots you create, and restrictions on redistributing the application itself.

### 2.4 Choose Installation Directory

1. On the destination folder screen, accept the default path (`C:\Program Files\BotBuilder`) or click **Browse** to select a custom location.
2. Confirm that sufficient disk space is available.
3. Click **Install** and wait for file extraction to complete.

### 2.5 Finish Installation

1. Optionally enable **Run BotBuilder** on the final screen.
2. Click **Finish**.
3. Shortcuts are created on the Desktop and in the Start Menu under **BotBuilder**.

### 2.6 First Launch

On the first application start:

1. A setup window prompts for **Language** (English, Russian, or Spanish).
2. Select **Appearance** (Light or Dark theme).
3. Click **Continue**.

Settings are stored at `%AppData%\botbuilder-desktop\settings.json` and persist across sessions.

### 2.7 Uninstallation

Remove BotBuilder through **Settings > Apps > Installed apps** (or **Programs and Features**). The uninstaller removes the installation directory and clears application data under `%AppData%\botbuilder-desktop\`.

---

## 3. Interface Overview

BotBuilder organizes work into modular windows accessible from the application menu. The primary authoring surface is the **Scenario Editor**.

### 3.1 Workspace (Canvas)

The central workspace is the scenario canvas:

- **Canvas area** — infinite grid where workflow blocks are placed and connected.
- **Toolbar** — block palette (Start, Message, Menu, Condition, and custom plugins), save controls, AI assistant, history mode, and plugin visibility toggle.
- **Connection layer** — SVG overlay rendering edges between block ports.
- **Grid and theme controls** — toggle snap grid and switch light/dark appearance from the canvas corner controls.

Pan the canvas by dragging with the primary mouse button. Zoom with the mouse wheel.

### 3.2 Sidebar (Editor Panel)

The right sidebar is the **Editor** panel:

- Appears when a block is selected on the canvas.
- Displays block-specific properties: message text, button labels, conditions, data bindings, and plugin-defined custom fields.
- Changes apply to the selected block immediately; use **Save** in the toolbar to persist the scenario to disk.

When no block is selected, the sidebar displays a neutral prompt.

### 3.3 Console and Monitoring

Operational feedback is available through dedicated views:

| View | Purpose |
|------|---------|
| **Bots** | List, create, start, and stop bot instances. |
| **System Monitor** | CPU, memory, and running process status for local bot workers. |
| **Database Manager** | Inspect and manage application SQLite databases. |
| **Deployment** | Package and export bot projects for target environments. |

Log output from running bots is accessible through the monitor and bot management screens. API-level errors are surfaced in dialog boxes when the local server cannot start or a port conflict occurs.

---

## 4. Connecting Nodes and Managing Layouts

### 4.1 Adding Blocks

1. Open a bot and enter the **Scenario Editor**.
2. Click a block type in the toolbar to place it on the canvas.
3. Drag the block to the desired position. Blocks snap to the grid when the grid overlay is enabled.

### 4.2 Creating Connections

1. Locate the output port on the source block (typically at the bottom or side edge).
2. Click and drag from the output port to the input port of the target block.
3. Release to create a directed connection. The SVG layer redraws the edge automatically.

Connections define execution flow: the compiler traverses the graph starting from the **Start** node.

### 4.3 Editing Block Properties

1. Click a block to select it.
2. Modify fields in the right **Editor** sidebar.
3. For menu blocks, reorder buttons via drag-and-drop within the sidebar button editor.

### 4.4 Layout Management

| Action | Method |
|--------|--------|
| Undo | `Ctrl+Z` (undo depth configurable in Settings) |
| Redo | `Ctrl+Y` |
| Save scenario | Toolbar save button or `Ctrl+S` |
| Save as template | Toolbar template button |
| Fit view | Use canvas zoom controls to frame all blocks |

### 4.5 Compiling and Running

1. Save the scenario.
2. Return to **Bots** and start the bot.
3. BotBuilder compiles the scenario graph into a Python script and launches it with the embedded Python runtime.

---

## 5. Downloading Extensions from the Cloud Marketplace

The **Template Library** provides access to local templates and remote marketplace packs.

### 5.1 Open the Template Library

From the application menu, navigate to **Templates**. The library opens in a dedicated window.

### 5.2 Browse the Marketplace

1. Select the **Marketplace** tab.
2. Browse available packs by category or use the search field.
3. Each card displays the pack name, description, tags, and source badge (Market / Local).

### 5.3 Install a Pack

1. Click **Install** or **Download** on the desired marketplace item.
2. Wait for the download and import to complete. Progress is indicated on the card.
3. Installed packs appear under the **Local** or **Catalog** section and become available for import into bot scenarios.

### 5.4 Apply a Template to a Bot

1. Open the target bot in the Scenario Editor.
2. Use the template import workflow from the editor or template library.
3. Review imported blocks and connections; adjust properties as needed.
4. Save the scenario before starting the bot.

### 5.5 Plugin Extensions

Custom block plugins can also be authored in the **Plugin Builder** and managed in **Plugins**. Marketplace template packs may include pre-built plugin definitions that are installed alongside scenario data.

---

## Related Documentation

| Document | Audience |
|----------|----------|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Engineers and technical reviewers |
| [README.md](../README.md) | Project overview and quick start |

For application settings (API port, undo steps, language, theme), open **Settings** from the menu bar.
