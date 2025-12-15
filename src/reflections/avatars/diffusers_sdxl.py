from __future__ import annotations

import asyncio
import base64
import io
from dataclasses import dataclass
from functools import lru_cache

from reflections.core.settings import settings


class DiffusersSDXLException(RuntimeError):
    pass


def _validate_local_sdxl_dir(path: str, *, variant: str | None):  # type: ignore[no-untyped-def]
    """
    Fail-fast validation for local Diffusers SDXL directories.

    This catches common issues like downloading the right folders but having
    unexpected weight filenames (Diffusers looks for specific names).
    """
    from pathlib import Path

    p = Path(path)
    if not p.exists() or not p.is_dir():
        raise DiffusersSDXLException(f"diffusers_model_dir_missing:{path}")
    if not (p / "model_index.json").exists():
        raise DiffusersSDXLException(
            f"diffusers_missing_model_index_json:{(p / 'model_index.json')}"
        )

    # Unet weights are the most common “wrong filename” issue.
    unet_dir = p / "unet"
    if not unet_dir.exists():
        raise DiffusersSDXLException(f"diffusers_missing_component_dir:{unet_dir}")
    if not (unet_dir / "config.json").exists():
        raise DiffusersSDXLException(f"diffusers_missing_config:{unet_dir/'config.json'}")

    expected = (
        "diffusion_pytorch_model.fp16.safetensors"
        if (variant or "").lower().strip() == "fp16"
        else "diffusion_pytorch_model.safetensors"
    )
    if not (unet_dir / expected).exists():
        # Suggest candidates so the user can rename without guessing.
        candidates = sorted([x.name for x in unet_dir.glob("*.safetensors")])
        raise DiffusersSDXLException(
            "diffusers_missing_unet_weights:"
            f"expected={unet_dir/expected}; found={candidates}"
        )


def _dtype_from_str(s: str):  # type: ignore[no-untyped-def]
    import torch  # type: ignore[import-not-found]

    v = (s or "").lower().strip()
    if v == "float16" or v == "fp16":
        return torch.float16
    if v == "float32" or v == "fp32":
        return torch.float32
    raise DiffusersSDXLException(f"diffusers_invalid_dtype:{s}")


@dataclass(frozen=True)
class DiffusersSDXLClient:
    base_model: str
    refiner_model: str | None
    local_files_only: bool
    device: str
    dtype: str
    high_noise_frac: float
    enable_compile: bool

    def _load_pipes(self):  # type: ignore[no-untyped-def]
        """
        Load and cache SDXL base (+ optional refiner) pipelines.

        This intentionally imports heavy deps lazily so the backend can run
        without Torch/Diffusers installed unless this feature is used.
        """
        import torch  # type: ignore[import-not-found]
        from diffusers import DiffusionPipeline  # type: ignore[import-not-found]

        torch_dtype = _dtype_from_str(self.dtype)

        # Determine whether we should load the fp16 variant weights (common for SDXL).
        # We may still want to load fp16 weights even when running with float32 on CPU.
        variant: str | None = None
        if self.local_files_only:
            from pathlib import Path

            base_path = Path(self.base_model)
            if base_path.exists() and (base_path / "unet" / "diffusion_pytorch_model.fp16.safetensors").exists():
                variant = "fp16"

        # Device fallback: Docker on macOS typically has CPU-only PyTorch.
        device = self.device
        if device == "mps":
            mps_ok = bool(getattr(torch.backends, "mps", None)) and bool(
                torch.backends.mps.is_available()
            )
            if not mps_ok:
                device = "cpu"
                # On CPU, float16 often fails or is extremely slow; prefer float32 compute.
                if torch_dtype == torch.float16:
                    torch_dtype = torch.float32

        if self.local_files_only:
            # If this is a local directory, validate that the expected filenames exist.
            # (If it's a HF model id in cache, Path(...) won't exist; skip validation.)
            from pathlib import Path

            if Path(self.base_model).exists():
                _validate_local_sdxl_dir(self.base_model, variant=variant)
            if self.refiner_model and Path(self.refiner_model).exists():
                _validate_local_sdxl_dir(self.refiner_model, variant=variant)

        base = DiffusionPipeline.from_pretrained(
            self.base_model,
            torch_dtype=torch_dtype,
            use_safetensors=True,
            variant=variant,
            local_files_only=bool(self.local_files_only),
        )
        if hasattr(base, "enable_attention_slicing"):
            base.enable_attention_slicing()
        if hasattr(base, "enable_vae_slicing"):
            base.enable_vae_slicing()
        base.to(device)
        if self.enable_compile and hasattr(torch, "compile"):
            try:
                base.unet = torch.compile(  # type: ignore[attr-defined]
                    base.unet, mode="reduce-overhead", fullgraph=True
                )
            except Exception:
                # Compilation is optional; ignore failures.
                pass

        refiner = None
        if self.refiner_model:
            refiner = DiffusionPipeline.from_pretrained(
                self.refiner_model,
                text_encoder_2=base.text_encoder_2,
                vae=base.vae,
                torch_dtype=torch_dtype,
                use_safetensors=True,
                variant=variant,
                local_files_only=bool(self.local_files_only),
            )
            if hasattr(refiner, "enable_attention_slicing"):
                refiner.enable_attention_slicing()
            if hasattr(refiner, "enable_vae_slicing"):
                refiner.enable_vae_slicing()
            refiner.to(device)
            if self.enable_compile and hasattr(torch, "compile"):
                try:
                    refiner.unet = torch.compile(  # type: ignore[attr-defined]
                        refiner.unet, mode="reduce-overhead", fullgraph=True
                    )
                except Exception:
                    pass

        return base, refiner

    @lru_cache(maxsize=1)
    def _pipes_cached(self):  # type: ignore[no-untyped-def]
        return self._load_pipes()

    def _generate_sync(self, *, prompt: str, negative_prompt: str | None, width: int, height: int, steps: int, cfg_scale: float, seed: int) -> str:  # type: ignore[no-untyped-def]
        import torch  # type: ignore[import-not-found]

        base, refiner = self._pipes_cached()

        generator = None
        if seed is not None and int(seed) >= 0:
            # Using CPU generator tends to be the most portable across devices.
            generator = torch.Generator(device="cpu").manual_seed(int(seed))

        if refiner is None:
            img = base(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=int(width),
                height=int(height),
                num_inference_steps=int(steps),
                guidance_scale=float(cfg_scale),
                generator=generator,
            ).images[0]
        else:
            latents = base(
                prompt=prompt,
                negative_prompt=negative_prompt,
                width=int(width),
                height=int(height),
                num_inference_steps=int(steps),
                denoising_end=float(self.high_noise_frac),
                guidance_scale=float(cfg_scale),
                generator=generator,
                output_type="latent",
            ).images
            img = refiner(
                prompt=prompt,
                negative_prompt=negative_prompt,
                num_inference_steps=int(steps),
                denoising_start=float(self.high_noise_frac),
                guidance_scale=float(cfg_scale),
                generator=generator,
                image=latents,
            ).images[0]

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"

    async def txt2img(
        self,
        *,
        prompt: str,
        negative_prompt: str | None,
        width: int,
        height: int,
        steps: int,
        cfg_scale: float,
        seed: int,
    ) -> str:
        # Diffusers generation is blocking + GPU-heavy; keep it off the event loop.
        return await asyncio.to_thread(
            self._generate_sync,
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
            steps=steps,
            cfg_scale=cfg_scale,
            seed=seed,
        )


def get_diffusers_sdxl_client() -> DiffusersSDXLClient:
    if not settings.DIFFUSERS_SDXL_BASE_MODEL:
        raise DiffusersSDXLException("DIFFUSERS_SDXL_BASE_MODEL is not configured")
    return DiffusersSDXLClient(
        base_model=str(settings.DIFFUSERS_SDXL_BASE_MODEL),
        refiner_model=str(settings.DIFFUSERS_SDXL_REFINER_MODEL)
        if settings.DIFFUSERS_SDXL_REFINER_MODEL
        else None,
        local_files_only=bool(settings.DIFFUSERS_LOCAL_FILES_ONLY),
        device=str(settings.DIFFUSERS_DEVICE),
        dtype=str(settings.DIFFUSERS_DTYPE),
        high_noise_frac=float(settings.DIFFUSERS_HIGH_NOISE_FRAC),
        enable_compile=bool(settings.DIFFUSERS_ENABLE_COMPILE),
    )


