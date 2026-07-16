"""
Tropelex LLM Backend
Unified interface for Ollama (primary, free) and OpenAI (fallback).
All features in Tropelex call this module — never OpenAI/Ollama directly.
"""

import logging
import os

logger = logging.getLogger("tropelex.llm")

# ── Config ──────────────────────────────────────────────────────────────────

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
OPENAI_BASE_URL = "https://api.openai.com/v1"
OPENAI_CHAT_MODEL = "gpt-4o-mini"
OPENAI_EMBED_MODEL = "text-embedding-3-small"

COMPRESS_SYSTEM = (
    "Rewrite the user's prompt to be concise and imperative. "
    "Remove all filler words, politeness markers, and redundant phrasing "
    "(e.g. 'please', 'thank you', 'just', 'actually', 'basically', "
    "'I would like to', 'could you please'). "
    "Preserve ALL technical requirements, constraints, and context. "
    "Fix any typos. Output ONLY the compressed prompt, nothing else."
)


# ── Ollama ───────────────────────────────────────────────────────────────────


async def _ollama_available() -> bool:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/version")
            return r.status_code == 200
    except Exception:
        return False


async def _ollama_chat(messages: list, model: str = OLLAMA_MODEL) -> str | None:
    try:
        import httpx

        async with httpx.AsyncClient(timeout=60.0) as client:
            r = await client.post(
                f"{OLLAMA_BASE_URL}/api/chat",
                json={"model": model, "messages": messages, "stream": False},
            )
            if r.status_code == 200:
                return r.json()["message"]["content"].strip()
    except Exception as e:
        logger.warning("Ollama chat failed: %s", e)
    return None


# ── OpenAI ───────────────────────────────────────────────────────────────────


def _openai_key() -> str | None:
    key = os.environ.get("OPENAI_API_KEY", "")
    return key if key.startswith("sk-") else None


async def _openai_chat(messages: list, max_tokens: int = 1000) -> str | None:
    key = _openai_key()
    if not key:
        return None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{OPENAI_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": OPENAI_CHAT_MODEL,
                    "messages": messages,
                    "temperature": 0.2,
                    "max_tokens": max_tokens,
                },
            )
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"].strip()
            logger.error("OpenAI chat error %s: %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("OpenAI chat failed: %s", e)
    return None


async def _openai_embed(texts: list[str]) -> list[list[float]] | None:
    key = _openai_key()
    if not key:
        return None
    try:
        import httpx

        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{OPENAI_BASE_URL}/embeddings",
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json={"model": OPENAI_EMBED_MODEL, "input": texts},
            )
            if r.status_code == 200:
                data = r.json()["data"]
                data.sort(key=lambda x: x["index"])
                return [d["embedding"] for d in data]
            logger.error("OpenAI embed error %s: %s", r.status_code, r.text[:200])
    except Exception as e:
        logger.warning("OpenAI embed failed: %s", e)
    return None


# ── Public API ───────────────────────────────────────────────────────────────


async def compress(prompt: str) -> dict:
    """
    Compress a prompt. Tries Ollama first, falls back to OpenAI.
    Returns {"compressed": str, "backend": str, "error": str|None}
    """
    messages = [
        {"role": "system", "content": COMPRESS_SYSTEM},
        {"role": "user", "content": prompt},
    ]

    # Try Ollama first
    if await _ollama_available():
        result = await _ollama_chat(messages)
        if result:
            return {
                "compressed": result,
                "backend": f"ollama/{OLLAMA_MODEL}",
                "error": None,
            }

    # Fall back to OpenAI
    result = await _openai_chat(messages, max_tokens=min(len(prompt) // 2 + 100, 1000))
    if result:
        return {
            "compressed": result,
            "backend": f"openai/{OPENAI_CHAT_MODEL}",
            "error": None,
        }

    return {
        "compressed": prompt,
        "backend": "none",
        "error": "No LLM backend available",
    }


async def chat(system: str, user: str, max_tokens: int = 500) -> str | None:
    """
    General-purpose chat. Ollama → OpenAI fallback.
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    if await _ollama_available():
        result = await _ollama_chat(messages)
        if result:
            return result
    return await _openai_chat(messages, max_tokens=max_tokens)


async def embed(texts: list[str]) -> list[list[float]] | None:
    """
    Generate embeddings. OpenAI text-embedding-3-small only (best quality/cost).
    Returns list of float vectors, or None if unavailable.
    """
    if not texts:
        return []
    # Batch in chunks of 100 (OpenAI limit)
    results = []
    for i in range(0, len(texts), 100):
        batch = texts[i : i + 100]
        vecs = await _openai_embed(batch)
        if vecs is None:
            return None
        results.extend(vecs)
    return results


async def embed_one(text: str) -> list[float] | None:
    """Embed a single string."""
    vecs = await embed([text])
    return vecs[0] if vecs else None


async def available_backends() -> dict:
    """Report which backends are available."""
    ollama = await _ollama_available()
    openai = _openai_key() is not None
    return {
        "ollama": ollama,
        "ollama_model": OLLAMA_MODEL if ollama else None,
        "openai": openai,
        "embeddings": openai,
    }
