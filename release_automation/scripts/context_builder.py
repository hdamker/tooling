"""
Context builder for CAMARA release automation.

Provides the build_context() function — the single entry point for
constructing the unified context used by bot message templates,
issue sync, and other consumers.
See technical-architecture.md Section 2.9 for the authoritative schema.
"""

from typing import Any, Dict

from .bot_context import BotContext


def build_context(**kwargs: Any) -> Dict[str, Any]:
    """
    Construct a unified context dict for template rendering and issue updates.

    Accepts any keyword arguments matching BotContext fields. Unknown
    kwargs are silently ignored (defensive — workflow may pass extra data).

    Guarantees:
    1. Output dict contains ALL keys from BotContext schema
    2. No None values — every field has a type-appropriate default
    3. Boolean flags derived automatically from string fields

    Returns:
        Dict with all BotContext fields, ready for pystache rendering.
    """
    # Filter to only known BotContext fields
    known_fields = {k for k in BotContext.__dataclass_fields__}
    filtered = {k: v for k, v in kwargs.items() if k in known_fields}

    ctx = BotContext(**filtered)
    ctx.derive_flags()
    return ctx.to_dict()
