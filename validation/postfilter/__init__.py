"""Post-filter pipeline.

Applies rule metadata lookup, applicability evaluation, conditional
severity resolution, and profile-based blocking decisions.
"""

from .engine import PostFilterResult, run_post_filter

__all__ = ["PostFilterResult", "run_post_filter"]
