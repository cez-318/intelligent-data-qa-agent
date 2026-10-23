"""Copy source archives into an isolated directory, excluding secrets and caches."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT.parent / "3.代码"


def prepare():
    manifest = {}
    for filename, target in [("data-agent.zip", "backend"), ("data-agent-fronted.zip", "frontend")]:
        archive = SOURCE / filename
        manifest[filename] = hashlib.sha256(archive.read_bytes()).hexdigest()
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                parts = Path(member.filename).parts[1:]
                if not parts or member.is_dir() or "__pycache__" in parts:
                    continue
                relative = Path(*parts)
                if relative.as_posix() in {"conf/app_config.yaml", "uv.lock"}:
                    continue
                dest = (ROOT / target / relative).resolve()
                if not dest.is_relative_to(ROOT / target):
                    raise ValueError("Unsafe archive path")
                if dest.exists():
                    raise FileExistsError(dest)
                dest.parent.mkdir(parents=True, exist_ok=True)
                raw = zipped.read(member)
                if dest.suffix in {".py", ".yaml", ".prompt", ".toml"}:
                    raw = raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "").encode("utf-8")
                dest.write_bytes(raw)
    (ROOT / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


if __name__ == "__main__":
    prepare()
