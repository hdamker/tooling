"""
CAMARA Validator - Modular API validation tool for CAMARA specifications.

This package provides comprehensive validation of CAMARA API specifications
against Commonalities requirements using a rule-based architecture.
"""

import logging
import sys

from camara_validator.__version__ import __author__, __description__, __version__

# Public API exports
__all__ = [
    "__version__",
    "__author__",
    "__description__",
]

# Create logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Create console handler with formatting
handler = logging.StreamHandler()
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# Version check
if sys.version_info < (3, 8):
    raise RuntimeError("CAMARA Validator requires Python 3.8 or higher")
