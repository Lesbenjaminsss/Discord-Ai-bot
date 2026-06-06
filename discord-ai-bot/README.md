# Discord AI Soru-Cevap Botu

Kullanicilar botu **etiketleyerek** soru sorar; bot OpenAI ile cevaplar.

Casino botu (`discord-bot`) ve tasarim botundan (`discord-tasarla-bot`) ayri. **Yeni bir Discord uygulamasi** olusturup onun tokenini kullan.

## Kurulum

1. [Discord Developer Portal](https://discord.com/developers/applications) -> **New Application** -> Bot -> token al
2. OAuth2 URL Generator:
   - Scopes: `bot` + `applications.commands`
   - Bot permissions: **Mesaj Gonder**, **Mesaj Gecmisini Oku**
   - Linki acip sunucuya ekle
4. [OpenAI API key](https://platform.openai.com/api-keys) al (kredi gerekir)
5. Bu klasorde:

```
pip install -r requirements.txt
copy .env.example .env
```

`.env` icine yaz:

```
DISCORD_TOKEN=...
DISCORD_GUILD_ID=...
OPENAI_API_KEY=...
```

6. `python token_kontrol.py` sonra `python bot.py` (veya `baslat.bat`)

## Kullanim

**Slash komut (hemen calisir):**

```
/sor soru: Python'da dosya nasil acilir?
```

**Etiket (opsiyonel):** Developer Portal -> Bot -> **Message Content Intent** ac,
`.env` dosyasina `ENABLE_MENTIONS=1` ekle, botu yeniden baslat. Sonra:

```
@BotAdi Python'da dosya nasil acilir?
```

## OpenAI kotasi dolunca

Varsayilan `CHAT_PROVIDER=auto`: OpenAI limiti dolunca bot otomatik **Pollinations** ucretsiz yedegine gecer.

Sadece ucretsiz: `CHAT_PROVIDER=pollinations`
Sadece OpenAI: `CHAT_PROVIDER=openai` (+ faturalama acik olmali)

## Ayarlar (.env)

| Degisken | Aciklama |
| -------- | -------- |
| `DISCORD_TOKEN` | Discord bot token |
| `OPENAI_API_KEY` | OpenAI API anahtari |
| `CHAT_PROVIDER` | `auto` (varsayilan), `openai`, `pollinations` |
| `CHAT_MODEL` | Varsayilan: `gpt-4o-mini` |
| `POLLINATIONS_CHAT_MODEL` | Ucretsiz yedek model, varsayilan `openai` |
| `POLLINATIONS_API_KEY` | Istege bagli — https://enter.pollinations.ai |
| `CHAT_COOLDOWN_SEC` | Kullanici basina bekleme (saniye), varsayilan 10 |
| `MAX_REPLY_CHARS` | Tek mesaj karakter limiti (max 2000) |
| `SYSTEM_PROMPT` | AI davranisini ozellestir (istege bagli) |

## Klasor

`c:\Users\lesbe\Projects\mta-phone\discord-ai-bot`
