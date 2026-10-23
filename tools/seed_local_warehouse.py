"""Initialize only the named isolated empty warehouse with fictional records."""
import argparse
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONTAINER = "qa-opt-mysql"


def mysql(docker, sql):
    # Password stays inside the container; SQL is delivered on stdin, not argv.
    command = 'export MYSQL_PWD="$(cat "$MYSQL_ROOT_PASSWORD_FILE")"; exec mysql -uroot --default-character-set=utf8mb4 --batch --skip-column-names dw'
    result = subprocess.run([docker, "exec", "-i", CONTAINER, "sh", "-c", command],
                            input=sql, text=True, encoding="utf-8", capture_output=True, timeout=30)
    if result.returncode:
        raise RuntimeError("LOCAL_WAREHOUSE_SQL_FAILED")
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--docker", default=shutil.which("docker"))
    parser.add_argument("--confirm-empty-local-warehouse", action="store_true", required=True)
    args = parser.parse_args()
    if not args.docker:
        parser.error("Docker executable not found")
    inspect = subprocess.run([args.docker, "inspect", CONTAINER, "--format", '{{index .Config.Labels "com.docker.compose.project"}}'],
                             capture_output=True, text=True, timeout=15)
    if inspect.returncode or inspect.stdout.strip() != "intelligent-qa-optimized":
        raise RuntimeError("NOT_THE_ISOLATED_PROJECT_CONTAINER")
    count = int(mysql(args.docker, "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='dw';"))
    if count:
        manifest = mysql(args.docker, "SELECT dataset FROM qa_fixture_manifest;")
        if manifest == "fictional_ecommerce_v1_five_orders":
            print("Known fictional fixture already exists; no changes made.")
            return
        raise RuntimeError("WAREHOUSE_NOT_EMPTY_NO_OVERWRITE")
    mysql(args.docker, (ROOT / "backend/data/sample_warehouse.sql").read_text(encoding="utf-8"))
    print("Created original-schema fixture: 5 fictional orders. Existing databases were not modified.")


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, subprocess.TimeoutExpired):
        raise SystemExit("Warehouse initialization stopped safely; no credentials or database errors displayed.") from None
