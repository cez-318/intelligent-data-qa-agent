import asyncio
from typing import Optional

from sqlalchemy import text, URL
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine, async_sessionmaker

from app.conf.app_config import DBConfig, app_config
from improved.db_logging import protect_driver_logs


class MysqlClientManager:
    def __init__(self, db_config: DBConfig):
        self.db_config = db_config
        self.engine: Optional[AsyncEngine] = None
        self.session_factory = None

    def _get_url(self):
        return URL.create("mysql+asyncmy", username=self.db_config.user, password=self.db_config.password,
                          host=self.db_config.host, port=self.db_config.port, database=self.db_config.database,
                          query={"charset": "utf8mb4"})

    def init(self):
        protect_driver_logs()
        self.engine = create_async_engine(url=self._get_url(),
                                          pool_size=10,
                                          pool_pre_ping=True)
        self.session_factory = async_sessionmaker(self.engine,
                                                  autoflush=True,
                                                  expire_on_commit=False,
                                                  autobegin=True)

    async def close(self):
        await self.engine.dispose()


dw_mysql_client_manager = MysqlClientManager(app_config.db_dw)
meta_mysql_client_manager = MysqlClientManager(app_config.db_meta)

if __name__ == '__main__':
    meta_mysql_client_manager.init()


    async def test():
        async with meta_mysql_client_manager.session_factory() as session:
            result = await session.execute(text("select * from table_info limit 10"))
            rows = result.fetchall()
            print(rows)


    asyncio.run(test())
