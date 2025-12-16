from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.avatars.repository import AvatarsRepository
from reflections.core.settings import settings
from reflections.voice.http_schemas import GreetResponse
from reflections.voice.repository import VoiceRepository


@dataclass(frozen=True)
class VoiceHttpService:
    repo: VoiceRepository
    avatars_repo: AvatarsRepository

    @classmethod
    def create(cls) -> "VoiceHttpService":
        return cls(repo=VoiceRepository(), avatars_repo=AvatarsRepository())

    async def greet(self, session: AsyncSession, *, user) -> GreetResponse:
        """
        Generate an initial assistant greeting and (optionally) synthesize TTS.

        This is used to:
        - greet the user by name
        - warm up Ollama + the TTS bridge (Piper) early to reduce first-turn latency
        """
        user_name = str(getattr(user, "name", "") or "").strip() or "there"
        voice: str | None = None
        persona: str | None = None

        active_avatar_id = getattr(user, "active_avatar_id", None)
        if active_avatar_id:
            a = await self.avatars_repo.get_for_user(
                session, user_id=user.id, avatar_id=active_avatar_id
            )
            if a is not None:
                persona = (a.persona_prompt or None)
                vc = a.voice_config or {}
                voice = (vc.get("voice") or vc.get("tts_voice") or None)
                if voice is not None:
                    voice = str(voice).strip() or None

        system_prompt = (
            (persona.strip() + "\n\n") if persona else ""
        ) + "You are Lumina. Greet the user warmly in 1-2 short sentences."
        user_prompt = f"The user's name is {user_name}. Greet them by name."

        text = await self.repo.generate_assistant_reply_chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ]
        )
        text = " ".join(text.strip().split())
        if not text:
            text = f"Welcome back, {user_name}."

        wav_b64: str | None = None
        if settings.TTS_BASE_URL:
            wav_bytes = await self.repo.synthesize_tts_wav(text=text, voice=voice)
            wav_b64 = self.repo.wav_bytes_to_b64(wav_bytes)

        return GreetResponse(text=text, wav_b64=wav_b64, voice=voice)


@lru_cache
def get_voice_http_service() -> VoiceHttpService:
    return VoiceHttpService.create()


