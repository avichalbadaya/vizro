import logging
import os

from ._vizro import Vizro

__all__ = ["Vizro"]

__version__ = "0.1.6.dev0"

logging.basicConfig(level=os.getenv("VIZRO_LOG_LEVEL", "WARNING"))
