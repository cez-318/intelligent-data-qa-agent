"""Generate private local credentials without printing secrets or resetting users.

Only prepares the new isolated compose.mysql.yaml deployment. Does not modify
an existing database. The output files are generated configuration artifacts.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets

ROOT = Path(__file__).resolve().parents[1]
SECRET_KEYS = ("DATA_AGENT_API_TOKEN", "META_DB_PASSWORD", "DW_DB_PASSWORD")
CONNECTION = {"META_DB_HOST": "127.0.0.1", "META_DB_PORT": "13306", "META_DB_USER": "metadata_owner", "META_DB_NAME": "meta",
              "DW_DB_HOST": "127.0.0.1", "DW_DB_PORT": "13306", "DW_DB_USER": "qa_readonly", "DW_DB_NAME": "dw"}


def read_env(path):
    values = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or key.strip() in values:
            raise ValueError("Invalid or duplicate environment setting")
        values[key.strip()] = value.strip().strip("\"'")
    return values


def prepare(root=ROOT):
    root = Path(root)
    env = root / "backend" / ".env"
    values = read_env(env)
    directory = root / ".secrets"
    marker = directory / "local-mysql.json"
    if marker.exists():
        saved = json.loads(marker.read_text())
        for key in SECRET_KEYS:
            digest = hashlib.sha256(values.get(key, "").encode()).hexdigest()
            if digest != saved["digests"][key]:
                raise ValueError("Credentials changed; refusing to rotate automatically")
        if any(values.get(key) != value for key, value in CONNECTION.items()):
            raise ValueError("Connection changed; refusing to overwrite")
        if not all((directory / name).is_file() for name in ("mysql-root-password", "mysql-init.sql")):
            raise ValueError("Private initialization files missing")
        return
    if any(values.get(key) for key in ("META_DB_PASSWORD", "DW_DB_PASSWORD")) or directory.exists():
        raise ValueError("Existing credentials or private state; manual review required")
    for key, expected in CONNECTION.items():
        allowed = {expected, "3306"} if key.endswith("PORT") else {expected}
        if values.get(key) and values[key] not in allowed:
            raise ValueError("Custom database settings found; refusing to replace")
    updates = {key: values.get(key) or secrets.token_hex(32) for key in SECRET_KEYS}
    updates.update(CONNECTION)
    # Generated hex passwords cannot introduce SQL syntax.
    for key in ("META_DB_PASSWORD", "DW_DB_PASSWORD"):
        if not re.fullmatch(r"[0-9a-f]{64}", updates[key]):
            raise ValueError("Invalid generated database credential")
    sql = (
        "CREATE DATABASE meta CHARACTER SET utf8mb4;\n"
        "CREATE DATABASE dw CHARACTER SET utf8mb4;\n"
        f"CREATE USER 'metadata_owner'@'%' IDENTIFIED BY '{updates['META_DB_PASSWORD']}';\n"
        f"CREATE USER 'qa_readonly'@'%' IDENTIFIED BY '{updates['DW_DB_PASSWORD']}';\n"
        "GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, REFERENCES ON meta.* TO 'metadata_owner'@'%';\n"
        "GRANT SELECT ON dw.* TO 'qa_readonly'@'%';\n"
    )
    directory.mkdir(mode=0o700)
    for name, content in (("mysql-root-password", secrets.token_hex(32)), ("mysql-init.sql", sql)):
        target = directory / name
        with target.open("x", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        target.chmod(0o600)
    lines, seen = [], set()
    for line in env.read_text(encoding="utf-8-sig").splitlines():
        key = line.partition("=")[0].strip()
        if key in updates:
            lines.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            lines.append(line)
    lines.extend(f"{key}={value}" for key, value in updates.items() if key not in seen)
    env.write_text("\n".join(lines) + "\n", encoding="utf-8")
    marker.write_text(json.dumps({"digests": {key: hashlib.sha256(updates[key].encode()).hexdigest() for key in SECRET_KEYS}}), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare", action="store_true", required=True)
    parser.parse_args()
    try:
        prepare()
    except (OSError, ValueError, KeyError):
        raise SystemExit("Credential setup stopped safely; review existing configuration. No secrets printed.") from None
    print("Local credentials prepared; no values displayed. MySQL account activation requires Compose startup.")
