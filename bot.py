import asyncio
import html
import logging
import os
import time
import uuid
from decimal import Decimal, InvalidOperation
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, Message, PreCheckoutQuery
)
from dotenv import load_dotenv

from database import Database

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_PATH = os.getenv("DB_PATH", "ton_miner.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing. Put it in .env")
if not ADMIN_ID:
    raise RuntimeError("ADMIN_ID is missing. Put it in .env")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("ton-miner")

db = Database(DB_PATH)
bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()


# -------------------- formatting --------------------

def money(v):
    d = Decimal(str(v))
    return f"{d:.6f}".rstrip("0").rstrip(".") or "0"

def safe(s):
    return html.escape(str(s))

def fmt_duration(seconds):
    seconds = max(0, int(seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h:02d}h {m:02d}m"
    return f"{h:02d}:{m:02d}:{s:02d}"

def bar(percent, width=18):
    percent = max(0, min(100, float(percent)))
    filled = round(width * percent / 100)
    return "▰" * filled + "▱" * (width - filled)

def is_admin(uid):
    return uid == ADMIN_ID


# -------------------- mining engine --------------------
# This is an in-app simulated mining ledger.
# It does NOT claim blockchain mining. Real TON is only paid by admin.

def accrue(uid):
    user = db.user(uid)
    machine = db.machine(user["machine_id"]) or db.machine("free")
    now = time.time()
    last = float(user["mining_last_ts"])
    elapsed = max(0.0, now - last)

    rate_seconds = float(machine["hours_per_ton"]) * 3600.0
    earned = elapsed / rate_seconds if rate_seconds > 0 else 0.0

    if earned > 0:
        db.add_uncollected(uid, earned)
        db.set_mining_last(uid, now)
        user["uncollected"] += earned
        user["mining_last_ts"] = now
    return earned

def mining_info(user):
    machine = db.machine(user["machine_id"]) or db.machine("free")
    cycle = float(machine["hours_per_ton"]) * 3600.0
    elapsed = max(0, time.time() - float(user["mining_last_ts"]))
    percent = min(100, elapsed / cycle * 100) if cycle else 0
    remaining = max(0, cycle - elapsed)
    return machine, elapsed, percent, remaining


# -------------------- keyboards --------------------

def home_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏️ MINING CORE", callback_data="mining"),
         InlineKeyboardButton(text="🖥️ MACHINES", callback_data="machines")],
        [InlineKeyboardButton(text="💎 BALANCE", callback_data="balance"),
         InlineKeyboardButton(text="👥 REFERRALS", callback_data="referrals")],
        [InlineKeyboardButton(text="🎯 EARN", callback_data="earn"),
         InlineKeyboardButton(text="👛 WALLET", callback_data="wallet")],
        [InlineKeyboardButton(text="💸 WITHDRAW", callback_data="withdraw"),
         InlineKeyboardButton(text="📜 HISTORY", callback_data="history")],
        [InlineKeyboardButton(text="📊 PROFILE", callback_data="profile")]
    ])

def back_kb(target="home"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ BACK", callback_data=target)]
    ])

def mining_kb(can_collect):
    rows = [[
        InlineKeyboardButton(text="🔄 REFRESH", callback_data="mining"),
        InlineKeyboardButton(text="💎 BALANCE", callback_data="balance")
    ]]
    if can_collect:
        rows.append([InlineKeyboardButton(text="💰 COLLECT", callback_data="collect")])
    rows += [
        [InlineKeyboardButton(text="🖥️ MACHINES", callback_data="machines")],
        [InlineKeyboardButton(text="↩️ MAIN MENU", callback_data="home")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=rows)

def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 STATS", callback_data="a:stats"),
         InlineKeyboardButton(text="💸 PAYOUTS", callback_data="a:payouts")],
        [InlineKeyboardButton(text="📢 BROADCAST", callback_data="a:broadcast"),
         InlineKeyboardButton(text="📢 START CHANNELS", callback_data="a:startch")],
        [InlineKeyboardButton(text="🎯 EARN TASKS", callback_data="a:earn"),
         InlineKeyboardButton(text="🖥️ MACHINES", callback_data="a:machines")],
        [InlineKeyboardButton(text="⚙️ SETTINGS", callback_data="a:settings")]
    ])


# -------------------- required channel gate --------------------

async def member_ok(uid, chat_id):
    try:
        member = await bot.get_chat_member(chat_id, uid)
        return member.status not in ("left", "kicked")
    except Exception:
        return False

async def gate_ok(uid):
    channels = db.required_channels()
    if not channels:
        return True
    for ch in channels:
        if not await member_ok(uid, ch["chat_id"]):
            return False
    return True

def gate_kb():
    rows = []
    for ch in db.required_channels():
        rows.append([InlineKeyboardButton(text=f"📢 {ch['name']}", url=ch["url"])])
    rows.append([InlineKeyboardButton(text="✅ VERIFY & CONTINUE", callback_data="verify")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def finalize_referral(uid):
    u = db.user(uid)
    if not u["referrer"] or not u["wallet"] or not u["channel_verified"]:
        return False
    ref = db.user(int(u["referrer"]))
    if uid in ref["valid_referrals"]:
        return False
    ref["valid_referrals"].append(uid)
    db.save_user(ref)
    try:
        await bot.send_message(
            ref["id"],
            "🎉 <b>REFERRAL VERIFIED</b>\n\n"
            "Your referral completed channel verification and connected a wallet."
        )
    except Exception:
        pass
    return True

async def verify_user(uid):
    if not await gate_ok(uid):
        return False
    u = db.user(uid)
    u["channel_verified"] = True
    db.save_user(u)
    await finalize_referral(uid)
    return True


# -------------------- dashboard --------------------

async def dashboard(message):
    u = db.user(
        message.from_user.id,
        message.from_user.username,
        message.from_user.first_name
    )
    if not await gate_ok(u["id"]):
        await message.answer(
            "🔐 <b>ACCESS VERIFICATION</b>\n\n"
            "Join all required channels/groups, then verify your account.",
            reply_markup=gate_kb()
        )
        return

    await verify_user(u["id"])
    u = db.user(u["id"])

    m = db.machine(u["machine_id"]) or db.machine("free")
    await message.answer(
        "⚡ <b>TON MINER</b>\n"
        "<i>MINING CONTROL CENTER</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 AVAILABLE BALANCE\n<b>{money(u['balance'])} TON</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        f"⛏️ ACTIVE MACHINE  <b>{safe(m['name'])}</b>\n"
        f"⚡ RATE             <b>1 TON / {m['hours_per_ton']} HOURS</b>\n"
        f"👥 REFERRALS       <b>{len(u['valid_referrals'])}/{db.setting('required_referrals')}</b>\n"
        f"👛 WALLET          <b>{'CONNECTED ✅' if u['wallet'] else 'NOT CONNECTED ❌'}</b>\n\n"
        "<i>Open Mining Core for live elapsed-time tracking.</i>",
        reply_markup=home_kb()
    )


@dp.message(CommandStart())
async def start(message: Message):
    u = db.user(message.from_user.id, message.from_user.username, message.from_user.first_name)
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) == 2 and parts[1].startswith("ref_"):
        try:
            rid = int(parts[1][4:])
            if rid != u["id"] and not u["referrer"]:
                u["referrer"] = rid
                ref = db.user(rid)
                if u["id"] not in ref["referrals"]:
                    ref["referrals"].append(u["id"])
                    db.save_user(ref)
                db.save_user(u)
        except ValueError:
            pass

    if not await gate_ok(u["id"]):
        await message.answer(
            "🔐 <b>WELCOME TO TON MINER</b>\n\n"
            "Complete the required channel verification to continue.",
            reply_markup=gate_kb()
        )
        return
    await verify_user(u["id"])
    await dashboard(message)


@dp.callback_query(F.data == "verify")
async def verify_cb(c: CallbackQuery):
    if not await verify_user(c.from_user.id):
        await c.answer("❌ Join every required channel first.", show_alert=True)
        return
    await c.message.edit_text(
        "✅ <b>VERIFICATION COMPLETE</b>\n\nYour account is unlocked.",
        reply_markup=back_kb()
    )
    await c.answer("Verified")


# -------------------- mining --------------------

@dp.callback_query(F.data == "mining")
async def mining_cb(c: CallbackQuery):
    u = db.user(c.from_user.id)
    accrue(u["id"])
    u = db.user(u["id"])
    m, elapsed, percent, remaining = mining_info(u)
    total = int(remaining)
    h, rem = divmod(total, 3600)
    mi, s = divmod(rem, 60)

    await c.message.edit_text(
        "⛏️ <b>MINING CORE</b>\n"
        "<i>LIVE MINING MONITOR</i>\n\n"
        "╭──────────────────────────╮\n"
        f"│ 🖥️ MACHINE  <b>{safe(m['name'])}</b>\n"
        f"│ ⚡ RATE     <b>1 TON / {m['hours_per_ton']} HOURS</b>\n"
        "╰──────────────────────────╯\n\n"
        "💎 <b>READY TO COLLECT</b>\n"
        f"<code>{money(u['uncollected'])} TON</code>\n\n"
        f"{bar(percent)} <b>{percent:.1f}%</b>\n\n"
        f"⏱️ MINING ACTIVE FOR  <b>{fmt_duration(elapsed)}</b>\n"
        f"⏳ NEXT CYCLE IN       <b>{h:02d}:{mi:02d}:{s:02d}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 COLLECTABLE  <b>{money(u['uncollected'])} TON</b>\n"
        f"💎 BALANCE      <b>{money(u['balance'])} TON</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<i>Refresh anytime to update the live elapsed-time calculation.</i>",
        reply_markup=mining_kb(u["uncollected"] > 0)
    )
    await c.answer()


@dp.callback_query(F.data == "collect")
async def collect_cb(c: CallbackQuery):
    u = db.user(c.from_user.id)
    accrue(u["id"])
    u = db.user(u["id"])
    amount = float(u["uncollected"])
    if amount <= 0:
        await c.answer("⏳ Nothing ready to collect.", show_alert=True)
        return

    db.add_balance(u["id"], amount)
    db.set_uncollected(u["id"], 0)
    db.log_tx(u["id"], "mining_collect", amount, "")
    u = db.user(u["id"])

    await c.message.edit_text(
        "💎 <b>COLLECTION COMPLETE</b>\n\n"
        f"Collected: <b>+{money(amount)} TON</b>\n"
        f"Available balance: <b>{money(u['balance'])} TON</b>\n\n"
        "⛏️ Your mining cycle continues automatically.",
        reply_markup=mining_kb(False)
    )
    await c.answer("Collected successfully")


# -------------------- machines + Stars --------------------

@dp.callback_query(F.data == "machines")
async def machines_cb(c: CallbackQuery):
    rows = []
    for m in db.machines():
        price = "FREE" if int(m["stars"]) == 0 else f"{m['stars']} ⭐"
        rows.append([InlineKeyboardButton(
            text=f"{m['name']} • {price}",
            callback_data=f"machine:{m['id']}"
        )])
    rows.append([InlineKeyboardButton(text="↩️ MAIN MENU", callback_data="home")])

    await c.message.edit_text(
        "🖥️ <b>MINING HARDWARE</b>\n"
        "<i>Upgrade your production rate.</i>\n\n"
        "🟢 FREE MINER — 1 TON / 20 HOURS\n"
        "⭐ 50 STARS — 1 TON / 10 HOURS\n"
        "⚡ 100 STARS — 1 TON / 5 HOURS\n"
        "🔥 200 STARS — 1 TON / 1.25 HOURS\n\n"
        "<i>Paid machines use Telegram's official Stars payment system.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await c.answer()


@dp.callback_query(F.data.startswith("machine:"))
async def machine_cb(c: CallbackQuery):
    mid = c.data.split(":", 1)[1]
    m = db.machine(mid)
    if not m:
        await c.answer("Machine not found.", show_alert=True)
        return

    if int(m["stars"]) == 0:
        u = db.user(c.from_user.id)
        accrue(u["id"])
        db.activate_machine(u["id"], mid)
        await c.message.edit_text(
            "🟢 <b>FREE MINER ACTIVATED</b>\n\n"
            "⚡ Rate: <b>1 TON / 20 HOURS</b>\n"
            "⛏️ Mining cycle is now active.",
            reply_markup=back_kb("mining")
        )
        await c.answer()
        return

    await c.message.edit_text(
        f"🖥️ <b>{safe(m['name'])}</b>\n\n"
        f"⭐ Price: <b>{m['stars']} Stars</b>\n"
        f"⚡ Rate: <b>1 TON / {m['hours_per_ton']} HOURS</b>\n\n"
        "Telegram will show the official Stars payment confirmation.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐ BUY FOR {m['stars']} STARS",
                                  callback_data=f"buy:{mid}")],
            [InlineKeyboardButton(text="↩️ BACK", callback_data="machines")]
        ])
    )
    await c.answer()


@dp.callback_query(F.data.startswith("buy:"))
async def buy_cb(c: CallbackQuery):
    mid = c.data.split(":", 1)[1]
    m = db.machine(mid)
    if not m or int(m["stars"]) <= 0:
        await c.answer("Invalid machine.", show_alert=True)
        return

    payload = f"machine|{mid}|{c.from_user.id}|{uuid.uuid4().hex[:10]}"
    await bot.send_invoice(
        chat_id=c.from_user.id,
        title=m["name"],
        description=f"Mining machine: 1 TON / {m['hours_per_ton']} hours",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=m["name"], amount=int(m["stars"]))]
    )
    await c.answer()


@dp.pre_checkout_query()
async def pre_checkout(q: PreCheckoutQuery):
    await q.answer(ok=True)


@dp.message(F.successful_payment)
async def payment_success(message: Message):
    p = message.successful_payment
    parts = p.invoice_payload.split("|")
    if len(parts) != 4 or parts[0] != "machine":
        return
    _, mid, uid, _ = parts
    if int(uid) != message.from_user.id:
        return
    m = db.machine(mid)
    if not m:
        return

    charge = p.telegram_payment_charge_id
    if db.payment_exists(charge):
        return

    db.save_payment(charge, message.from_user.id, mid, int(p.total_amount))
    accrue(message.from_user.id)
    db.activate_machine(message.from_user.id, mid)

    await message.answer(
        "💳 <b>PAYMENT CONFIRMED</b>\n\n"
        f"🖥️ Machine: <b>{safe(m['name'])}</b>\n"
        f"⭐ Paid: <b>{p.total_amount} Stars</b>\n"
        f"⚡ Rate: <b>1 TON / {m['hours_per_ton']} HOURS</b>\n\n"
        "🟢 <b>MINING CYCLE STARTED</b>",
        reply_markup=home_kb()
    )


# -------------------- wallet / referral / earn --------------------

class InputState(StatesGroup):
    wallet = State()
    broadcast = State()

@dp.callback_query(F.data == "wallet")
async def wallet_cb(c: CallbackQuery, state: FSMContext):
    u = db.user(c.from_user.id)
    await state.set_state(InputState.wallet)
    await c.message.edit_text(
        "👛 <b>TON WALLET</b>\n\n"
        f"Current: <code>{safe(u['wallet']) if u['wallet'] else 'NOT CONNECTED'}</code>\n\n"
        "Send your TON wallet address.\n"
        "⚠️ Never send a seed phrase or private key.",
        reply_markup=back_kb()
    )
    await c.answer()


@dp.callback_query(F.data == "referrals")
async def referrals_cb(c: CallbackQuery):
    u = db.user(c.from_user.id)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{u['id']}"
    await c.message.edit_text(
        "👥 <b>REFERRAL NETWORK</b>\n\n"
        f"Valid: <b>{len(u['valid_referrals'])}/{db.setting('required_referrals')}</b>\n"
        f"Invited: <b>{len(u['referrals'])}</b>\n\n"
        f"🔗 <code>{link}</code>\n\n"
        "<i>A referral counts only after the invited user verifies required channels "
        "and connects a wallet.</i>",
        reply_markup=back_kb()
    )
    await c.answer()


@dp.callback_query(F.data == "earn")
async def earn_cb(c: CallbackQuery):
    u = db.user(c.from_user.id)
    rows = []
    for t in db.earn_tasks():
        done = t["id"] in u["earn_done"]
        rows.append([InlineKeyboardButton(
            text=f"{'✅' if done else '🎯'} {t['name']} • +{money(t['reward'])} TON",
            callback_data=f"earn:{t['id']}"
        )])
    rows.append([InlineKeyboardButton(text="↩️ MAIN MENU", callback_data="home")])
    await c.message.edit_text(
        "🎯 <b>EARN CENTER</b>\n\n"
        "Join a listed channel, verify membership and receive the configured TON reward.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await c.answer()


@dp.callback_query(F.data.startswith("earn:"))
async def earn_task_cb(c: CallbackQuery):
    tid = c.data.split(":", 1)[1]
    t = db.earn_task(tid)
    if not t:
        await c.answer("Task not found.", show_alert=True)
        return
    await c.message.edit_text(
        "🎯 <b>EARN TASK</b>\n\n"
        f"📢 Channel: <b>{safe(t['name'])}</b>\n"
        f"💎 Reward: <b>+{money(t['reward'])} TON</b>\n\n"
        "Join the channel and press CHECK JOIN.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 JOIN CHANNEL", url=t["url"])],
            [InlineKeyboardButton(text="✅ CHECK JOIN", callback_data=f"checkearn:{tid}")],
            [InlineKeyboardButton(text="↩️ BACK", callback_data="earn")]
        ])
    )
    await c.answer()


@dp.callback_query(F.data.startswith("checkearn:"))
async def check_earn_cb(c: CallbackQuery):
    tid = c.data.split(":", 1)[1]
    t = db.earn_task(tid)
    u = db.user(c.from_user.id)
    if not t:
        await c.answer("Task removed.", show_alert=True)
        return
    if tid in u["earn_done"]:
        await c.answer("Already rewarded.", show_alert=True)
        return
    if not await member_ok(u["id"], t["chat_id"]):
        await c.answer("❌ Join the channel first.", show_alert=True)
        return

    db.mark_earn_done(u["id"], tid)
    db.add_balance(u["id"], float(t["reward"]))
    db.log_tx(u["id"], "channel_earn", float(t["reward"]), tid)
    u = db.user(u["id"])

    await c.message.edit_text(
        "🎉 <b>TASK COMPLETED</b>\n\n"
        f"Reward: <b>+{money(t['reward'])} TON</b>\n"
        f"Balance: <b>{money(u['balance'])} TON</b>",
        reply_markup=back_kb()
    )
    await c.answer("Reward credited")


@dp.message(InputState.wallet)
async def wallet_input(message: Message, state: FSMContext):
    address = (message.text or "").strip()
    if len(address) < 20 or " " in address:
        await message.answer("❌ Send only a valid TON wallet address.")
        return
    u = db.user(message.from_user.id)
    u["wallet"] = address
    db.save_user(u)
    await state.clear()
    await finalize_referral(u["id"])
    await message.answer(
        "👛 <b>WALLET CONNECTED</b>\n\n"
        f"Address: <code>{safe(address)}</code>\n\n"
        "Wallet connection completed. Your referral status has been checked.",
        reply_markup=home_kb()
    )


# -------------------- balance / history / profile --------------------

@dp.callback_query(F.data == "balance")
async def balance_cb(c: CallbackQuery):
    u = db.user(c.from_user.id)
    accrue(u["id"])
    u = db.user(u["id"])
    await c.message.edit_text(
        "💎 <b>BALANCE CENTER</b>\n\n"
        f"Available: <b>{money(u['balance'])} TON</b>\n"
        f"Ready to collect: <b>{money(u['uncollected'])} TON</b>\n"
        f"Minimum withdrawal: <b>{money(db.setting('minimum_withdrawal'))} TON</b>",
        reply_markup=back_kb()
    )
    await c.answer()


@dp.callback_query(F.data == "history")
async def history_cb(c: CallbackQuery):
    rows = db.transactions(c.from_user.id, 12)
    body = "\n".join(
        f"• {safe(x['kind']).upper()} — <b>{money(x['amount'])} TON</b>"
        for x in rows
    ) or "No transactions yet."
    await c.message.edit_text("📜 <b>HISTORY</b>\n\n" + body, reply_markup=back_kb())
    await c.answer()


@dp.callback_query(F.data == "profile")
async def profile_cb(c: CallbackQuery):
    u = db.user(c.from_user.id)
    m = db.machine(u["machine_id"]) or db.machine("free")
    await c.message.edit_text(
        "📊 <b>MINER PROFILE</b>\n\n"
        f"ID: <code>{u['id']}</code>\n"
        f"Balance: <b>{money(u['balance'])} TON</b>\n"
        f"Collectable: <b>{money(u['uncollected'])} TON</b>\n"
        f"Valid referrals: <b>{len(u['valid_referrals'])}</b>\n"
        f"Machine: <b>{safe(m['name'])}</b>\n"
        f"Wallet: <b>{'CONNECTED ✅' if u['wallet'] else 'NOT CONNECTED ❌'}</b>",
        reply_markup=back_kb()
    )
    await c.answer()


# -------------------- withdrawal --------------------

@dp.callback_query(F.data == "withdraw")
async def withdraw_cb(c: CallbackQuery):
    u = db.user(c.from_user.id)
    accrue(u["id"])
    u = db.user(u["id"])
    minimum = float(db.setting("minimum_withdrawal"))

    if u["withdrawal_id"]:
        msg = "⏳ <b>WITHDRAWAL IN PROGRESS</b>\n\nYou already have an active request."
        kb = back_kb()
    elif not u["wallet"]:
        msg = "❌ <b>WITHDRAWAL LOCKED</b>\n\n<b>1/4</b> Connect your TON wallet first."
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="👛 CONNECT WALLET", callback_data="wallet")],
            [InlineKeyboardButton(text="↩️ BACK", callback_data="home")]
        ])
    elif len(u["valid_referrals"]) < int(db.setting("required_referrals")):
        msg = (
            "❌ <b>WITHDRAWAL LOCKED</b>\n\n"
            f"<b>2/4</b> Valid referrals: <b>{len(u['valid_referrals'])}/"
            f"{db.setting('required_referrals')}</b>"
        )
        kb = back_kb()
    elif float(u["balance"]) < minimum:
        msg = (
            "❌ <b>WITHDRAWAL LOCKED</b>\n\n"
            f"<b>3/4</b> Minimum: <b>{money(minimum)} TON</b>\n"
            f"Available: <b>{money(u['balance'])} TON</b>"
        )
        kb = back_kb()
    elif bool(db.setting("machine_required")) and u["machine_id"] == "free":
        msg = (
            "❌ <b>WITHDRAWAL LOCKED</b>\n\n"
            "<b>4/4</b> A paid machine purchase is required before payout."
        )
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🖥️ BUY MACHINE", callback_data="machines")],
            [InlineKeyboardButton(text="↩️ BACK", callback_data="home")]
        ])
    else:
        wid = uuid.uuid4().hex[:10]
        amount = float(u["balance"])
        db.create_withdrawal(wid, u["id"], amount, u["wallet"])
        db.set_withdrawal_id(u["id"], wid)

        msg = (
            "💸 <b>WITHDRAWAL REQUEST SUBMITTED</b>\n\n"
            f"Amount: <b>{money(amount)} TON</b>\n"
            f"Wallet: <code>{safe(u['wallet'])}</code>\n\n"
            "Status: <b>⏳ PENDING ADMIN REVIEW</b>\n\n"
            "<i>Please wait for your funds to arrive.</i>"
        )
        kb = back_kb()

        try:
            await bot.send_message(
                ADMIN_ID,
                "🚨 <b>NEW TON PAYOUT REQUEST</b>\n\n"
                f"User: <code>{u['id']}</code>\n"
                f"Amount: <b>{money(amount)} TON</b>\n"
                f"Wallet: <code>{safe(u['wallet'])}</code>\n"
                f"Request: <code>{wid}</code>\n\n"
                "<i>Complete the real TON transfer externally, then mark the request paid.</i>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ APPROVE", callback_data=f"wd:approve:{wid}")],
                    [InlineKeyboardButton(text="❌ REJECT", callback_data=f"wd:reject:{wid}")],
                    [InlineKeyboardButton(text="💎 MARK PAID", callback_data=f"wd:paid:{wid}")]
                ])
            )
        except Exception as e:
            log.exception("Could not notify admin: %s", e)

    await c.message.edit_text(msg, reply_markup=kb)
    await c.answer()


@dp.callback_query(F.data.startswith("wd:"))
async def wd_cb(c: CallbackQuery):
    if not is_admin(c.from_user.id):
        await c.answer("Admin only.", show_alert=True)
        return
    _, action, wid = c.data.split(":")
    w = db.withdrawal(wid)
    if not w:
        await c.answer("Request not found.", show_alert=True)
        return

    u = db.user(w["user_id"])

    if action == "approve":
        db.set_withdrawal_status(wid, "approved")
        await bot.send_message(
            u["id"],
            "✅ <b>WITHDRAWAL APPROVED</b>\n\n"
            f"Amount: <b>{money(w['amount'])} TON</b>\n\n"
            "Admin is processing your payout.\n"
            "<i>Please wait for your funds to arrive.</i>"
        )
    elif action == "reject":
        db.set_withdrawal_status(wid, "rejected")
        db.set_withdrawal_id(u["id"], None)
        await bot.send_message(
            u["id"],
            "❌ <b>WITHDRAWAL REJECTED</b>\n\nYour request was rejected by admin."
        )
    elif action == "paid":
        # Admin confirms that the real external TON transfer has been completed.
        db.set_withdrawal_status(wid, "paid")
        db.subtract_balance(u["id"], float(w["amount"]))
        db.set_withdrawal_id(u["id"], None)
        await bot.send_message(
            u["id"],
            "💎 <b>PAYMENT COMPLETED</b>\n\n"
            f"Amount: <b>{money(w['amount'])} TON</b>\n\n"
            "Your payout has been marked as completed."
        )

    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer("Updated")


# -------------------- admin panel --------------------

@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Admin only.")
        return
    await message.answer(
        "⚙️ <b>TON MINER ADMIN CENTER</b>\n\n"
        "Manage payouts, channels, earn tasks, machines, settings and broadcasts.",
        reply_markup=admin_kb()
    )


@dp.callback_query(F.data.startswith("a:"))
async def admin_panel(c: CallbackQuery, state: FSMContext):
    if not is_admin(c.from_user.id):
        await c.answer("Admin only.", show_alert=True)
        return
    action = c.data.split(":", 1)[1]

    if action == "stats":
        await c.message.edit_text(
            "📊 <b>SYSTEM STATS</b>\n\n"
            f"Users: <b>{db.count_users()}</b>\n"
            f"Pending payouts: <b>{db.count_active_withdrawals()}</b>\n"
            f"Start channels: <b>{len(db.required_channels())}</b>\n"
            f"Earn tasks: <b>{len(db.earn_tasks())}</b>\n"
            f"Machines: <b>{len(db.machines())}</b>\n"
            f"Minimum withdrawal: <b>{money(db.setting('minimum_withdrawal'))} TON</b>\n"
            f"Referral requirement: <b>{db.setting('required_referrals')}</b>\n"
            f"Machine gate: <b>{'ON' if db.setting('machine_required') else 'OFF'}</b>",
            reply_markup=admin_kb()
        )

    elif action == "payouts":
        rows = db.active_withdrawals(10)
        body = "\n\n".join(
            f"<code>{w['id']}</code> • <b>{money(w['amount'])} TON</b>\n"
            f"User <code>{w['user_id']}</code> • {safe(w['status'])}"
            for w in rows
        ) or "No active payout requests."
        await c.message.edit_text(
            "💸 <b>PAYOUT QUEUE</b>\n\n" + body,
            reply_markup=admin_kb()
        )

    elif action == "startch":
        body = "\n".join(
            f"• <code>{safe(x['chat_id'])}</code> — {safe(x['name'])}"
            for x in db.required_channels()
        ) or "No required channels."
        await c.message.edit_text(
            "📢 <b>START CHANNELS</b>\n\n"
            f"{body}\n\n"
            "<code>/addstart @channel | Name</code>\n"
            "<code>/delstart @channel</code>",
            reply_markup=admin_kb()
        )

    elif action == "earn":
        body = "\n".join(
            f"• <code>{x['id']}</code> — {safe(x['name'])} — +{money(x['reward'])} TON"
            for x in db.earn_tasks()
        ) or "No earn tasks."
        await c.message.edit_text(
            "🎯 <b>EARN TASKS</b>\n\n"
            f"{body}\n\n"
            "<code>/addearn @channel | Name | 0.10</code>\n"
            "<code>/delearntask ID</code>",
            reply_markup=admin_kb()
        )

    elif action == "machines":
        body = "\n".join(
            f"• <code>{x['id']}</code> — {safe(x['name'])} — "
            f"{x['stars']} ⭐ — 1 TON/{x['hours_per_ton']}h"
            for x in db.machines()
        )
        await c.message.edit_text(
            "🖥️ <b>MACHINE CONTROL</b>\n\n"
            f"{body}\n\n"
            "<code>/addmachine Name | Stars | Hours</code>\n"
            "<code>/delmachine ID</code>",
            reply_markup=admin_kb()
        )

    elif action == "settings":
        await c.message.edit_text(
            "⚙️ <b>SETTINGS</b>\n\n"
            f"Minimum withdrawal: <b>{money(db.setting('minimum_withdrawal'))} TON</b>\n"
            f"Required referrals: <b>{db.setting('required_referrals')}</b>\n"
            f"Machine purchase gate: <b>{'ON' if db.setting('machine_required') else 'OFF'}</b>\n\n"
            "<code>/setmin 5</code>\n"
            "<code>/setrefs 5</code>\n"
            "<code>/setmachinegate on</code>",
            reply_markup=admin_kb()
        )

    elif action == "broadcast":
        await state.set_state(InputState.broadcast)
        await c.message.edit_text(
            "📢 <b>BROADCAST MODE</b>\n\n"
            "Send the message you want to broadcast to all registered users.",
            reply_markup=admin_kb()
        )

    await c.answer()


# -------------------- admin commands --------------------

@dp.message(Command("setmin"))
async def setmin(message: Message):
    if not is_admin(message.from_user.id): return
    try:
        v = float(message.text.split()[1])
        if v <= 0: raise ValueError
        db.set_setting("minimum_withdrawal", v)
        await message.answer(f"✅ Minimum withdrawal: <b>{money(v)} TON</b>")
    except Exception:
        await message.answer("Usage: /setmin 5")

@dp.message(Command("setrefs"))
async def setrefs(message: Message):
    if not is_admin(message.from_user.id): return
    try:
        v = int(message.text.split()[1])
        if v < 0: raise ValueError
        db.set_setting("required_referrals", v)
        await message.answer(f"✅ Referral requirement: <b>{v}</b>")
    except Exception:
        await message.answer("Usage: /setrefs 5")

@dp.message(Command("setmachinegate"))
async def setgate(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split()
    if len(args) != 2 or args[1].lower() not in ("on", "off"):
        await message.answer("Usage: /setmachinegate on")
        return
    on = args[1].lower() == "on"
    db.set_setting("machine_required", on)
    await message.answer(f"✅ Machine gate: <b>{'ON' if on else 'OFF'}</b>")

@dp.message(Command("addstart"))
async def addstart(message: Message):
    if not is_admin(message.from_user.id): return
    raw = message.text.split(maxsplit=1)
    if len(raw) < 2 or "|" not in raw[1]:
        await message.answer("Usage: /addstart @channel | Name")
        return
    target, name = [x.strip() for x in raw[1].split("|", 1)]
    chat_id = int(target) if target.startswith("-100") else target
    url = target if target.startswith("http") else f"https://t.me/{target.lstrip('@')}"
    db.add_required_channel(chat_id, name, url)
    await message.answer("✅ Start channel added.")

@dp.message(Command("delstart"))
async def delstart(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /delstart @channel")
        return
    db.delete_required_channel(args[1].strip())
    await message.answer("✅ Start channel removed.")

@dp.message(Command("addearn"))
async def addearn(message: Message):
    if not is_admin(message.from_user.id): return
    raw = message.text.split(maxsplit=1)
    if len(raw) < 2 or raw[1].count("|") < 2:
        await message.answer("Usage: /addearn @channel | Name | 0.10")
        return
    target, name, reward = [x.strip() for x in raw[1].split("|", 2)]
    try:
        reward = float(reward)
        if reward <= 0: raise ValueError
    except Exception:
        await message.answer("Invalid reward.")
        return
    chat_id = int(target) if target.startswith("-100") else target
    url = target if target.startswith("http") else f"https://t.me/{target.lstrip('@')}"
    tid = uuid.uuid4().hex[:6]
    db.add_earn_task(tid, chat_id, name, url, reward)
    await message.answer(f"✅ Earn task added. ID: <code>{tid}</code>")

@dp.message(Command("delearntask"))
async def delearntask(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /delearntask ID")
        return
    db.delete_earn_task(args[1].strip())
    await message.answer("✅ Earn task removed.")

@dp.message(Command("addmachine"))
async def addmachine(message: Message):
    if not is_admin(message.from_user.id): return
    raw = message.text.split(maxsplit=1)
    if len(raw) < 2 or raw[1].count("|") < 2:
        await message.answer("Usage: /addmachine Name | Stars | Hours")
        return
    name, stars, hours = [x.strip() for x in raw[1].split("|", 2)]
    try:
        stars, hours = int(stars), float(hours)
        if stars < 0 or hours <= 0: raise ValueError
    except Exception:
        await message.answer("Invalid machine values.")
        return
    mid = "m" + uuid.uuid4().hex[:6]
    db.add_machine(mid, name, stars, hours)
    await message.answer(f"✅ Machine added: <code>{mid}</code>")

@dp.message(Command("delmachine"))
async def delmachine(message: Message):
    if not is_admin(message.from_user.id): return
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        await message.answer("Usage: /delmachine ID")
        return
    if args[1].strip() == "free":
        await message.answer("❌ FREE MINER cannot be removed.")
        return
    db.delete_machine(args[1].strip())
    await message.answer("✅ Machine removed.")

@dp.message(Command("broadcast"))
async def broadcast_cmd(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id): return
    raw = message.text.split(maxsplit=1)
    if len(raw) == 2:
        await broadcast(raw[1], message)
    else:
        await state.set_state(InputState.broadcast)
        await message.answer("📢 Send the broadcast message now.")

async def broadcast(text, admin_message):
    sent = 0
    for uid in db.user_ids():
        try:
            await bot.send_message(uid, text)
            sent += 1
        except Exception:
            pass
    await admin_message.answer(f"📢 <b>BROADCAST COMPLETE</b>\n\nDelivered: <b>{sent}</b> users.")

@dp.message(InputState.broadcast)
async def broadcast_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.clear()
    await broadcast(message.text or "", message)


# -------------------- navigation --------------------

@dp.callback_query(F.data == "home")
async def home_cb(c: CallbackQuery):
    await c.message.delete()
    await dashboard(c.message)
    await c.answer()


@dp.message()
async def fallback(message: Message):
    await message.answer("Use the buttons below.", reply_markup=home_kb())


async def main():
    log.info("TON MINER online")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
