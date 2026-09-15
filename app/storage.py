from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any

import keyring

from .models import Host, Snippet, TunnelRule
from .vault import protect, unprotect


class Store:
    SERVICE = "NexTerm"
    DEFAULT_DISCORD_CLIENT_ID = "1300038133793947718"

    DEFAULTS: dict[str, Any] = {
        "hosts": [],
        "folders": ["Ungrouped"],
        "snippets": [
            {"name": "System overview", "command": "uptime && free -h && df -h /", "description": "Load, memory and root disk", "group": "Diagnostics", "id": "builtin-system"},
            {"name": "Listening ports", "command": "ss -tulpn", "description": "TCP and UDP listeners", "group": "Network", "id": "builtin-ports"},
            {"name": "Docker containers", "command": "docker ps --format 'table {{.Names}}\\t{{.Status}}\\t{{.Ports}}'", "description": "Running containers", "group": "Docker", "id": "builtin-docker"},
        ],
        "tunnels": [],
        "auto_imported": [],
        "history": [],
        "settings": {
            "theme": "System", "accent": "#0067C0", "font": "Cascadia Mono",
            "font_size": 12, "terminal_bg": "#0B0F14", "terminal_fg": "#D7DEE8",
            "cursor": "#FFFFFF", "keepalive": 30, "reconnect": True,
            "copy_on_select": False, "confirm_close": True, "cursor_blink": True,
            "mica": True, "show_hidden": False, "scrollback": 10000,
            "in_app_notifications": True, "system_notifications": True,
            "sound_notifications": False, "autostart": False, "window_opacity": 100,
            "palette": "NexTerm Blue", "github_repo": "Ilja/NexTerm",
            "license_key": "", "license_edition": "Standard", "license_status": "active",
            "discord_rpc": False, "discord_client_id": DEFAULT_DISCORD_CLIENT_ID,
            "discord_details": "Взламывает Пентагон",
        },
    }

    def __init__(self):
        root = Path(os.getenv("APPDATA", Path.home())) / "NexTerm"
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / "data.json"
        self.known_hosts_path = root / "known_hosts"
        self.vault_path = root / "vault"
        self.imports_path = root / "imports"
        self.license_cache_path = root / "license.json"
        self.vault_path.mkdir(exist_ok=True)
        self.imports_path.mkdir(exist_ok=True)
        self.known_hosts_path.touch(exist_ok=True)
        self.data: dict[str, Any] = deepcopy(self.DEFAULTS)
        self._hosts_cache: list[Host] | None = None
        self._snippets_cache: list[Snippet] | None = None
        self._tunnels_cache: list[TunnelRule] | None = None
        self._folders_cache: list[str] | None = None
        self.load()

    def load(self):
        if self.path.exists():
            try:
                incoming = json.loads(self.path.read_text(encoding="utf-8-sig"))
                if not isinstance(incoming, dict):
                    return
                settings = incoming.pop("settings", {})
                self.data.update(incoming)
                if isinstance(settings, dict):
                    self.data["settings"].update(settings)
                if not str(self.data["settings"].get("discord_client_id","")).strip():
                    self.data["settings"]["discord_client_id"] = self.DEFAULT_DISCORD_CLIENT_ID
                for key in ("hosts", "folders", "snippets", "tunnels", "auto_imported", "history"):
                    if not isinstance(self.data.get(key), list):
                        self.data[key] = deepcopy(self.DEFAULTS[key])
                for key in ("hosts", "snippets", "tunnels", "history"):
                    self.data[key] = [item for item in self.data[key] if isinstance(item, dict)]
                self.data["folders"] = [str(item).strip() for item in self.data["folders"] if str(item).strip()]
                self.data["auto_imported"] = [str(item) for item in self.data["auto_imported"] if isinstance(item, str)]
            except (OSError, ValueError, TypeError):
                pass

    def save(self):
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(self.path)

    @property
    def hosts(self) -> list[Host]:
        if self._hosts_cache is not None:
            return list(self._hosts_cache)
        values=[]
        for item in self.data["hosts"]:
            try:values.append(Host.from_dict(item))
            except TypeError:pass
        self._hosts_cache=values
        return list(values)

    @property
    def snippets(self) -> list[Snippet]:
        if self._snippets_cache is not None:
            return list(self._snippets_cache)
        values=[]
        for item in self.data["snippets"]:
            try:values.append(Snippet.from_dict(item))
            except TypeError:pass
        self._snippets_cache=values
        return list(values)

    @property
    def tunnels(self) -> list[TunnelRule]:
        if self._tunnels_cache is not None:
            return list(self._tunnels_cache)
        values=[]
        for item in self.data["tunnels"]:
            try:values.append(TunnelRule.from_dict(item))
            except TypeError:pass
        self._tunnels_cache=values
        return list(values)

    @property
    def folders(self) -> list[str]:
        if self._folders_cache is not None:
            return list(self._folders_cache)
        names={str(item).strip() or "Ungrouped" for item in self.data.get("folders",[])}
        names.update((h.group or "Ungrouped") for h in self.hosts)
        names.add("Ungrouped")
        self._folders_cache=sorted(names, key=lambda value: (value.casefold()!="ungrouped", value.casefold()))
        return list(self._folders_cache)

    def set_hosts(self, values: list[Host]):
        self.data["hosts"] = [x.to_dict() for x in values]
        self._hosts_cache = list(values)
        self._folders_cache = None
        self.save()

    def set_folders(self, values: list[str]):
        cleaned=[]
        seen=set()
        for value in values:
            name=str(value).strip() or "Ungrouped"
            key=name.casefold()
            if key not in seen:
                cleaned.append(name);seen.add(key)
        if "ungrouped" not in seen:cleaned.insert(0,"Ungrouped")
        self.data["folders"]=cleaned
        self._folders_cache = None
        self.save()

    def set_snippets(self, values: list[Snippet]):
        self.data["snippets"] = [x.to_dict() for x in values]
        self._snippets_cache = list(values)
        self.save()

    def set_tunnels(self, values: list[TunnelRule]):
        self.data["tunnels"] = [x.to_dict() for x in values]
        self._tunnels_cache = list(values)
        self.save()

    def secret(self, host_id: str, kind: str = "password") -> str:
        try:
            return keyring.get_password(self.SERVICE, f"{host_id}:{kind}") or ""
        except Exception:
            return ""

    def set_secret(self, host_id: str, value: str, kind: str = "password"):
        if not value:return
        try:
            account = f"{host_id}:{kind}"
            keyring.set_password(self.SERVICE, account, value)
        except Exception:
            pass

    def set_private_key(self,host_id:str,path:str):
        data=Path(path).expanduser().read_bytes()
        target=self.vault_path/f"{host_id}.key";temp=target.with_suffix(".tmp")
        temp.write_bytes(protect(data));temp.replace(target)

    def private_key(self,host_id:str)->str:
        target=self.vault_path/f"{host_id}.key"
        if not target.exists():return ""
        try:return unprotect(target.read_bytes()).decode("utf-8")
        except (OSError,UnicodeDecodeError):return ""

    def has_private_key(self,host_id:str)->bool:
        return (self.vault_path/f"{host_id}.key").exists()

    def delete_private_key(self,host_id:str):
        try:(self.vault_path/f"{host_id}.key").unlink(missing_ok=True)
        except OSError:pass

    def delete_secret(self, host_id: str):
        for kind in ("password", "passphrase"):
            try:
                keyring.delete_password(self.SERVICE, f"{host_id}:{kind}")
            except Exception:
                pass
        self.delete_private_key(host_id)

    def add_history(self, host: Host, status: str, detail: str = ""):
        from datetime import datetime
        self.data["history"].insert(0, {
            "time": datetime.now().isoformat(timespec="seconds"), "host": host.name,
            "address": host.hostname, "status": status, "detail": detail,
        })
        self.data["history"] = self.data["history"][:500]
        self.save()
