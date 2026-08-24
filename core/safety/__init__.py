"""
Safety gating primitives — the #54 counterpart to core/triggers/tag_gate.py.

Wishlist #73's fast-follow: SafetyMetadata and the auto-classifier
(classifier.py) have now moved out of server.py's inline block. DecisionCreate
and the safety-report endpoints downstream of them (get_safety_stats,
get_safety_dashboard, get_safety_trend, submit_safety_review, run_safety_check,
get_safety_envelope, and their private helpers — a genuinely larger surface
than the original "~150-line block" estimate suggested, confirmed by grep
before touching anything) are still in server.py, deliberately deferred
again rather than folded into this pass — moving a dozen interdependent
endpoints in the same change as the classifier extraction would be exactly
the wide, hard-to-review change this project avoids. Real fast-follow, not
a blocker, same as last time.
"""

from core.safety.classifier import SafetyMetadata, auto_classify_safety
from core.safety.gate import SafetyMetadataRequiredError, require_safety_metadata

__all__ = [
    "SafetyMetadata", "SafetyMetadataRequiredError",
    "auto_classify_safety", "require_safety_metadata",
]
