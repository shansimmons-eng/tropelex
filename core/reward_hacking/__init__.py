"""
Reward-hacking signals — detectors that need no recorded decision at all,
just a structural pattern in the diff itself (wishlist #107).

Distinct in kind from core/ghost/: Ghost compares a diff against a
specific decision's text. These detectors look at the diff alone.
"""
