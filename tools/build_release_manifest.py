"""Build a deterministic inventory for the clean source release."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "release_manifest.json"
FORBIDDEN_PARTS = {".env", ".secrets", ".venv", "node_modules", "__pycache__", ".pytest_cache"}
FORBIDDEN_SUFFIXES = {".pyc"}


def digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main() -> None:
    files = []
    groups: Counter[str] = Counter()
    total_bytes = 0
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or path == OUTPUT:
            continue
        relative = path.relative_to(ROOT)
        if any(part in FORBIDDEN_PARTS for part in relative.parts) or path.suffix in FORBIDDEN_SUFFIXES:
            raise RuntimeError(f"FORBIDDEN_RELEASE_ARTIFACT:{relative.as_posix()}")
        size = path.stat().st_size
        total_bytes += size
        groups[relative.parts[0]] += 1
        files.append({"path": relative.as_posix(), "bytes": size, "sha256": digest(path)})
    payload = {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "release": ROOT.name,
        "file_count": len(files),
        "total_bytes_excluding_manifest": total_bytes,
        "files_by_top_level": dict(sorted(groups.items())),
        "exclusions": [
            "backend/.env and .secrets",
            "Python and Node dependency directories",
            "runtime caches and test-machine JUnit XML",
            "Docker images, volumes and embedding weights",
            "large downloadable or reproducible datasets",
            "obsolete and duplicate historical run artifacts",
        ],
        "files": files,
    }
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"file_count": len(files), "bytes": total_bytes}, ensure_ascii=True))


if __name__ == "__main__":
    main()
