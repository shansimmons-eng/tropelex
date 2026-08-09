"""
Safety gating primitives — the #54 counterpart to core/triggers/tag_gate.py.

This is the start of the `core/safety/` extraction the wishlist proposes,
scoped deliberately: it houses the new required-safety-metadata gate, not
a wholesale relocation of server.py's existing inline safety block
(SafetyMetadata, DecisionCreate, _auto_classify_safety, and the dozen or
so safety-report endpoints downstream of them). That block is actively
load-bearing across a lot of server.py; moving all of it in the same pass
as adding new gating logic would risk exactly the kind of wide, hard-to-
review change this project has been deliberately avoiding. It stays a
fast-follow, not a blocker for the gate itself.
"""

from core.safety.gate import SafetyMetadataRequiredError, require_safety_metadata

__all__ = ["SafetyMetadataRequiredError", "require_safety_metadata"]
