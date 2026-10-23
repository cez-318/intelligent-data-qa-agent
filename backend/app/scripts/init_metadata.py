"""Create missing original ORM tables in the explicitly configured metadata DB."""
import argparse
import asyncio
from app.clients.mysql_client_manager import meta_mysql_client_manager
from app.models.base import Base
from app.models import table_info_mysql, column_info_mysql, metric_info_mysql, column_metric_mysql


async def initialize():
    meta_mysql_client_manager.init()
    try:
        async with meta_mysql_client_manager.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
    finally:
        await meta_mysql_client_manager.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-create-tables", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(initialize())
