from __future__ import annotations

import csv
import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import paramiko

from .models import Host


def import_hosts(path: str | Path) -> list[Host]:
    """Read OpenSSH config or a Termius-style JSON/CSV export."""
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".json":
        payload = json.loads(source.read_text(encoding="utf-8-sig"))
        return _hosts_from_json(payload)
    if suffix == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            return [_host_from_mapping(row, "Imported from Termius") for row in csv.DictReader(stream) if _address(row)]
    return _hosts_from_ssh_config(source)


def discover_termius_exports() -> list[Path]:
    roots=[Path.home()/"Downloads",Path.home()/"Desktop",Path.home()/"Documents"]
    found=[]
    for root in roots:
        if not root.exists():
            continue
        for pattern in ("*termius*.json","*Termius*.json","*termius*.csv","*Termius*.csv"):
            for path in root.glob(pattern):
                if path.is_file():
                    found.append(path)
        for pattern in ("*.json","*.csv"):
            for path in root.glob(pattern):
                if path.is_file() and path.stat().st_size < 50_000_000 and _looks_like_host_export(path):
                    found.append(path)
    return sorted(set(found), key=lambda p:p.stat().st_mtime if p.exists() else 0, reverse=True)


def _looks_like_host_export(path: Path) -> bool:
    try:
        sample=path.read_text(encoding="utf-8-sig",errors="ignore")[:120_000].lower()
    except OSError:
        return False
    return any(key in sample for key in ("hostname", "address", "sshport", "privatekeypath")) and any(key in sample for key in ("username", "user", "group", "label", "termius"))


def import_termius_local(root: str | Path | None = None) -> list[Host]:
    """Best-effort import from Termius' local Electron storage.

    Termius keeps synced data in Chromium LevelDB/IndexedDB. Passwords and
    private keys are intentionally ignored; we only extract host metadata.
    """
    base = Path(root) if root else Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "Termius"
    candidates = [
        base / "Local Storage" / "leveldb",
        base / "IndexedDB" / "file__0.indexeddb.leveldb",
    ]
    hosts: list[Host] = []
    seen: set[tuple[str, str, int]] = set()
    for folder in candidates:
        if not folder.exists():
            continue
        for path in sorted(folder.glob("*"), key=lambda item: item.stat().st_mtime, reverse=True):
            if path.suffix.lower() not in {".ldb", ".log"} or path.stat().st_size > 8_000_000:
                continue
            for item in _termius_objects_from_leveldb(path):
                for host in _hosts_from_json(item):
                    key = (host.hostname.casefold(), host.username.casefold(), host.port)
                    if host.hostname and key not in seen:
                        host.group = host.group or "Imported from Termius"
                        hosts.append(host);seen.add(key)
    return hosts


def termius_profile_path() -> Path:
    return Path(os.getenv("APPDATA", Path.home() / "AppData" / "Roaming")) / "Termius"


def backup_termius_profile(target_root: str | Path) -> tuple[Path | None, int, int]:
    source = termius_profile_path()
    if not source.exists():
        return None, 0, 0
    target_root = Path(target_root)
    target = target_root / f"Termius-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    copied = 0
    skipped = 0
    for item in source.rglob("*"):
        relative = item.relative_to(source)
        destination = target / relative
        try:
            if item.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)
            copied += 1
        except OSError:
            skipped += 1
    return target, copied, skipped


def _hosts_from_ssh_config(path: Path) -> list[Host]:
    config = paramiko.SSHConfig()
    with path.open(encoding="utf-8-sig") as stream:
        config.parse(stream)
    hosts=[]
    for alias in config.get_hostnames():
        if alias == "*" or "*" in alias or "?" in alias:
            continue
        value=config.lookup(alias);identities=value.get("identityfile") or []
        hosts.append(Host(alias,value.get("hostname",alias),value.get("user","root"),_port(value.get("port")),"Imported", "key" if identities else "password",identities[0] if identities else ""))
    return hosts


def _hosts_from_json(payload: Any) -> list[Host]:
    results=[]

    def visit(value: Any, group: str = "Imported from Termius"):
        if isinstance(value, list):
            for item in value:visit(item,group)
            return
        if not isinstance(value, dict):
            return
        address=_address(value)
        if address:
            results.append(_host_from_mapping(value,group))
            return
        label=_pick(value,"label","name","title")
        next_group=str(label).strip() if label and any(key in value for key in ("hosts","children","items")) else group
        for key,item in value.items():
            if key.lower() not in {"password","private","privatekey","passphrase","secret"}:visit(item,next_group)

    visit(payload)
    return results


def _termius_objects_from_leveldb(path: Path) -> list[dict[str, Any]]:
    data = path.read_bytes()
    text = data.decode("utf-8", errors="ignore")
    objects: list[dict[str, Any]] = []
    for chunk in _candidate_json_chunks(text):
        parsed = _loads_relaxed(chunk)
        if isinstance(parsed, dict):
            objects.append(parsed)
        elif isinstance(parsed, list):
            objects.extend(item for item in parsed if isinstance(item, dict))
    return objects


def _candidate_json_chunks(text: str) -> list[str]:
    chunks: list[str] = []
    lowered = text.lower()
    positions: list[int] = []
    for keyword in ("address", "hostname", "username", "ssh", "group", "label"):
        start = 0
        while True:
            index = lowered.find(keyword, start)
            if index < 0:
                break
            positions.append(index);start = index + len(keyword)
            if len(positions) > 1200:
                break
    for index in sorted(set(positions)):
        start = max(text.rfind("{", max(0, index - 2200), index), text.rfind("[", max(0, index - 2200), index))
        end_brace = text.find("}", index, min(len(text), index + 4200))
        end_list = text.find("]", index, min(len(text), index + 8200))
        ends = [value for value in (end_brace, end_list) if value >= 0]
        if start >= 0 and ends:
            chunks.append(text[start:min(ends) + 1])
        start = max(text.rfind("\\{", max(0, index - 2200), index), text.rfind("\\[", max(0, index - 2200), index))
        end_brace = text.find("\\}", index, min(len(text), index + 4200))
        end_list = text.find("\\]", index, min(len(text), index + 8200))
        ends = [value for value in (end_brace, end_list) if value >= 0]
        if start >= 0 and ends:
            chunks.append(text[start:min(ends) + 2])
        if len(chunks) > 1500:
            break
    return chunks


def _loads_relaxed(value: str) -> Any:
    for candidate in (value, value.replace('\\"', '"').replace("\\\\", "\\")):
        try:
            return json.loads(candidate)
        except (TypeError, ValueError):
            pass
    try:
        return json.loads(bytes(value, "utf-8").decode("unicode_escape"))
    except (TypeError, ValueError, UnicodeDecodeError):
        return None


def _host_from_mapping(value: dict[str, Any], default_group: str) -> Host:
    normalized={str(key).lower().replace("_","").replace(" ",""): item for key,item in value.items()}
    ssh=value.get("ssh") if isinstance(value.get("ssh"),dict) else {}
    credentials=ssh.get("credentials") if isinstance(ssh.get("credentials"),dict) else {}
    address=str(_pick(value,"address","hostname","host","ip") or "").strip()
    name=str(_pick(value,"label","name","title") or address).strip()
    username=str(_pick(value,"username","user") or _pick(credentials,"username","user") or "root").strip()
    port=_port(_pick(value,"port","sshPort") or _pick(ssh,"port"))
    group=str(_pick(value,"group","groupName","folder","vault") or default_group).strip()
    key_path=str(_pick(value,"keyPath","identityFile","privateKeyPath") or "").strip()
    if not address:
        address=str(normalized.get("address") or normalized.get("hostname") or "").strip()
    return Host(name,address,username,port,group,"key" if key_path else "password",key_path)


def _address(value: dict[str, Any]) -> str:
    found=_pick(value,"address","hostname","host","ip")
    return str(found).strip() if found is not None else ""


def _pick(value: dict[str, Any], *keys: str) -> Any:
    normalized={str(key).lower().replace("_","").replace(" ",""): item for key,item in value.items()}
    for key in keys:
        item=normalized.get(key.lower().replace("_","").replace(" ",""))
        if item not in (None,""):return item
    return None


def _port(value: Any) -> int:
    try:return max(1,min(65535,int(value or 22)))
    except (TypeError,ValueError):return 22
