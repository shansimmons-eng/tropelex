"""Tests for core.plugins.hooks — hook registration, unregistration, and execution."""

import pytest

from core.plugins.hooks import (
    HookRegistry,
    SUPPORTED_HOOKS,
    VALID_HOOK_TYPES,
    _callable_name,
    _invoke,
    _validate_callable,
    _validate_hook_type,
)


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


class TestValidateHookType:
    def test_before_passes(self):
        _validate_hook_type("before")

    def test_after_passes(self):
        _validate_hook_type("after")

    def test_raises_on_invalid(self):
        with pytest.raises(ValueError, match="Invalid hook_type"):
            _validate_hook_type("during")


class TestValidateCallable:
    def test_accepts_function(self):
        _validate_callable(lambda x: x)

    def test_raises_on_non_callable(self):
        with pytest.raises(TypeError, match="Expected a callable"):
            _validate_callable("not a function")


class TestCallableName:
    def test_prefers_qualname(self):
        def my_func():
            pass

        assert _callable_name(my_func) == "my_func"

    def test_falls_back_to_str(self):
        sentinel = object()
        assert _callable_name(sentinel) == str(sentinel)


class TestInvoke:
    @pytest.mark.asyncio
    async def test_sync_callback(self):
        result = await _invoke(lambda ctx: {"added": True, **ctx}, {"x": 1})
        assert result == {"added": True, "x": 1}

    @pytest.mark.asyncio
    async def test_async_callback(self):
        async def enrich(ctx):
            return {**ctx, "async": True}

        result = await _invoke(enrich, {"x": 1})
        assert result == {"x": 1, "async": True}

    @pytest.mark.asyncio
    async def test_none_return_keeps_original(self):
        result = await _invoke(lambda ctx: None, {"keep": True})
        assert result == {"keep": True}


# ---------------------------------------------------------------------------
# HookRegistry
# ---------------------------------------------------------------------------


def _noop(ctx):
    return ctx


def _tag(tag_name):
    """Return a hook that stamps *tag_name* into the context."""
    def _hook(ctx):
        ctx = {**ctx, tag_name: True}
        return ctx
    _hook.__qualname__ = f"_tag({tag_name})"
    return _hook


class TestRegisterHook:
    def test_register_and_retrieve(self):
        reg = HookRegistry()
        reg.register_hook("pre_save", _noop)
        hooks = reg.get_hooks("pre_save")
        assert _noop in hooks["before"]

    def test_register_after_hook(self):
        reg = HookRegistry()
        reg.register_hook("post_save", _noop, hook_type="after")
        hooks = reg.get_hooks("post_save")
        assert _noop in hooks["after"]

    def test_register_rejects_bad_type(self):
        reg = HookRegistry()
        with pytest.raises(ValueError):
            reg.register_hook("pre_save", _noop, hook_type="during")

    def test_register_rejects_non_callable(self):
        reg = HookRegistry()
        with pytest.raises(TypeError):
            reg.register_hook("pre_save", 42)

    def test_multiple_callbacks_same_hook(self):
        reg = HookRegistry()
        f1 = lambda c: c
        f2 = lambda c: c
        reg.register_hook("pre_save", f1)
        reg.register_hook("pre_save", f2)
        assert len(reg.get_hooks("pre_save")["before"]) == 2


class TestUnregisterHook:
    def test_unregister_existing(self):
        reg = HookRegistry()
        reg.register_hook("pre_save", _noop)
        reg.unregister_hook("pre_save", _noop)
        assert reg.get_hooks("pre_save")["before"] == []

    def test_unregister_from_after_bucket(self):
        reg = HookRegistry()
        reg.register_hook("post_sync", _noop, hook_type="after")
        reg.unregister_hook("post_sync", _noop)
        assert reg.get_hooks("post_sync")["after"] == []

    def test_unregister_nonexistent_raises(self):
        reg = HookRegistry()
        with pytest.raises(ValueError, match="not found"):
            reg.unregister_hook("pre_save", _noop)

    def test_unregister_only_removes_target(self):
        reg = HookRegistry()
        f1 = lambda c: c
        f2 = lambda c: c
        reg.register_hook("pre_save", f1)
        reg.register_hook("pre_save", f2)
        reg.unregister_hook("pre_save", f1)
        assert len(reg.get_hooks("pre_save")["before"]) == 1


class TestHasHooks:
    def test_empty_registry(self):
        reg = HookRegistry()
        assert reg.has_hooks("pre_save") is False

    def test_after_registration(self):
        reg = HookRegistry()
        reg.register_hook("pre_save", _noop)
        assert reg.has_hooks("pre_save") is True


# ---------------------------------------------------------------------------
# execute_hooks
# ---------------------------------------------------------------------------


class TestExecuteHooks:
    @pytest.mark.asyncio
    async def test_no_hooks_returns_copy(self):
        reg = HookRegistry()
        ctx = {"key": "value"}
        result = await reg.execute_hooks("pre_save", ctx)
        assert result == {"key": "value"}
        assert result is not ctx  # deepcopy

    @pytest.mark.asyncio
    async def test_single_before_hook_modifies_context(self):
        reg = HookRegistry()
        reg.register_hook("pre_save", _tag("injected"))
        result = await reg.execute_hooks("pre_save", {"x": 1})
        assert result["injected"] is True
        assert result["x"] == 1

    @pytest.mark.asyncio
    async def test_chained_before_hooks(self):
        reg = HookRegistry()
        reg.register_hook("pre_save", _tag("first"))
        reg.register_hook("pre_save", _tag("second"))
        result = await reg.execute_hooks("pre_save", {})
        assert result["first"] is True
        assert result["second"] is True

    @pytest.mark.asyncio
    async def test_after_hooks_run(self):
        reg = HookRegistry()
        reg.register_hook("post_save", _tag("processed"), hook_type="after")
        result = await reg.execute_hooks("post_save", {}, hook_type="after")
        assert result["processed"] is True

    @pytest.mark.asyncio
    async def test_async_hook_modifies_context(self):
        reg = HookRegistry()

        async def async_enrich(ctx):
            return {**ctx, "async_done": True}

        reg.register_hook("pre_sync", async_enrich)
        result = await reg.execute_hooks("pre_sync", {})
        assert result["async_done"] is True

    @pytest.mark.asyncio
    async def test_invalid_hook_type_raises(self):
        reg = HookRegistry()
        with pytest.raises(ValueError, match="Invalid hook_type"):
            await reg.execute_hooks("pre_save", {}, hook_type="during")

    @pytest.mark.asyncio
    async def test_original_context_not_mutated(self):
        reg = HookRegistry()
        reg.register_hook("pre_save", _tag("added"))
        original = {"original": True}
        await reg.execute_hooks("pre_save", original)
        assert "added" not in original

    @pytest.mark.asyncio
    async def test_integration_all_supported_hooks(self):
        """Every SUPPORTED_HOOKS name should be registerable and executable."""
        reg = HookRegistry()
        for name in SUPPORTED_HOOKS:
            reg.register_hook(name, _tag(name))
        for name in SUPPORTED_HOOKS:
            result = await reg.execute_hooks(name, {})
            assert result[name] is True
