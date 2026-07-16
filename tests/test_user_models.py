"""Unit tests for user models — Role, permissions, and UserStore."""

import pytest
from datetime import datetime, timezone

from core.auth.models import Role, User, UserStore, has_permission, role_has_at_least


# ---------------------------------------------------------------------------
# Role hierarchy
# ---------------------------------------------------------------------------

class TestRoleHierarchy:
    """role_has_at_least compares roles by privilege level."""

    def test_admin_at_least_admin(self):
        assert role_has_at_least(Role.ADMIN, Role.ADMIN) is True

    def test_admin_at_least_user(self):
        assert role_has_at_least(Role.ADMIN, Role.USER) is True

    def test_user_not_at_least_admin(self):
        assert role_has_at_least(Role.USER, Role.ADMIN) is False

    def test_viewer_at_least_viewer(self):
        assert role_has_at_least(Role.VIEWER, Role.VIEWER) is True

    def test_viewer_not_at_least_user(self):
        assert role_has_at_least(Role.VIEWER, Role.USER) is False


# ---------------------------------------------------------------------------
# Permission checks
# ---------------------------------------------------------------------------

class TestHasPermission:
    """has_permission is a pure function over User + permission string."""

    def test_admin_has_all_permissions(self):
        admin = User(role=Role.ADMIN)
        for perm in ("read", "write", "delete", "manage_users"):
            assert has_permission(admin, perm) is True

    def test_user_has_read_write(self):
        user = User(role=Role.USER)
        assert has_permission(user, "read") is True
        assert has_permission(user, "write") is True
        assert has_permission(user, "delete") is False
        assert has_permission(user, "manage_users") is False

    def test_viewer_has_read_only(self):
        viewer = User(role=Role.VIEWER)
        assert has_permission(viewer, "read") is True
        assert has_permission(viewer, "write") is False

    def test_inactive_user_has_no_permissions(self):
        inactive = User(role=Role.ADMIN, is_active=False)
        assert has_permission(inactive, "read") is False

    def test_unknown_permission_returns_false(self):
        user = User(role=Role.ADMIN)
        assert has_permission(user, "nonexistent") is False


# ---------------------------------------------------------------------------
# User dataclass
# ---------------------------------------------------------------------------

class TestUser:
    """User is a frozen dataclass with sensible defaults."""

    def test_defaults(self):
        u = User()
        assert isinstance(u.user_id, str) and len(u.user_id) > 0
        assert u.role == Role.VIEWER
        assert u.is_active is True

    def test_frozen(self):
        u = User()
        with pytest.raises(AttributeError):
            u.role = Role.ADMIN  # type: ignore[misc]

    def test_custom_fields(self):
        u = User(user_id="abc", username="alice", email="a@b.com", role=Role.ADMIN)
        assert u.user_id == "abc"
        assert u.username == "alice"
        assert u.role == Role.ADMIN


# ---------------------------------------------------------------------------
# UserStore CRUD
# ---------------------------------------------------------------------------

class TestUserStore:
    """In-memory CRUD operations."""

    def setup_method(self):
        self.store = UserStore()

    def _make_user(self, uid: str = "u1") -> User:
        return User(user_id=uid, username=f"user-{uid}")

    # --- create ---

    def test_create_and_get(self):
        user = self._make_user()
        self.store.create(user)
        assert self.store.get("u1") == user

    def test_create_duplicate_raises(self):
        self.store.create(self._make_user())
        with pytest.raises(ValueError, match="already exists"):
            self.store.create(self._make_user())

    # --- get ---

    def test_get_missing_returns_none(self):
        assert self.store.get("nope") is None

    # --- update ---

    def test_update_username(self):
        self.store.create(self._make_user())
        updated = self.store.update("u1", username="bob")
        assert updated is not None
        assert updated.username == "bob"
        assert updated.user_id == "u1"  # unchanged

    def test_update_role(self):
        self.store.create(self._make_user())
        updated = self.store.update("u1", role=Role.ADMIN)
        assert updated.role == Role.ADMIN

    def test_update_missing_returns_none(self):
        assert self.store.update("nope", username="x") is None

    # --- delete ---

    def test_delete_existing(self):
        self.store.create(self._make_user())
        assert self.store.delete("u1") is True
        assert self.store.get("u1") is None

    def test_delete_missing_returns_false(self):
        assert self.store.delete("nope") is False

    # --- list_all ---

    def test_list_all(self):
        self.store.create(self._make_user("a"))
        self.store.create(self._make_user("b"))
        result = self.store.list_all()
        assert len(result) == 2
        ids = {u.user_id for u in result}
        assert ids == {"a", "b"}
