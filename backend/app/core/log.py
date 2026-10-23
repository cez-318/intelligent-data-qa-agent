"""Default-deny logging: legacy callers may interpolate sensitive values."""
import sys
from loguru import logger
from app.core.context import request_id_ctx_var


def safe_record(record):
    record["message"] = f"event={record['function']} level={record['level'].name}"
    record["exception"] = None
    record["extra"] = {"request_id": str(request_id_ctx_var.get())}


logger.remove()
logger = logger.patch(safe_record)
logger.add(sys.stderr, format="{time:YYYY-MM-DD HH:mm:ss} | {extra[request_id]} | {name}:{line} | {message}",
           backtrace=False, diagnose=False)
