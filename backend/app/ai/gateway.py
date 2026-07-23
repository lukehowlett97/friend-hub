"""
AI gateway — provider-agnostic interface + OpenRouter implementation.
"""
import logging
from typing import Protocol, runtime_checkable

import httpx

logger = logging.getLogger(__name__)

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


@runtime_checkable
class ChatModelProvider(Protocol):
    async def complete_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
    ) -> tuple[str, int, int]:
        """Returns (response_text, tokens_in, tokens_out)."""
        ...


class OpenRouterProvider:
    """Calls OpenRouter's OpenAI-compatible chat completions endpoint."""

    def __init__(self, api_key: str):
        self._api_key = api_key

    async def complete_chat(
        self,
        messages: list[dict],
        model: str,
        temperature: float = 0.7,
    ) -> tuple[str, int, int]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://friend-hub.app",
            "X-Title": "Friend Hub",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{OPENROUTER_BASE_URL}/chat/completions",
                json=payload,
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]
        text = choice["message"]["content"].strip()
        usage = data.get("usage", {})
        tokens_in = usage.get("prompt_tokens", 0)
        tokens_out = usage.get("completion_tokens", 0)

        return text, tokens_in, tokens_out


def get_provider(api_key: str, provider_name: str = "openrouter") -> ChatModelProvider:
    """Returns the right provider for the configured name."""
    if provider_name in ("openrouter", "openai"):
        return OpenRouterProvider(api_key)
    raise ValueError(f"Unknown AI provider: {provider_name!r}")


@runtime_checkable
class EmbeddingProvider(Protocol):
    async def embed_texts(self, texts: list[str], model: str) -> tuple[list[list[float]], int]:
        """Returns (vectors, tokens_in). tokens_in is 0 when the provider doesn't report usage."""
        ...


class FakeEmbeddingProvider:
    """Deterministic embeddings for tests/dev — same text always maps to the same vector."""

    DIMENSIONS = 64

    async def embed_texts(self, texts: list[str], model: str) -> tuple[list[list[float]], int]:
        import hashlib
        import math
        import random

        vectors: list[list[float]] = []
        for text in texts:
            seed = int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big")
            rng = random.Random(seed)
            raw = [rng.uniform(-1.0, 1.0) for _ in range(self.DIMENSIONS)]
            norm = math.sqrt(sum(v * v for v in raw)) or 1.0
            vectors.append([v / norm for v in raw])
        return vectors, 0


class OllamaEmbeddingProvider:
    """Embeddings via a local Ollama server (one request per text; no usage reporting)."""

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    async def embed_texts(self, texts: list[str], model: str) -> tuple[list[list[float]], int]:
        vectors: list[list[float]] = []
        async with httpx.AsyncClient(timeout=60.0) as client:
            for text in texts:
                resp = await client.post(
                    f"{self._base_url}/api/embeddings",
                    json={"model": model, "prompt": text},
                )
                resp.raise_for_status()
                vectors.append(resp.json()["embedding"])
        return vectors, 0


class OpenAIEmbeddingProvider:
    """Embeddings via an OpenAI-compatible /v1/embeddings endpoint (batched)."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com"):
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")

    async def embed_texts(self, texts: list[str], model: str) -> tuple[list[list[float]], int]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{self._base_url}/v1/embeddings",
                json={"model": model, "input": texts},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        items = sorted(data["data"], key=lambda d: d["index"])
        vectors = [item["embedding"] for item in items]
        tokens_in = data.get("usage", {}).get("prompt_tokens", 0)
        return vectors, tokens_in


def get_embedding_provider(settings) -> EmbeddingProvider:
    """Returns the embedding provider for settings.ai_embedding_provider."""
    name = settings.ai_embedding_provider
    if name == "fake":
        return FakeEmbeddingProvider()
    if name == "ollama":
        return OllamaEmbeddingProvider(settings.ollama_base_url)
    if name == "openai":
        if not settings.ai_embedding_api_key:
            raise ValueError("AI_EMBEDDING_API_KEY is required for the openai embedding provider")
        return OpenAIEmbeddingProvider(settings.ai_embedding_api_key, settings.ai_embedding_base_url)
    raise ValueError(f"Unknown embedding provider: {name!r}")


class PollinationsImageProvider:
    """Generates images via Pollinations.ai — no API key required."""

    async def generate_image(self, prompt: str, model: str = "") -> str:
        """Returns a URL to the generated image."""
        import urllib.parse
        encoded = urllib.parse.quote(prompt)
        url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
        # HEAD request to verify the image is generated before returning the URL
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        return url


def get_image_provider(api_key: str = "") -> PollinationsImageProvider:
    return PollinationsImageProvider()
