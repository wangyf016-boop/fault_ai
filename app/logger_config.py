import logging
import sys
from contextvars import ContextVar

# Context variable to hold the request ID
request_id_var: ContextVar[str] = ContextVar("request_id", default="N/A")


LOG_FORMAT = (
    "%(asctime)s.%(msecs)03d | %(levelname)s | %(name)s | "
    "req=%(request_id)s | %(filename)s:%(lineno)d | %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

class RequestIdFilter(logging.Filter):
    """
    A logging filter that injects the request_id from a context variable.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "N/A"
        return True


def setup_logging():
    """
    Set up the application's logging configuration.
    """
    # Get the root logger
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)  # Set the default level

    # Remove existing handlers to avoid duplicates
    if logger.hasHandlers():
        logger.handlers.clear()

    # Create a handler for console output
    handler = logging.StreamHandler(sys.stdout)

    # Add our custom filter to the handler
    handler.addFilter(RequestIdFilter())

    # Create a formatter
    formatter = logging.Formatter(LOG_FORMAT, DATE_FORMAT)

    # Set the formatter for the handler
    handler.setFormatter(formatter)

    # Add the handler to the root logger
    logger.addHandler(handler)

    # Configure logging for key libraries to be less verbose if needed
    logging.getLogger("uvicorn").setLevel(logging.INFO)
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.INFO)
    logging.getLogger("httpx").setLevel(logging.INFO)

    logger.info("Logging setup complete.")
