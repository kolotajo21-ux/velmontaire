from __future__ import annotations

import hashlib
import json
from pathlib import Path

from runtime_foundation_manifest import (
    CRITICAL_FILES,
    RUNTIME_FOUNDATION_MILESTONE,
    RUNTIME_FOUNDATION_NAME,
    RUNTIME_FOUNDATION_STATUS,
    RUNTIME_FOUNDATION_VERSION,
)

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "runtime_foundation_v1.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while True:
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    missing = []
    files = {}

    for relative in CRITICAL_FILES:
        path = ROOT / relative

        if not path.is_file():
            missing.append(relative)
            continue

        files[relative] = {
            "sha256": sha256(path),
            "size": path.stat().st_size,
        }

    if missing:
        print("RUNTIME FOUNDATION FREEZE FAILED")
        print("Missing critical files:")
        for item in missing:
            print(f" - {item}")
        raise SystemExit(1)

    payload = {
        "name": RUNTIME_FOUNDATION_NAME,
        "version": RUNTIME_FOUNDATION_VERSION,
        "milestone": RUNTIME_FOUNDATION_MILESTONE,
        "status": RUNTIME_FOUNDATION_STATUS,
        "critical_file_count": len(files),
        "files": files,
    }

    OUTPUT.write_text(
        json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print("=" * 88)
    print("RUNTIME FOUNDATION V1 FREEZE")
    print("=" * 88)
    print(f"Version: {RUNTIME_FOUNDATION_VERSION}")
    print(f"Milestone: {RUNTIME_FOUNDATION_MILESTONE}")
    print(f"Status: {RUNTIME_FOUNDATION_STATUS}")
    print(f"Critical files hashed: {len(files)}")
    print(f"Manifest: {OUTPUT}")
    print("✅ RUNTIME FOUNDATION V1 HASH MANIFEST CREATED")


if __name__ == "__main__":
    main()