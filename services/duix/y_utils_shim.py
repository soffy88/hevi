"""
Y_utils logger and config shim for Duix container.

This replaces the broken .so file (y_utils/logger.cpython-38-x86_64-linux-gnu.so)
that exports create_logger() but not logger.
"""
import logging

# Create the logger instance that app.py expects
logger = logging.getLogger('duix')
logger.setLevel(logging.INFO)

# Add a handler if none exists
if not logger.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    logger.addHandler(handler)


def create_logger(name=None):
    """Create a logger with the expected interface."""
    if name:
        return logging.getLogger(name)
    return logger


class GlobalConfig:
    """Global configuration - expected by app.py."""
    server_ip = "0.0.0.0"
    server_port = 8383
    temp_dir = "/code/data/temp"
    result_dir = "/code/data/result"
    
    @classmethod
    def instance(cls):
        return cls()


__all__ = ['logger', 'create_logger', 'GlobalConfig']
