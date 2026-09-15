from __future__ import annotations

import os
import sys
import urllib.request
import json
from pathlib import Path
from typing import Any


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_autostart(enabled: bool, name: str = "NexTerm"):
    if os.name != "nt":
        return
    import winreg

    command = f'"{sys.executable}"'
    if not getattr(sys, "frozen", False):
        command += f' "{Path(sys.argv[0]).resolve()}"'
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, name, 0, winreg.REG_SZ, command)
        else:
            try:
                winreg.DeleteValue(key, name)
            except FileNotFoundError:
                pass


def check_github_version(repo: str, current_version: str) -> tuple[bool, str, str]:
    repo = repo.strip().strip("/")
    if not repo or "/" not in repo:
        raise ValueError("GitHub repo must look like owner/repo")
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    request = urllib.request.Request(url, headers={"User-Agent": "NexTerm"})
    with urllib.request.urlopen(request, timeout=8) as response:
        payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    latest = str(payload.get("tag_name") or payload.get("name") or "").lstrip("v")
    html_url = str(payload.get("html_url") or f"https://github.com/{repo}/releases")
    return _version_tuple(latest) > _version_tuple(current_version), latest, html_url


def _version_tuple(value: str) -> tuple[int, ...]:
    parts=[]
    for item in value.replace("-", ".").split("."):
        try:
            parts.append(int("".join(ch for ch in item if ch.isdigit()) or "0"))
        except ValueError:
            parts.append(0)
    return tuple(parts or [0])
