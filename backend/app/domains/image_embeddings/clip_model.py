from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


class OpenCLIPRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class OpenCLIPConfig:
    model_name: str
    model_version: str
    device: str = "auto"


class OpenCLIPEmbedder:
    def __init__(self, config: OpenCLIPConfig):
        self.config = config
        self._loaded = False
        self._device = None
        self._model = None
        self._preprocess = None
        self._tokenizer = None
        self._torch = None
        self._image_cls = None

    @property
    def model_name(self) -> str:
        return self.config.model_name

    @property
    def model_version(self) -> str:
        return self.config.model_version

    def embed_image(self, image_path: Path | str) -> list[float]:
        self._load()
        image = self._image_cls.open(image_path).convert("RGB")
        tensor = self._preprocess(image).unsqueeze(0).to(self._device)
        with self._torch.no_grad():
            embedding = self._model.encode_image(tensor)
            embedding = embedding / embedding.norm(dim=-1, keepdim=True)
        return _to_float_list(embedding)

    def embed_text(self, text: str) -> list[float]:
        self._load()
        tokens = self._tokenizer([text]).to(self._device)
        with self._torch.no_grad():
            embedding = self._model.encode_text(tokens)
            embedding = embedding / embedding.norm(dim=-1, keepdim=True)
        return _to_float_list(embedding)

    def _load(self) -> None:
        if self._loaded:
            return
        try:
            import open_clip
            import torch
            from PIL import Image
        except ImportError as exc:
            raise OpenCLIPRuntimeError(
                "Image embedding worker requires optional ML dependencies: "
                "torch, open_clip_torch, and Pillow. Install them only in the "
                "worker environment, not necessarily the web app container."
            ) from exc

        device = self._resolve_device(torch)
        model, _, preprocess = open_clip.create_model_and_transforms(
            self.config.model_name,
            pretrained=self.config.model_version,
            device=device,
        )
        model.eval()

        self._torch = torch
        self._image_cls = Image
        self._device = device
        self._model = model
        self._preprocess = preprocess
        self._tokenizer = open_clip.get_tokenizer(self.config.model_name)
        self._loaded = True

    def _resolve_device(self, torch: Any) -> str:
        requested = (self.config.device or "auto").lower()
        if requested == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        if requested == "cuda" and not torch.cuda.is_available():
            raise OpenCLIPRuntimeError("IMAGE_EMBEDDINGS_DEVICE=cuda requested, but CUDA is not available")
        if requested not in {"cpu", "cuda"}:
            raise OpenCLIPRuntimeError("IMAGE_EMBEDDINGS_DEVICE must be one of: auto, cpu, cuda")
        return requested


def _to_float_list(embedding) -> list[float]:
    values = embedding.detach().cpu().squeeze(0).tolist()
    return [float(value) for value in values]
