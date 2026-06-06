"""OpenAI ile soru-cevap — kotasi dolunca Pollinations yedegi."""
from __future__ import annotations

import asyncio
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date

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
_WIKI_UA = "DiscordAiBot/1.0 (educational; wiki lookup)"
_CHAT_TEMPERATURE = 0.25

_TR_MONTH_NUM = {
    "ocak": 1,
    "şubat": 2,
    "subat": 2,
    "mart": 3,
    "nisan": 4,
    "mayıs": 5,
    "mayis": 5,
    "haziran": 6,
    "temmuz": 7,
    "ağustos": 8,
    "agustos": 8,
    "eylül": 9,
    "eylul": 9,
    "ekim": 10,
    "kasım": 11,
    "kasim": 11,
    "aralık": 12,
    "aralik": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_TR_MONTH_NAME = (
    "",
    "Ocak",
    "Şubat",
    "Mart",
    "Nisan",
    "Mayıs",
    "Haziran",
    "Temmuz",
    "Ağustos",
    "Eylül",
    "Ekim",
    "Kasım",
    "Aralık",
)

_MONTH_ALT = (
    r"ocak|şubat|subat|mart|nisan|mayıs|mayis|haziran|temmuz|ağustos|agustos|"
    r"eylül|eylul|ekim|kasım|kasim|aralık|aralik|january|february|march|april|"
    r"may|june|july|august|september|october|november|december"
)


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


def _strip_pollinations_footer(text: str) -> str:
    """Pollinations ucretsiz API'nin sonuna ekledigi reklam metnini temizler."""
    cleaned = text.strip()
    patterns = (
        r"\n-{3,}\s*\n\s*Support\s+Pollinations\.AI:.*$",
        r"\n-{3,}\s*\n\s*🌸.*?🌸\s*\n\s*Powered by Pollinations\.AI.*$",
        r"\nPowered by Pollinations\.AI[^\n]*$",
        r"\nSupport Pollinations\.AI:.*$",
        r"\n-{3,}\s*$",
    )
    for pattern in patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.IGNORECASE | re.DOTALL)

    lines = cleaned.splitlines()
    while lines:
        line = lines[-1].strip()
        if not line:
            lines.pop()
            continue
        lower = line.lower()
        if (
            line == "---"
            or "pollinations.ai" in lower
            or lower.startswith("support pollinations")
            or lower.startswith("powered by pollinations")
            or (line.startswith("🌸") and "🌸" in line[1:])
        ):
            lines.pop()
            continue
        break
    return "\n".join(lines).strip()


def _extract_wikipedia_search_term(question: str) -> str:
    q = question.strip().rstrip("?").strip()
    lower = q.lower()

    tail_markers = (
        " ne zaman başlıyor",
        " ne zaman basliyor",
        " ne zaman başlar",
        " ne zaman baslar",
        " ne zaman",
        " kaç gün kaldı",
        " kac gun kaldi",
        " kaç gün var",
        " kac gun var",
        " kaç gün",
        " kac gun",
        " hangi tarihte",
        " hangi tarih",
        " başlıyor mu",
        " basliyor mu",
    )
    for marker in sorted(tail_markers, key=len, reverse=True):
        if lower.endswith(marker):
            q = q[: -len(marker)].strip(" ,.")
            lower = q.lower()
            break

    for marker in (
        " kimdir",
        " nedir",
        " ne demek",
        " hakkinda",
        " hakkında",
        " kac yasinda",
        " kaç yaşında",
        " dogum tarihi",
        " doğum tarihi",
        " hangi takimda",
        " hangi takımda",
        " nereli",
        " boyu kac",
        " boyu kaç",
        " meslegi",
        " mesleği",
    ):
        idx = lower.find(marker)
        if idx > 0:
            q = q[:idx].strip(" ,.")
            break

    return _normalize_wiki_term(q)


def _normalize_wiki_term(term: str) -> str:
    lower = term.lower()
    if "dünya kupası" in lower or "dunya kupasi" in lower or "world cup" in lower:
        return "2026 FIFA Dünya Kupası"
    return term.strip()


def _wikipedia_summary_sync(term: str, lang: str = "tr") -> str | None:
    params = urllib.parse.urlencode(
        {
            "action": "opensearch",
            "search": term,
            "limit": 1,
            "namespace": 0,
            "format": "json",
        }
    )
    search_url = f"https://{lang}.wikipedia.org/w/api.php?{params}"
    req = urllib.request.Request(search_url, headers={"User-Agent": _WIKI_UA})
    with urllib.request.urlopen(req, timeout=12) as resp:
        data = json.loads(resp.read().decode())
    if len(data) < 2 or not data[1]:
        return None

    title = data[1][0]
    title_path = urllib.parse.quote(title.replace(" ", "_"), safe="/")
    summary_url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{title_path}"
    req2 = urllib.request.Request(summary_url, headers={"User-Agent": _WIKI_UA})
    with urllib.request.urlopen(req2, timeout=12) as resp2:
        page = json.loads(resp2.read().decode())

    extract = (page.get("extract") or page.get("description") or "").strip()
    if not extract:
        return None
    return f"{title}: {extract}"[:1400]


async def _wikipedia_lookup(question: str) -> str | None:
    primary = _extract_wikipedia_search_term(question)
    candidates: list[tuple[str, str]] = [(primary, "tr")]
    if primary != question.strip().rstrip("?"):
        candidates.append((question.strip().rstrip("?")[:80], "tr"))
    lower = question.lower()
    if "dünya kupası" in lower or "dunya kupasi" in lower or "world cup" in lower:
        candidates.append(("2026 FIFA World Cup", "en"))

    seen: set[str] = set()
    for term, lang in candidates:
        key = f"{lang}:{term.lower()}"
        if key in seen or len(term) < 2 or len(term) > 120:
            continue
        seen.add(key)
        try:
            result = await asyncio.to_thread(_wikipedia_summary_sync, term, lang)
        except Exception:
            continue
        if result:
            return result
    return None


def _parse_event_start_date(wiki: str) -> date | None:
    year_match = re.search(r"\b(20\d{2})\b", wiki)
    default_year = int(year_match.group(1)) if year_match else date.today().year

    range_match = re.search(
        rf"(\d{{1,2}})\s+({_MONTH_ALT})\s*[-–—]\s*\d{{1,2}}\s+(?:{_MONTH_ALT})\s+(20\d{{2}})",
        wiki,
        re.IGNORECASE,
    )
    if range_match:
        day = int(range_match.group(1))
        month_name = range_match.group(2).lower()
        year = int(range_match.group(3))
        month = _TR_MONTH_NUM.get(month_name)
        if month:
            return date(year, month, day)

    range_match2 = re.search(
        rf"(\d{{1,2}})\s+({_MONTH_ALT})\s*[-–—]\s*\d{{1,2}}\s+(?:{_MONTH_ALT})",
        wiki,
        re.IGNORECASE,
    )
    if range_match2:
        day = int(range_match2.group(1))
        month_name = range_match2.group(2).lower()
        month = _TR_MONTH_NUM.get(month_name)
        if month:
            return date(default_year, month, day)

    single_match = re.search(
        rf"(\d{{1,2}})\s+({_MONTH_ALT})(?:\s+(20\d{{2}}))?",
        wiki,
        re.IGNORECASE,
    )
    if single_match:
        day = int(single_match.group(1))
        month_name = single_match.group(2).lower()
        year = int(single_match.group(3)) if single_match.group(3) else default_year
        month = _TR_MONTH_NUM.get(month_name)
        if month:
            return date(year, month, day)

    return None


def _format_tr_date(d: date) -> str:
    return f"{d.day} {_TR_MONTH_NAME[d.month]} {d.year}"


def _maybe_direct_date_answer(question: str, wiki: str | None) -> str | None:
    if not wiki:
        return None

    lower = question.lower()
    asks_when = any(
        k in lower
        for k in (
            "ne zaman",
            "kaç gün",
            "kac gun",
            "kaldı",
            "kaldi",
            "başlıyor",
            "basliyor",
            "başlar",
            "baslar",
        )
    )
    if not asks_when:
        return None

    start = _parse_event_start_date(wiki)
    if not start:
        return None

    today = date.today()
    days_left = (start - today).days
    event_name = wiki.split(":", 1)[0].strip()
    start_str = _format_tr_date(start)
    today_str = _format_tr_date(today)

    if "kaç gün" in lower or "kac gun" in lower or "kaldı" in lower or "kaldi" in lower:
        if days_left > 0:
            return (
                f"**{event_name}** **{start_str}** tarihinde başlıyor "
                f"(açılış maçı). Bugüne ({today_str}) göre **{days_left} gün** kaldı."
            )
        if days_left == 0:
            return f"**{event_name}** bugün ({start_str}) başlıyor."
        return (
            f"**{event_name}** {start_str} tarihinde başladı; "
            f"bugüne göre **{abs(days_left)} gün** önce."
        )

    return f"**{event_name}** **{start_str}** tarihinde başlıyor (açılış maçı)."


def _today_context() -> str:
    today = date.today()
    return (
        f"Bugunun tarihi: {_format_tr_date(today)} ({today.isoformat()}). "
        "Geri sayim ve 'kac gun kaldi' hesaplarinda SADECE bu tarihi kullan. "
        "Turnuva baslangic tarihi ile grup asamasi gunlerini karistirma; "
        "2026 Dunya Kupasi acilis maci 11 Haziran 2026'dir, 23 Haziran degil."
    )


def _build_system_content(wiki: str | None) -> str:
    base = get_system_prompt()
    parts = [base, _today_context()]
    if wiki:
        parts.append(
            "Asagidaki Vikipedi ozeti guvenilir kaynaktir. "
            "Tarih sorularinda Vikipedi'deki baslangic tarihini kullan; celisen bilgi uydurma.\n\n"
            f"Vikipedi:\n{wiki}"
        )
    return "\n\n".join(parts)


def _build_chat_messages(question: str, wiki: str | None) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": _build_system_content(wiki)},
        {"role": "user", "content": question},
    ]


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


def _build_simple_prompt(question: str, wiki: str | None) -> str:
    system = _build_system_content(wiki)
    return (
        f"{system}\n\n"
        f"Kullanici sorusu: {question}\n\n"
        "Kisa, dogru ve net cevap ver. Bilmedigini yazma:"
    )


async def _ask_pollinations_chat(question: str, wiki: str | None) -> str:
    client = _get_pollinations_client()
    model = get_pollinations_chat_model()
    try:
        response = await client.chat.completions.create(
            model=model,
            messages=_build_chat_messages(question, wiki),
            max_tokens=1024,
            temperature=_CHAT_TEMPERATURE,
        )
    except OpenAIError as e:
        raise ChatError(f"Pollinations hatasi: {e}") from e

    choice = response.choices[0].message.content
    if not choice or not choice.strip():
        raise ChatError("Pollinations bos cevap dondurdu.")
    return _strip_pollinations_footer(choice.strip())


async def _ask_pollinations_simple(question: str, wiki: str | None) -> str:
    prompt = _build_simple_prompt(question, wiki)
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
            raw = await asyncio.to_thread(_http_get_text, url)
            return _strip_pollinations_footer(raw)
        except ChatError as e:
            last_err = e
            continue

    raise ChatError(
        f"Ucretsiz AI servisi calismadi: {last_err}. "
        "Pollinations anahtari icin: https://enter.pollinations.ai"
    ) from last_err


async def _ask_pollinations(question: str, wiki: str | None) -> ChatResult:
    last_err: Exception | None = None

    for attempt_fn in (_ask_pollinations_chat, _ask_pollinations_simple):
        try:
            text = await attempt_fn(question, wiki)
            return ChatResult(text=text, provider="pollinations")
        except ChatError as e:
            last_err = e
            print(f"Pollinations denemesi basarisiz: {e}", flush=True)

    raise ChatError(
        f"Ucretsiz AI servisi calismadi: {last_err}. "
        "OpenAI faturasini ac veya https://enter.pollinations.ai adresinden anahtar al."
    ) from last_err


async def _ask_openai(question: str, wiki: str | None) -> ChatResult:
    client = _get_openai_client()
    model = get_chat_model()

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=_build_chat_messages(question, wiki),
            max_tokens=1024,
            temperature=_CHAT_TEMPERATURE,
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

    wiki = await _wikipedia_lookup(question)
    if wiki:
        print("Vikipedi baglami kullaniliyor.", flush=True)

    direct = _maybe_direct_date_answer(question, wiki)
    if direct:
        print("Tarih/geri sayim dogrudan hesaplandi.", flush=True)
        return ChatResult(text=direct, provider="wiki")

    provider = get_chat_provider()

    if provider == "pollinations":
        return await _ask_pollinations(question, wiki)

    if provider == "openai":
        try:
            return await _ask_openai(question, wiki)
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
            return await _ask_openai(question, wiki)
        except (APIError, RateLimitError, OpenAIError) as e:
            if _is_billing_error(e):
                print("OpenAI kotasi dolu, Pollinations yedegine geciliyor...", flush=True)
                return await _ask_pollinations(question, wiki)
            raise ChatError(f"OpenAI hatasi: {e}") from e

    return await _ask_pollinations(question, wiki)
