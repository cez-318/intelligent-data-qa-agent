import logging
import pytest


@pytest.mark.parametrize("name", ["asyncmy", "asyncmy.cursors"])
def test_driver_warning_content_is_redacted(caplog, name):
    from improved.db_logging import protect_driver_logs
    protect_driver_logs()
    with caplog.at_level(logging.WARNING, logger=name):
        logging.getLogger(name).warning("SELECT secret FROM customer WHERE email=%s", "private@example.invalid")
    assert "private@example.invalid" not in caplog.text
    assert "SELECT secret" not in caplog.text
    assert "database_driver_warning" in caplog.text
