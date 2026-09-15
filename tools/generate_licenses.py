from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.license_manager import generate_activation_codes, sign_license


def main():
    out = Path("server/licenses")
    out.mkdir(parents=True, exist_ok=True)
    expires = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
    codes = generate_activation_codes(16)
    manifest = []
    for index, code in enumerate(codes, 1):
        payload = sign_license({
            "key": code,
            "edition": "Enterprise",
            "status": "active",
            "owner": f"Enterprise Seat {index:02d}",
            "expires_at": expires,
            "features": ["tunnels", "sftp", "groups", "priority-updates"],
        })
        (out / f"{code}.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        manifest.append({"key": code, "owner": payload["owner"], "file": f"{code}.json"})
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Generated {len(codes)} Enterprise licenses in {out}")


if __name__ == "__main__":
    main()
