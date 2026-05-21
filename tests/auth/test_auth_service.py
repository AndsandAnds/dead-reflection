from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from uuid import UUID

import pytest  # type: ignore[import-not-found]

from reflections.auth.models import User
from reflections.auth.service import AuthService


@dataclass
class FakeRepo:
    """In-memory repository that exercises AuthService without a real Postgres."""

    user_count: int = 0
    inserted: list[User] = field(default_factory=list)
    session_inserts: int = 0

    async def get_user_by_email(self, _session, *, email: str) -> User | None:
        for u in self.inserted:
            if u.email == email.lower():
                return u
        return None

    async def get_user_by_id(self, _session, *, user_id: UUID) -> User | None:
        for u in self.inserted:
            if u.id == user_id:
                return u
        return None

    async def count_users(self, _session) -> int:
        return self.user_count

    async def insert_user(
        self,
        _session,
        *,
        user_id: UUID,
        email: str,
        name: str,
        password_hash: str,
        is_admin: bool = False,
    ) -> User:
        user = User(
            id=user_id,
            email=email.lower(),
            name=name.strip(),
            password_hash=password_hash,
            is_admin=is_admin,
            created_at=dt.datetime.now(dt.UTC),
        )
        self.inserted.append(user)
        self.user_count += 1
        return user

    async def insert_session(self, _session, **_kwargs) -> None:
        self.session_inserts += 1


class FakeSession:
    """AsyncSession stand-in for service-level tests."""

    async def refresh(self, _instance):
        return None

    async def commit(self):
        return None


@pytest.mark.anyio
async def test_first_signup_is_admin() -> None:
    repo = FakeRepo(user_count=0)
    svc = AuthService(repo=repo)  # type: ignore[arg-type]

    user, token = await svc.signup(
        FakeSession(),  # type: ignore[arg-type]
        email="first@example.com",
        name="First",
        password="hunter2hunter2",
    )

    assert user.is_admin is True
    assert token


@pytest.mark.anyio
async def test_second_signup_is_not_admin() -> None:
    repo = FakeRepo(user_count=1)  # pretend one user already exists
    svc = AuthService(repo=repo)  # type: ignore[arg-type]

    user, _token = await svc.signup(
        FakeSession(),  # type: ignore[arg-type]
        email="second@example.com",
        name="Second",
        password="hunter2hunter2",
    )

    assert user.is_admin is False
