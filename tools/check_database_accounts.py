"""Read-only local credential and grant check. Never prints passwords/grants."""
import asyncio
from pathlib import Path
import re
import sys
import asyncmy

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.conf.app_config import app_config


async def verify():
    for label, config in (("metadata", app_config.db_meta), ("warehouse", app_config.db_dw)):
        if config.host != "127.0.0.1" or config.port != 13306:
            raise ValueError("This check is restricted to the isolated local deployment")
        connection = await asyncmy.connect(host=config.host, port=config.port, user=config.user,
                                          password=config.password, db=config.database,
                                          connect_timeout=5, autocommit=True)
        try:
            async with connection.cursor() as cursor:
                await cursor.execute("SELECT 1")
                assert (await cursor.fetchone())[0] == 1
                await cursor.execute("SHOW GRANTS")
                grants = [row[0].replace("`", "") for row in await cursor.fetchall()]
                if label == "warehouse":
                    assert any(re.match(r"GRANT SELECT ON dw\.\* TO ", item) for item in grants)
                    assert all(re.match(r"GRANT (USAGE ON \*\.\*|SELECT ON dw\.\*) TO ", item) and "WITH GRANT OPTION" not in item for item in grants)
                else:
                    assert any("CREATE" in item and " ON meta.* TO " in item for item in grants)
                print(f"{label}: login OK; grants checked")
        finally:
            connection.close()


if __name__ == "__main__":
    try:
        asyncio.run(verify())
    except Exception as error:
        raise SystemExit(f"Database check failed ({type(error).__name__}); credentials were not displayed.") from None
