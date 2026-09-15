# NexTerm

NexTerm is a Windows SSH/SFTP desktop client built with PyQt5 and PyQt-Fluent-Widgets.

## Features

![NexTerm main window](docs/screenshots/nexterm-main.png)

- SSH terminal with tabs, reconnect, snippets, mouse reporting and themed colors.
- Two-panel SFTP workspace with upload, download, rename, delete and drag-and-drop.
- Host groups with create, rename, delete and move-to-group actions.
- TCP tunnels through a VPS, including web and raw TCP traffic.
- Termius migration helper: imports exports, OpenSSH config and backs up the local Termius profile.
- Settings for theme, palette, opacity, autostart, notifications, sounds, Discord RPC and GitHub update checks.
- Optional Enterprise activation with offline grace.

![NexTerm settings](docs/screenshots/nexterm-settings.png)

## Run From Source

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Build EXE

```powershell
powershell -ExecutionPolicy Bypass -File build.ps1
```

The EXE is created at:

```text
dist\NexTerm\NexTerm.exe
```

## Editions

Standard is the default local edition. Enterprise activation is available for private builds and managed deployments.

See [LICENSE](LICENSE) and [ENTERPRISE_LICENSE.md](ENTERPRISE_LICENSE.md).
