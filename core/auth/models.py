"""User model, role system, and permission checks.

Pure functions for authorization logic. Role hierarchy enforces
least-privilege: ADMIN > USER > VIEWER. UserStore provides
in-memory CRUD with no external dependencies.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4


class Role(Enum):
    """Authorization roles with implicit hierarchy (higher = more privileged)."""

    VIEWER = "viewer"
    USER = "user"
    ADMIN = "admin"


# Role hierarchy: higher index = more privilege.
_ROLE_RANK: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.USER: 1,
    Role.ADMIN: 2,
}

# Permission definitions per role.
_ROLE_PERMISSIONS: dict[Role, set[str]] = {
    Role.VIEWER: {"read"},
    Role.USER: {"read", "write"},
    Role.ADMIN: {"read", "write", "delete", "manage_users"},
}


@dataclass(frozen=True)
class User:
    """Immutable user record."""

    user_id: str = field(default_factory=lambda: uuid4().hex)
    username: str = ""
    email: str = ""
    role: Role = Role.VIEWER
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    is_active: bool = True


def has_permission(user: User, permission: str) -> bool:
    """Check whether *user* holds *permission* based on their role.

    Pure function — no side effects, deterministic output for same input.
    """
    if not user.is_active:
        return False
    return permission in _ROLE_PERMISSIONS.get(user.role, set())


def role_has_at_least(role: Role, minimum: Role) -> bool:
    """Return True when *role* meets or exceeds *minimum* in hierarchy."""
    return _ROLE_RANK.get(role, 0) >= _ROLE_RANK.get(minimum, 0)


class UserStore:
    """In-memory user storage with CRUD operations.

    Not thread-safe — intended for single-process usage or
    protected by external synchronisation when needed.
    """

    def __init__(self) -> None:
        self._users: dict[str, User] = {}

    def create(self, user: User) -> User:
        """Insert a new user. Raises ValueError on duplicate user_id."""
        if user.user_id in self._users:
            raise ValueError(f"User already exists: {user.user_id}")
        self._users[user.user_id] = user
        return user

    def get(self, user_id: str) -> Optional[User]:
        """Return user by ID, or None if not found."""
        return self._users.get(user_id)

    def update(self, user_id: str, **changes) -> Optional[User]:
        """Return a new User with *changes* applied, or None if not found.

        Because User is frozen, we construct a replacement instance.
        """
        existing = self._users.get(user_id)
        if existing is None:
            return None
        updated = User(
            user_id=existing.user_id,
            username=changes.get("username", existing.username),
            email=changes.get("email", existing.email),
            role=changes.get("role", existing.role),
            created_at=existing.created_at,
            is_active=changes.get("is_active", existing.is_active),
        )
        self._users[user_id] = updated
        return updated

    def delete(self, user_id: str) -> bool:
        """Remove user by ID. Returns True if removed, False if absent."""
        return self._users.pop(user_id, None) is not None

    def list_all(self) -> list[User]:
        """Return all stored users."""
        return list(self._users.values())
