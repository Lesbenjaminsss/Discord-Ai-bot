"""
Discord AI soru-cevap botu.
/sor komutu her zaman calisir.
Etiket (@bot) icin Developer Portal'da Message Content Intent + ENABLE_MENTIONS=1 gerekir.
"""
import sys
import time

import discord
from discord import app_commands

from ai_chat import ChatError, ask_ai
from settings import (
    OWNER_ID,
    check_token,
    get_chat_cooldown_sec,
    get_enable_mentions,
    get_guild_id,
    get_max_reply_chars,
    get_token,
)

_cooldown: dict[int, float] = {}


def is_owner(uid: int) -> bool:
    return uid == OWNER_ID


def extract_question(message: discord.Message, bot_user: discord.ClientUser) -> str:
    text = message.content
    for mention in message.mentions:
        if mention.id == bot_user.id:
            text = text.replace(f"<@{mention.id}>", "")
            text = text.replace(f"<@!{mention.id}>", "")
    return text.strip()


def split_reply(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        cut = text.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    return chunks


def check_cooldown(uid: int) -> str | None:
    cooldown = get_chat_cooldown_sec()
    if cooldown <= 0 or is_owner(uid):
        return None
    last = _cooldown.get(uid, 0.0)
    wait = cooldown - (time.time() - last)
    if wait > 0:
        return f"Biraz bekle — **{int(wait) + 1}** saniye sonra tekrar dene."
    return None


async def answer_question(question: str, uid: int) -> tuple[list[str], str | None]:
    wait_msg = check_cooldown(uid)
    if wait_msg:
        return [], wait_msg

    question = question.strip()
    if not question:
        return [], "Soru bos. Ornek: `/sor soru: Python nedir?`"

    try:
        result = await ask_ai(question)
    except ChatError as e:
        return [], str(e)
    except Exception:
        return [], "Cevap uretilirken beklenmeyen hata. Terminal loguna bak."

    _cooldown[uid] = time.time()
    return split_reply(result.text, get_max_reply_chars()), None


class AiBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        if get_enable_mentions():
            intents.message_content = True
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self._synced = False

    async def _sync_commands(self) -> None:
        gid = get_guild_id()
        if gid.isdigit():
            guild = discord.Object(id=int(gid))
            self.tree.copy_global_to(guild=guild)
            try:
                synced = await self.tree.sync(guild=guild)
                where = f"sunucu {gid}"
            except discord.Forbidden:
                synced = await self.tree.sync()
                where = "global (yedek)"
        else:
            synced = await self.tree.sync()
            where = "global"
        names = [c.name for c in synced]
        print(f"Komutlar [{where}]: {', '.join(f'/{n}' for n in names)}", flush=True)

    async def on_ready(self) -> None:
        if not self._synced:
            self._synced = True
            await self._sync_commands()

        print("=" * 50, flush=True)
        print("AI SORU-CEVAP BOT AKTIF", flush=True)
        print(f"  {self.user} ({self.user.id})", flush=True)
        print("  /sor — soru sor", flush=True)
        if get_enable_mentions():
            print("  @bot etiketle — soru sor (Message Content Intent acik)", flush=True)
        else:
            print("  Etiket kapali — portalda Intent ac, .env: ENABLE_MENTIONS=1", flush=True)
        print("=" * 50, flush=True)
        await self.change_presence(activity=discord.Game(name="/sor"))


client = AiBot()


@client.tree.command(name="sor", description="AI'ya soru sor")
@app_commands.describe(soru="Sormak istedigin sey")
async def cmd_sor(i: discord.Interaction, soru: str):
    await i.response.defer(thinking=True)
    parts, err = await answer_question(soru, i.user.id)
    if err:
        return await i.followup.send(err, ephemeral=True)
    try:
        await i.followup.send(parts[0])
        for part in parts[1:]:
            await i.followup.send(part)
    except discord.Forbidden:
        await i.followup.send(
            "Bu kanala mesaj gonderme yetkim yok. Kanal izinlerini kontrol et.",
            ephemeral=True,
        )


@client.tree.command(name="yardim", description="Bot hakkinda bilgi")
async def cmd_yardim(i: discord.Interaction):
    emb = discord.Embed(title="AI Soru-Cevap Botu", color=0x3498DB)
    emb.add_field(
        name="Komut",
        value="`/sor soru:...` — AI'ya soru sor",
        inline=False,
    )
    if get_enable_mentions():
        emb.add_field(
            name="Etiket",
            value="Botu etiketleyip sorunu yaz: `@bot ...`",
            inline=False,
        )
    else:
        emb.add_field(
            name="Etiket (kapali)",
            value=(
                "Developer Portal -> Bot -> **Message Content Intent** ac, "
                "`.env` dosyasina `ENABLE_MENTIONS=1` ekle, botu yeniden baslat."
            ),
            inline=False,
        )
    await i.response.send_message(embed=emb)


@client.tree.error
async def tree_error(i: discord.Interaction, err: app_commands.AppCommandError):
    msg = f"Hata: {err}"
    if i.response.is_done():
        await i.followup.send(msg, ephemeral=True)
    else:
        await i.response.send_message(msg, ephemeral=True)


async def on_message_handler(message: discord.Message) -> None:
    if message.author.bot or client.user is None:
        return
    if client.user not in message.mentions:
        return

    question = extract_question(message, client.user)
    wait_msg = check_cooldown(message.author.id)
    if wait_msg:
        return await message.reply(wait_msg, mention_author=False)

    if not question:
        return await message.reply(
            "Merhaba! Beni etiketleyip sorunu yaz veya `/sor` kullan.",
            mention_author=False,
        )

    async with message.channel.typing():
        parts, err = await answer_question(question, message.author.id)

    if err:
        return await message.reply(err, mention_author=False)

    try:
        await message.reply(parts[0], mention_author=False)
        for part in parts[1:]:
            await message.channel.send(part)
    except discord.Forbidden:
        await message.channel.send(
            "Bu kanala mesaj gonderme yetkim yok. Kanal izinlerini kontrol et."
        )


if get_enable_mentions():
    @client.event
    async def on_message(message: discord.Message) -> None:
        await on_message_handler(message)


def print_intent_help() -> None:
    print()
    print("=" * 50, flush=True)
    print("HATA: Message Content Intent portalda KAPALI", flush=True)
    print()
    print("Etiket (@bot) icin su adimlari yap:", flush=True)
    print("  1. https://discord.com/developers/applications/", flush=True)
    print("  2. Botunu sec -> Bot -> Privileged Gateway Intents", flush=True)
    print("  3. MESSAGE CONTENT INTENT -> AC", flush=True)
    print("  4. Kaydet, botu yeniden baslat", flush=True)
    print()
    print("Simdilik /sor komutu calisir — ENABLE_MENTIONS=0 birak.", flush=True)
    print("Intent acinca .env: ENABLE_MENTIONS=1", flush=True)
    print("=" * 50, flush=True)


def main() -> None:
    token = get_token()
    ok, msg = check_token(token)
    print(msg)
    if not ok:
        print(f"\n.env yolu: {__import__('settings').ENV_PATH}")
        sys.exit(1)

    gid = get_guild_id()
    if not gid.isdigit():
        print()
        print("ONEMLI: .env dosyasina DISCORD_GUILD_ID ekle (komutlar hemen gorunsun)")

    try:
        client.run(token)
    except discord.PrivilegedIntentsRequired:
        print_intent_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
