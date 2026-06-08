import sys
import logging
from logging.handlers import RotatingFileHandler

class AdvancedLogger:
    def __init__(self, name="AppLogger", log_file="app.log"):
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)

        # Prevent adding duplicate handlers if the logger instance already exists
        if not self.logger.handlers:
            formatter = logging.Formatter(
                '[%(asctime)s] %(levelname)s [%(name)s.%(funcName)s:%(lineno)d] %(message)s'
            )

            # 1. Fix Console Stream Handler for Windows Terminal Output
            # We explicitly override the underlying stream layout to enforce UTF-8 wrapping
            sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None
            console_handler = logging.StreamHandler(sys.stdout)
            console_handler.setFormatter(formatter)
            self.logger.addHandler(console_handler)

            # 2. Fix Persistent File Handler Encoding
            # Added explicit encoding="utf-8" to the RotatingFileHandler to handle markdown/emojis safely
            file_handler = RotatingFileHandler(
                log_file, maxBytes=5*1024*1024, backupCount=5, encoding="utf-8"
            )
            file_handler.setFormatter(formatter)
            self.logger.addHandler(file_handler)

    def info(self, message: str = ""):
        """Standard informational logging."""
        self.logger.info(message)

    def error(self, function_name: str = "", error: Exception = ""):
        """
        Safe logging for errors. 
        Captures the function name and the full traceback for debugging.
        """
        error_msg = f"Error in {function_name}: {str(error)}"
        self.logger.error(error_msg, exc_info=True)

    def warning(self, message: str = ""):
        """Log unexpected events that aren't necessarily breaking the app."""
        self.logger.warning(message)

    def critical(self, message: str = ""):
        """Log failures that require immediate attention."""
        self.logger.critical(f"FATAL: {message}")

# Instantiate the structured singleton object for imports across your workspace files
logger = AdvancedLogger()