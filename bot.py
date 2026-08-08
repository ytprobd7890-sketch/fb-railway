#!/usr/bin/env python3
"""
FB Account Creator — Telegram Bot Controller
Bot দিয়ে পুরো কন্ট্রোল। Commands দিয়ে manage করো।
ratman4080 build
"""

import asyncio
import logging
import sys
import time
from dataclasses import dataclass, field
from typing import Set, Optional

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from config import Config
from proxy_fetcher import ProxyFetcher
from creator import FBCreator

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("fb-bot")


# ============================================================
# BOT STATE
# ============================================================
@dataclass
class BotState:
    created: int = 0
    errors: int = 0
    last_account: Optional[dict] = None
    active_tasks: Set[asyncio.Task] = field(default_factory=set)
    started_at: float = field(default_factory=time.time)
    semaphore: asyncio.Semaphore = field(default_factory=lambda: asyncio.Semaphore(3))


def format_result(r: dict) -> str:
    return (
        f"✅ Account Created\n"
        f"📧 {r['email']}\n"
        f"🔑 {r['password']}\n"
        f"👤 {r['first_name']} {r['last_name']}\n"
        f"⚧ {r['gender']}\n"
        f"🎂 {r['birth_date']}\n"
        f"✉️ Verified: {'Yes' if r.get('email_verified') else 'No'}\n"
        f"🆔 c_user: {r.get('c_user', 'N/A')}"
    )


# ============================================================
# POST INIT
# ============================================================
async def post_init(app: Application):
    cfg: Config = app.bot_data["cfg"]
    pf = ProxyFetcher(cfg)

    log.info("Initial proxy fetch...")
    await pf.refresh()
    log.info(f"Proxy pool: {pf.count()}")

    app.bot_data["pf"] = pf
    app.bot_data["state"] = BotState(
        semaphore=asyncio.Semaphore(cfg.max_concurrent)
    )

    task = asyncio.create_task(pf.auto_refresh_loop())
    app.bot_data["refresh_task"] = task
    log.info("Bot initialized. Ready for commands.")


# ============================================================
# CREATE TASK WRAPPER
# ============================================================
async def create_and_report(
    bot_app: Application,
    chat_id: int,
    creator: FBCreator,
    state: BotState,
):
    cfg: Config = bot_app.bot_data["cfg"]
    bot = bot_app.bot

    async with state.semaphore:
        try:
            result = await creator.create_account()
            if result:
                state.created += 1
                state.last_account = result
                msg = format_result(result)
                try:
                    await bot.send_message(chat_id=chat_id, text=msg)
                except Exception as e:
                    log.error(f"Send result fail: {e}")
            else:
                state.errors += 1
                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        text="❌ Account creation failed — check logs"
                    )
                except Exception:
                    pass
        except asyncio.CancelledError:
            log.info("Create task cancelled")
            raise
        except Exception as e:
            state.errors += 1
            log.error(f"Create task error: {e}")
            try:
                await bot.send_message(
                    chat_id=chat_id,
                    text=f"❌ Error: {e}"
                )
            except Exception:
                pass


# ============================================================
# COMMANDS
# ============================================================

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "🐀 FB Creator Bot — ratman4080\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "Commands:\n"
        "/create [N] — N টা account বানাও (default 1, max 10)\n"
        "/status — stats দেখো\n"
        "/proxy — proxy pool status\n"
        "/stop — সব pending task cancel করো\n"
        "/help — এই menu আবার দেখো\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        "nest is warm. teeth are sharp."
    )
    await update.message.reply_text(text)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start_cmd(update, context)


async def create_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg: Config = context.application.bot_data["cfg"]
    pf: ProxyFetcher = context.application.bot_data["pf"]
    state: BotState = context.application.bot_data["state"]

    if pf.count() == 0 and not cfg.get_static_proxies():
        await update.message.reply_text(
            "⚠️ Proxy pool empty! Wait for refresh or set PROXIES env."
        )
        return

    count = 1
    if context.args:
        try:
            count = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Usage: /create [N] — N must be a number")
            return

    count = max(1, min(count, 10))

    active = len([t for t in state.active_tasks if not t.done()])
    if active >= 15:
        await update.message.reply_text(
            f"⏳ Too many active tasks ({active}). Wait for some to finish."
        )
        return

    await update.message.reply_text(
        f"🚀 Queued {count} account creation(s).\n"
        f"Active tasks: {active}\n"
        f"Max concurrent: {cfg.max_concurrent}"
    )

    creator = FBCreator(cfg, pf)
    chat_id = update.effective_chat.id

    for _ in range(count):
        task = asyncio.create_task(
            create_and_report(context.application, chat_id, creator, state)
        )
        state.active_tasks.add(task)
        task.add_done_callback(state.active_tasks.discard)


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data["state"]
    cfg: Config = context.application.bot_data["cfg"]

    active = len([t for t in state.active_tasks if not t.done()])
    uptime = int(time.time() - state.started_at)
    hours, rem = divmod(uptime, 3600)
    mins, secs = divmod(rem, 60)

    last_info = "N/A"
    if state.last_account:
        la = state.last_account
        last_info = f"{la['email']} ({la['first_name']} {la['last_name']})"

    text = (
        f"📊 Bot Status\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Created: {state.created}\n"
        f"❌ Errors: {state.errors}\n"
        f"🔄 Active tasks: {active}\n"
        f"⏱️ Uptime: {hours}h {mins}m {secs}s\n"
        f"🔧 Max concurrent: {cfg.max_concurrent}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Last account: {last_info}"
    )
    await update.message.reply_text(text)


async def proxy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pf: ProxyFetcher = context.application.bot_data["pf"]
    cfg: Config = context.application.bot_data["cfg"]

    age = int(time.time() - pf._last_fetch) if pf._last_fetch else 0
    next_refresh = max(0, cfg.proxy_refresh_interval - age)

    text = (
        f"🌐 Proxy Pool Status\n"
        f"━━━━━━━━━━━━━━━━━━━━━━\n"
        f"Pool size: {pf.count()}\n"
        f"Last refresh: {age}s ago\n"
        f"Next refresh: {next_refresh}s\n"
        f"Auto-fetch: {'ON' if cfg.auto_fetch_proxies else 'OFF'}\n"
        f"Static proxies: {len(cfg.get_static_proxies())}\n"
        f"Validate timeout: {cfg.proxy_validate_timeout}s"
    )
    await update.message.reply_text(text)


async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state: BotState = context.application.bot_data["state"]

    cancelled = 0
    for task in list(state.active_tasks):
        if not task.done():
            task.cancel()
            cancelled += 1

    await update.message.reply_text(
        f"🛑 Cancelled {cancelled} pending task(s).\n"
        f"Running tasks will stop at next safe point."
    )


# ============================================================
# MAIN
# ============================================================
def main():
    cfg = Config()

    if not cfg.tg_bot_token:
        log.error("TG_BOT_TOKEN not set. Exiting.")
        sys.exit(1)

    if not cfg.tg_chat_id:
        log.error("TG_CHAT_ID not set. Exiting.")
        sys.exit(1)

    app = (
        Application.builder()
        .token(cfg.tg_bot_token)
        .post_init(post_init)
        .build()
    )

    app.bot_data["cfg"] = cfg

    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("create", create_cmd))
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("proxy", proxy_cmd))
    app.add_handler(CommandHandler("stop", stop_cmd))

    log.info("=== FB Creator Bot starting ===")
    log.info(f"Chat ID: {cfg.tg_chat_id}")
    log.info(f"Max concurrent: {cfg.max_concurrent}")
    log.info(f"FB endpoint: {cfg.fb_base}")

    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
