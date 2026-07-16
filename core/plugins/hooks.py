"""
Hook registry for Tropelex plugins.

Manages before/after hooks that plugins can register against named events.
Hooks receive a context dict; before-hooks may modify it, after-hooks
process results.  All public helpers are pure where possible.

Supported hook names:
    pre_save, post_save, pre_delete, post_delete, pre_sync, post_sync
"""

import copy
import inspect
import logging
from collections import defaultdict
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

SUPPORTED_HOOKS = frozenset({
    "pre_save",
    "post_save",
    "pre_delete",
    "post_delete",
    "pre_sync",
    "post_sync",
})

VALID_HOOK_TYPES = frozenset({"before", "after"})


class HookRegistry:
    """Central registry that stores and executes plugin hooks.

    Each *hook_name* maps to two buckets: ``before`` and ``after``.
    Callbacks are executed in registration order.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, dict[str, list[Callable]]] = defaultdict(
            lambda: {"before": [], "after": []}
        )

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_hook(
        self,
        hook_name: str,
        callback: Callable,
        hook_type: str = "before",
    ) -> None:
        """Register *callback* for *hook_name*.

        Args:
            hook_name: Event name (e.g. ``pre_save``).
            callback: Awaitable or sync callable ``(context: dict) -> dict``.
            hook_type: ``"before"`` or ``"after"``.

        Raises:
            ValueError: If *hook_type* is not recognised.
        """
        _validate_hook_type(hook_type)
        _validate_callable(callback)
        self._hooks[hook_name][hook_type].append(callback)
        logger.debug(
            "Registered %s hook '%s': %s",
            hook_type,
            hook_name,
            _callable_name(callback),
        )

    def unregister_hook(
        self,
        hook_name: str,
        callback: Callable,
    ) -> None:
        """Remove *callback* from both before/after buckets for *hook_name*.

        Silently succeeds if the callback was never registered.

        Raises:
            ValueError: If *callback* is not found in any bucket.
        """
        removed = False
        for htype in ("before", "after"):
            bucket = self._hooks[hook_name][htype]
            try:
                bucket.remove(callback)
                removed = True
            except ValueError:
                continue

        if not removed:
            raise ValueError(
                f"Callback {_callable_name(callback)} not found "
                f"for hook '{hook_name}'"
            )

        logger.debug(
            "Unregistered hook '%s': %s",
            hook_name,
            _callable_name(callback),
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute_hooks(
        self,
        hook_name: str,
        context: dict[str, Any],
        hook_type: str = "before",
    ) -> dict[str, Any]:
        """Execute all registered callbacks for *hook_name*.

        Before-hooks: each receives the current context and may return a
        (possibly modified) dict that becomes the next hook's input.
        After-hooks: same contract, operating on post-action results.

        Args:
            hook_name: Event name.
            context: Mutable data dict passed through the chain.
            hook_type: ``"before"`` or ``"after"``.

        Returns:
            The (possibly modified) context dict after all hooks ran.
        """
        _validate_hook_type(hook_type)
        active = self._hooks[hook_name][hook_type]

        result = copy.deepcopy(context)

        for callback in active:
            result = await _invoke(callback, result)

        return result

    # ------------------------------------------------------------------
    # Introspection (useful for tests / plugin manifests)
    # ------------------------------------------------------------------

    def get_hooks(self, hook_name: str) -> dict[str, list[Callable]]:
        """Return a *copy* of registered callbacks for *hook_name*."""
        return copy.deepcopy(self._hooks[hook_name])

    def has_hooks(self, hook_name: str) -> bool:
        """Return ``True`` if any callbacks are registered for *hook_name*."""
        return any(
            self._hooks[hook_name][t] for t in ("before", "after")
        )


# ------------------------------------------------------------------
# Pure helpers (module-level)
# ------------------------------------------------------------------


def _validate_hook_type(hook_type: str) -> None:
    """Raise ``ValueError`` if *hook_type* is not ``"before"`` or ``"after"``."""
    if hook_type not in VALID_HOOK_TYPES:
        raise ValueError(
            f"Invalid hook_type '{hook_type}'; expected 'before' or 'after'"
        )


def _validate_callable(callback: Callable) -> None:
    """Raise ``TypeError`` if *callback* is not callable."""
    if not callable(callback):
        raise TypeError(f"Expected a callable, got {type(callback).__name__}")


def _callable_name(callback: Callable) -> str:
    """Return a human-readable name for *callback*."""
    return getattr(callback, "__name__", None) or getattr(
        callback, "__qualname__", str(callback)
    )


async def _invoke(callback: Callable, context: dict[str, Any]) -> dict[str, Any]:
    """Call *callback* with *context*, awaiting if it is a coroutine function.

    Returns the callback's result, falling back to the original *context*
    if the callback returns ``None``.
    """
    if inspect.iscoroutinefunction(callback):
        raw = await callback(context)
    else:
        raw = callback(context)

    return raw if raw is not None else context
