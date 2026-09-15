from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class Host:
    name: str
    hostname: str
    username: str = "root"
    port: int = 22
    group: str = "Ungrouped"
    auth: str = "password"
    key_path: str = ""
    color: str = "#0A84FF"
    favorite: bool = False
    tags: list[str] = field(default_factory=list)
    id: str = field(default_factory=lambda: uuid4().hex)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Host":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in value.items() if k in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Snippet:
    name: str
    command: str
    description: str = ""
    group: str = "General"
    id: str = field(default_factory=lambda: uuid4().hex)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "Snippet":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in value.items() if k in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TunnelRule:
    name: str
    host_id: str
    remote_port: int
    local_host: str = "127.0.0.1"
    local_port: int = 3000
    bind_host: str = "0.0.0.0"
    public_host: str = ""
    persistent: bool = False
    enabled: bool = False
    id: str = field(default_factory=lambda: uuid4().hex)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "TunnelRule":
        allowed = cls.__dataclass_fields__.keys()
        return cls(**{k: v for k, v in value.items() if k in allowed})

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
