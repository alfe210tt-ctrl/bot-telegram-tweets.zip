"""Bot de Telegram: pega un link de X/Twitter y devuelve la imagen del tweet con fondo.
Uso:  TELEGRAM_BOT_TOKEN=xxxx python bot.py"""
import asyncio, base64, logging, os, re
from datetime import datetime

import httpx
from playwright.async_api import async_playwright
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from render import render

logging.basicConfig(level=logging.INFO)
logging.getLogger("httpx").setLevel(logging.WARNING)  # evita que el token salga en los logs
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
URL_RE = re.compile(r"(?:x|twitter|fxtwitter|vxtwitter|fixupx)\.com/[^/\s]+/status/(\d+)", re.I)
UA = {"User-Agent": "Mozilla/5.0"}
MESES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
FONDOS = ["🟣 Morado", "🌸 Rosa", "🔵 Azul", "🟢 Verde", "🟠 Naranja", "🌑 Oscuro", "⚫ Negro", "⚪ Blanco"]
DEFAULT_BG = int(os.environ.get("DEFAULT_BG", "0"))  # fondo por defecto (0 a 7); se puede cambiar en Railway
TEMAS = {"light": "☀️ Claro", "dark": "🌙 Oscuro"}
DEFAULT_THEME = os.environ.get("DEFAULT_THEME", "light")  # light u dark
sem = asyncio.Semaphore(2)  # máximo 2 imágenes a la vez


def fmt(n):
    n = int(n or 0)
    if n >= 1_000_000: return f"{n/1_000_000:.1f}M".replace(".0M", "M")
    if n >= 1_000: return f"{n/1_000:.1f}K".replace(".0K", "K")
    return str(n)


async def data_url(c, url):
    r = await c.get(url)
    r.raise_for_status()
    ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
    return f"data:{ctype};base64," + base64.b64encode(r.content).decode()


async def fetch_tweet(tid):
    async with httpx.AsyncClient(headers=UA, timeout=20, follow_redirects=True) as c:
        r = await c.get(f"https://api.fxtwitter.com/i/status/{tid}")
        t = r.json().get("tweet")
        if not t:
            return None
        a = t["author"]
        media_url = ""
        m = t.get("media") or {}
        if m.get("photos"):
            media_url = m["photos"][0]["url"]
        elif m.get("videos"):
            media_url = m["videos"][0].get("thumbnail_url", "")
        ts = t.get("created_timestamp")
        dt = datetime.fromtimestamp(ts) if ts else datetime.now()
        ver = a.get("verification")
        verified = bool(ver.get("verified")) if isinstance(ver, dict) else bool(ver or a.get("verified"))
        d = {
            "name": a.get("name", ""), "handle": a.get("screen_name", ""),
            "text": re.sub(r"\s*https://t\.co/\w+", "", t.get("text", "")).strip(),
            "date": f"{dt.day} {MESES[dt.month-1]}. {dt.year} · {dt:%H:%M}",
            "rep": fmt(t.get("replies")), "rt": fmt(t.get("retweets")),
            "lk": fmt(t.get("likes")), "vw": fmt(t.get("views")),
            "verified": verified, "avatar": "", "media": "",
        }
        for key, url in (("avatar", (a.get("avatar_url") or "").replace("_normal", "_400x400")), ("media", media_url)):
            if url:
                try: d[key] = await data_url(c, url)
                except Exception: logging.warning("no se pudo bajar %s", key)
        return d


async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Mándame el link de un tweet y te devuelvo la imagen.\n/fondo → elige el color del fondo.\n/tema → tarjeta clara u oscura.\n/limpio → activa o desactiva el modo limpio (sin fecha ni estadísticas).")


async def limpio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.chat_data["clean"] = not ctx.chat_data.get("clean", False)
    await update.message.reply_text("Modo limpio: " + ("activado ✅" if ctx.chat_data["clean"] else "desactivado"))


async def fondo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    botones = [InlineKeyboardButton(n, callback_data=f"bg:{i}") for i, n in enumerate(FONDOS)]
    teclado = InlineKeyboardMarkup([botones[:4], botones[4:]])
    await update.message.reply_text("Elige el color del fondo:", reply_markup=teclado)


async def on_bg(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    i = int(q.data.split(":")[1])
    ctx.chat_data["bg"] = i
    await q.answer("Fondo cambiado")
    await q.edit_message_text(f"Fondo elegido: {FONDOS[i]} ✅\nAhora mándame un link de tweet.")


async def tema(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    botones = [InlineKeyboardButton(n, callback_data=f"th:{k}") for k, n in TEMAS.items()]
    await update.message.reply_text("Elige el tema de la tarjeta:", reply_markup=InlineKeyboardMarkup([botones]))


async def on_theme(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    k = q.data.split(":")[1]
    if k not in TEMAS:
        return await q.answer()
    ctx.chat_data["theme"] = k
    await q.answer("Tema cambiado")
    await q.edit_message_text(f"Tema elegido: {TEMAS[k]} ✅\nAhora mándame un link de tweet.")


async def on_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    m = URL_RE.search(update.message.text or "")
    if not m:
        return
    wait = await update.message.reply_text("Generando imagen…")
    try:
        async with sem:
            d = await fetch_tweet(m.group(1))
            if not d:
                return await wait.edit_text("No pude leer ese tweet (borrado, privado o el servicio no responde).")
            d["clean"] = ctx.chat_data.get("clean", False)
            d["bg"] = ctx.chat_data.get("bg", DEFAULT_BG)
            d["theme"] = ctx.chat_data.get("theme", DEFAULT_THEME)
            # Se abre el navegador solo mientras se genera la imagen (ahorra memoria en hostings gratis)
            browser = await ctx.application.bot_data["pw"].chromium.launch(args=["--no-sandbox"])
            try:
                png = await render(browser, d)
            finally:
                await browser.close()
        await update.message.reply_photo(png)
        await update.message.reply_document(png, filename="tweet.png")
        await wait.delete()
    except Exception:
        logging.exception("error")
        await wait.edit_text("Ocurrió un error generando la imagen. Intenta de nuevo.")


async def post_init(app):
    app.bot_data["pw"] = await async_playwright().start()


async def post_shutdown(app):
    await app.bot_data["pw"].stop()


if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).post_init(post_init).post_shutdown(post_shutdown).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("limpio", limpio))
    app.add_handler(CommandHandler("fondo", fondo))
    app.add_handler(CommandHandler("tema", tema))
    app.add_handler(CallbackQueryHandler(on_theme, pattern=r"^th:(light|dark)$"))
    app.add_handler(CallbackQueryHandler(on_bg, pattern=r"^bg:\d$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()
