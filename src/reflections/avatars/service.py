from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.avatars.a1111 import get_a1111_client
from reflections.avatars.diffusers_sdxl import DiffusersSDXLException, get_diffusers_sdxl_client
from reflections.avatars.repository import AvatarsRepository
from reflections.auth.models import Avatar, User
from reflections.core.settings import settings


@dataclass
class AvatarsService:
    repo: AvatarsRepository

    @classmethod
    def create(cls) -> "AvatarsService":
        return cls(repo=AvatarsRepository())

    async def list_avatars(self, session: AsyncSession, *, user: User) -> tuple[list[Avatar], UUID | None]:
        items = await self.repo.list_for_user(session, user_id=user.id)
        return items, user.active_avatar_id

    async def create_avatar(
        self,
        session: AsyncSession,
        *,
        user: User,
        name: str,
        persona_prompt: str | None,
        image_url: str | None,
        voice_config: dict | None,
        set_active: bool,
    ) -> Avatar:
        a = await self.repo.create_for_user(
            session,
            user_id=user.id,
            name=name,
            persona_prompt=persona_prompt,
            image_url=image_url,
            voice_config=voice_config,
        )
        if set_active:
            await self.repo.set_active_avatar(session, user_id=user.id, avatar_id=a.id)
            user.active_avatar_id = a.id
        await session.commit()
        return a

    async def update_avatar(
        self,
        session: AsyncSession,
        *,
        user: User,
        avatar_id: UUID,
        name: str | None,
        persona_prompt: str | None,
        image_url: str | None,
        voice_config: dict | None,
    ) -> Avatar | None:
        a = await self.repo.update_for_user(
            session,
            user_id=user.id,
            avatar_id=avatar_id,
            name=name,
            persona_prompt=persona_prompt,
            image_url=image_url,
            voice_config=voice_config,
        )
        await session.commit()
        return a

    async def delete_avatar(
        self, session: AsyncSession, *, user: User, avatar_id: UUID
    ) -> int:
        deleted = await self.repo.delete_for_user(
            session, user_id=user.id, avatar_id=avatar_id
        )
        # If we deleted the active avatar, clear it.
        if user.active_avatar_id == avatar_id:
            await self.repo.set_active_avatar(session, user_id=user.id, avatar_id=None)
            user.active_avatar_id = None
        await session.commit()
        return deleted

    async def set_active(
        self, session: AsyncSession, *, user: User, avatar_id: UUID | None
    ) -> None:
        if avatar_id is not None:
            a = await self.repo.get_for_user(session, user_id=user.id, avatar_id=avatar_id)
            if a is None:
                # Ignore invalid ids (client may be stale); keep existing active avatar.
                return
        await self.repo.set_active_avatar(session, user_id=user.id, avatar_id=avatar_id)
        user.active_avatar_id = avatar_id
        await session.commit()

    async def generate_image_a1111(
        self,
        session: AsyncSession,
        *,
        user: User,
        avatar_id: UUID,
        prompt: str,
        negative_prompt: str | None,
        width: int,
        height: int,
        steps: int,
        cfg_scale: float,
        sampler_name: str | None,
        seed: int,
    ) -> str:
        a = await self.repo.get_for_user(session, user_id=user.id, avatar_id=avatar_id)
        if a is None:
            raise ValueError("avatar_not_found")

        payload: dict = {
            "prompt": prompt,
            "width": int(width),
            "height": int(height),
            "steps": int(steps),
            "cfg_scale": float(cfg_scale),
            "seed": int(seed),
        }
        if negative_prompt:
            payload["negative_prompt"] = negative_prompt
        if sampler_name:
            payload["sampler_name"] = sampler_name

        image_url = await get_a1111_client().txt2img(payload)
        updated = await self.repo.set_image_url(
            session, user_id=user.id, avatar_id=avatar_id, image_url=image_url
        )
        if updated is None:
            raise ValueError("avatar_not_found")
        await session.commit()
        return image_url

    async def generate_image_diffusers_sdxl(
        self,
        session: AsyncSession,
        *,
        user: User,
        avatar_id: UUID,
        prompt: str,
        negative_prompt: str | None,
        width: int,
        height: int,
        steps: int,
        cfg_scale: float,
        seed: int,
    ) -> str:
        a = await self.repo.get_for_user(session, user_id=user.id, avatar_id=avatar_id)
        if a is None:
            raise ValueError("avatar_not_found")

        try:
            image_url = await get_diffusers_sdxl_client().txt2img(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                steps=steps,
                cfg_scale=cfg_scale,
                seed=seed,
            )
        except DiffusersSDXLException:
            raise
        updated = await self.repo.set_image_url(
            session, user_id=user.id, avatar_id=avatar_id, image_url=image_url
        )
        if updated is None:
            raise ValueError("avatar_not_found")
        await session.commit()
        return image_url

    async def generate_image(
        self,
        session: AsyncSession,
        *,
        user: User,
        avatar_id: UUID,
        prompt: str,
        negative_prompt: str | None,
        width: int,
        height: int,
        steps: int,
        cfg_scale: float,
        sampler_name: str | None,
        seed: int,
        engine: str | None = None,
    ) -> str:
        chosen = (engine or settings.AVATAR_IMAGE_ENGINE or "a1111").lower().strip()
        if chosen in {"diffusers_sdxl", "diffusers", "sdxl"}:
            return await self.generate_image_diffusers_sdxl(
                session,
                user=user,
                avatar_id=avatar_id,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                steps=steps,
                cfg_scale=cfg_scale,
                seed=seed,
            )
        if chosen in {"a1111", "automatic1111"}:
            return await self.generate_image_a1111(
                session,
                user=user,
                avatar_id=avatar_id,
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=width,
                height=height,
                steps=steps,
                cfg_scale=cfg_scale,
                sampler_name=sampler_name,
                seed=seed,
            )
        raise ValueError("engine_not_supported")


