"""OpenAI ile soru-cevap — kotasi dolunca Pollinations yedegi."""
from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from openai import APIError, AsyncOpenAI, OpenAIError, RateLimitError

from settings import (
    get_chat_model,
    get_chat_provider,
    get_openai_api_key,
    get_pollinations_api_key,
    get_pollinations_chat_model,
    get_system_prompt,
)


class ChatError(Exception):
    pass


@dataclass
class ChatResult:
    text: str
    provider: str = "openai"


_openai_client: AsyncOpenAI | None = None
_pollinations_client: AsyncOpenAI | None = None


def _get_openai_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        key = get_openai_api_key()
        if not key:
            raise ChatError(
                "OpenAI API anahtari yok. `.env` dosyasina `OPENAI_API_KEY=sk-...` ekle "
                "veya `CHAT_PROVIDER=pollinations` kullan."
            )
        _openai_client = AsyncOpenAI(api_key=key)
    return _openai_client


def _get_pollinations_client() -> AsyncOpenAI:
    global _pollinations_client
    if _pollinations_client is None:
        key = get_pollinations_api_key() or "pollinations"
        _pollinations_client = AsyncOpenAI(
            api_key=key,
            base_url="https://gen.pollinations.ai/v1",
        )
    return _pollinations_client


def _is_billing_error(err: Exception) -> bool:
    msg = str(err).lower()
    if isinstance(err, APIError):
        msg = f"{err.message or err} {msg}".lower()
    return "insufficient_quota" in msg or "billing" in msg or "rate limit" in msg


def _http_get_text(url: str, timeout: int = 120) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "DiscordAiBot/1.0",
            "Accept": "text/plain,application/json,*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read().decode("utf-8", errors="replace").strip()
    except urllib.error.HTTPError as e:
        raise ChatError(f"Ucretsiz AI servisi hata {e.code}") from e
    except urllib.error.URLError as e:
        raise ChatError(f"Ucretsiz AI servisine baglanilamadi: {e}") from e

    if not data:
        raise ChatError("Ucretsiz AI bos cevap dondurdu.")
    if data.lstrip().startswith("<"):
        raise ChatError("Ucretsiz AI gecersiz yanit dondurdu.")
    return data


def _build_simple_prompt(question: str) -> str:
    return (
        f"{get_system_prompt()}\n\n"
        f"Kullanici sorusu: {question}\n\n"
        "Kisa ve net cevap ver:"
    )


async def _ask_pollinations_chat(question: str) -> str:
    client = _get_pollinations_client()
    model = get_pollinations_chat_model()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": get_system_prompt()},
                {"role": "user", "content": question},
            ],
            max_tokens=1024,
            temperature=0.7,
        )
    except OpenAIError as e:
        raise ChatError(f"Pollinations hatasi: {e}") from e

    choice = response.choices[0].message.content
    if not choice or not choice.strip():
        raise ChatError("Pollinations bos cevap dondurdu.")
    return choice.strip()


async def _ask_pollinations_simple(question: str) -> str:
    prompt = _build_simple_prompt(question)
    encoded = urllib.parse.quote(prompt, safe="")
    model = get_pollinations_chat_model()
    api_key = get_pollinations_api_key()

    urls = [
        f"https://text.pollinations.ai/{encoded}",
        f"https://gen.pollinations.ai/text/{encoded}?model={urllib.parse.quote(model)}",
    ]
    if api_key:
        urls.insert(0, f"https://gen.pollinations.ai/text/{encoded}?model={urllib.parse.quote(model)}&key={urllib.parse.quote(api_key)}")

    last_err: Exception | None = None
    for url in urls:
        try:
            return await asyncio.to_thread(_http_get_text, url)
        except ChatError as e:
            last_err = e
            continue

    raise ChatError(
        f"Ucretsiz AI servisi calismadi: {last_err}. "
        "Pollinations anahtari icin: https://enter.pollinations.ai"
    ) from last_err


async def _ask_pollinations(question: str) -> ChatResult:
    last_err: Exception | None = None

    if get_pollinations_api_key():
        try:
            text = await _ask_pollinations_chat(question)
            return ChatResult(text=text, provider="pollinations")
        except ChatError as e:
            last_err = e
            print(f"Pollinations chat basarisiz, basit endpoint deneniyor: {e}", flush=True)

    try:
        text = await _ask_pollinations_simple(question)
        return ChatResult(text=text, provider="pollinations")
    except ChatError as e:
        last_err = e

    if get_pollinations_api_key():
        try:
            text = await _ask_pollinations_chat(question)
            return ChatResult(text=text, provider="pollinations")
        except ChatError as e:
            last_err = e

    raise ChatError(
        f"Ucretsiz AI servisi calismadi: {last_err}. "
        "OpenAI faturasini ac veya https://enter.pollinations.ai adresinden anahtar al."
    ) from last_err


async def _ask_openai(question: str) -> ChatResult:
    client = _get_openai_client()
    model = get_chat_model()

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": get_system_prompt()},
                {"role": "user", "content": question},
            ],
            max_tokens=1024,
            temperature=0.7,
        )
    except RateLimitError as e:
        if _is_billing_error(e):
            raise
        raise ChatError("OpenAI cok hizli istek — biraz sonra tekrar dene.") from e
    except APIError as e:
        if _is_billing_error(e):
            raise
        if "invalid_api_key" in str(e).lower() or "authentication" in str(e).lower():
            raise ChatError("OpenAI API anahtari gecersiz.") from e
        raise ChatError(f"OpenAI hatasi: {e.message or e}") from e
    except OpenAIError as e:
        if _is_billing_error(e):
            raise
        raise ChatError(f"OpenAI hatasi: {e}") from e

    choice = response.choices[0].message.content
    if not choice or not choice.strip():
        raise ChatError("AI bos cevap dondurdu, tekrar dene.")
    return ChatResult(text=choice.strip(), provider="openai")


async def ask_ai(question: str) -> ChatResult:
    question = question.strip()
    if not question:
        raise ChatError("Soru bos. Beni etiketleyip sorunu yaz.")

    provider = get_chat_provider()

    if provider == "pollinations":
        return await _ask_pollinations(question)

    if provider == "openai":
        try:
            return await _ask_openai(question)
        except (APIError, RateLimitError, OpenAIError) as e:
            if _is_billing_error(e):
                raise ChatError(
                    "OpenAI kotasi veya odeme limiti dolu. "
                    "https://platform.openai.com/settings/organization/billing "
                    "veya `.env` → `CHAT_PROVIDER=auto` / `pollinations`"
                ) from e
            raise

    if get_openai_api_key():
        try:
            return await _ask_openai(question)
        except (APIError, RateLimitError, OpenAIError) as e:
            if _is_billing_error(e):
                print("OpenAI kotasi dolu, Pollinations yedegine geciliyor...", flush=True)
                return await _ask_pollinations(question)
            raise ChatError(f"OpenAI hatasi: {e}") from e

    return await _ask_pollinations(question)
