"""MySQL EXPLAIN notes can contain SQL with bound values; never log that text."""
import logging


class DriverLogRedaction(logging.Filter):
    def filter(self, record):
        record.msg = "database_driver_warning" if record.levelno >= logging.WARNING else "database_driver_event"
        record.args = ()
        record.exc_info = record.exc_text = record.stack_info = None
        return True


def protect_driver_logs():
    for name in ("asyncmy", "asyncmy.cursors", "asyncmy.connection"):
        logger = logging.getLogger(name)
        if not any(isinstance(item, DriverLogRedaction) for item in logger.filters):
            logger.addFilter(DriverLogRedaction())
