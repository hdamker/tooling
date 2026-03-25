# Validation engine adapters.
# Each adapter invokes its engine and normalizes output to the common
# findings model (see schemas/findings-schema.yaml).

from .spectral_adapter import run_spectral_engine

__all__ = ["run_spectral_engine"]
