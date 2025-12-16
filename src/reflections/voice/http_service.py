from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import logging

from sqlalchemy.ext.asyncio import AsyncSession  # type: ignore[import-not-found]

from reflections.avatars.repository import AvatarsRepository
from reflections.core.settings import settings
from reflections.voice.http_schemas import GreetResponse, ListVoicesResponse
from reflections.voice.repository import VoiceRepository

logger = logging.getLogger(__name__)


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
            try:
                wav_bytes = await self.repo.synthesize_tts_wav(text=text, voice=voice)
                wav_b64 = self.repo.wav_bytes_to_b64(wav_bytes)
            except Exception as e:
                # Degrade gracefully: the greeting text is still valuable even if
                # the host TTS bridge is down/misconfigured.
                logger.warning("greet_tts_failed: %s", str(e))

        return GreetResponse(text=text, wav_b64=wav_b64, voice=voice)

    async def list_voices(self) -> ListVoicesResponse:
        """
        List available voices for the current TTS engine (best-effort).
        """
        if not settings.TTS_BASE_URL:
            return ListVoicesResponse(engine=None, configured=False, voices=[])
        try:
            data = await self.repo.list_tts_voices()
            engine = str(data.get("engine") or "") or None
            voices = data.get("voices")
            if not isinstance(voices, list):
                voices = []
            return ListVoicesResponse(
                engine=engine,
                configured=True,
                voices=[str(v) for v in voices if str(v).strip()],
            )
        except Exception:
            # If the bridge doesn't implement /voices yet (or is down), degrade gracefully.
            return ListVoicesResponse(engine=None, configured=False, voices=[])


@lru_cache
def get_voice_http_service() -> VoiceHttpService:
    return VoiceHttpService.create()


