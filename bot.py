import asyncio
import json
import os
import time
import uuid
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
    LabeledPrice, Message, PreCheckoutQuery
)
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DB_FILE = Path(os.getenv("DB_FILE", "data.json"))

if not TOKEN or not ADMIN_ID:
    raise RuntimeError("BOT_TOKEN and ADMIN_ID are required in .env")

DEFAULT = {
    "settings": {
        "required_referrals": 5,
        "min_withdrawal": 5.0,
        "machine_gate": True,
        "required_channels": []
    },
    "machines": [
        {"id":"free","name":"FREE MINER","stars":0,"hours":20.0},
        {"id":"m50","name":"50 ⭐ TURBO","stars":50,"hours":10.0},
        {"id":"m100","name":"100 ⭐ HYPER","stars":100,"hours":5.0},
        {"id":"m200","name":"200 ⭐ ULTRA","stars":200,"hours":1.25}
    ],
    "earn_tasks": [],
    "users": {},
    "withdrawals": {},
    "transactions": [],
    "stars_payments": {}
}

def load():
    if not DB_FILE.exists():
        DB_FILE.write_text(json.dumps(DEFAULT, indent=2), encoding="utf-8")
        return json.loads(json.dumps(DEFAULT))
    try:
        d=json.loads(DB_FILE.read_text(encoding="utf-8"))
    except Exception:
        d=json.loads(json.dumps(DEFAULT))
    for k,v in DEFAULT.items():
        d.setdefault(k, v)
    for k,v in DEFAULT["settings"].items():
        d["settings"].setdefault(k, v)
    return d

db=load()

def save():
    tmp=DB_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(db, indent=2), encoding="utf-8")
    tmp.replace(DB_FILE)

def user(uid, username=None, first_name=None):
    k=str(uid)
    if k not in db["users"]:
        db["users"][k]={
            "id":uid,"username":username or "","first_name":first_name or "",
            "balance":0.0,"wallet":"","verified":False,
            "referrer":None,"referrals":[],"valid_referrals":[],
            "machine_id":"free","machine_started":time.time(),
            "earn_done":[],"withdrawal_id":None
        }
        save()
    u=db["users"][k]
    if username is not None: u["username"]=username
    if first_name is not None: u["first_name"]=first_name
    return u

def fmt(x):
    return f"{float(x):.6f}".rstrip("0").rstrip(".") or "0"

def get_machine(mid):
    return next((m for m in db["machines"] if m["id"]==mid), None)

def accrue(uid):
    u=user(uid)
    m=get_machine(u["machine_id"]) or get_machine("free")
    now=time.time()
    elapsed=max(0, now-float(u["machine_started"]))
    mined=elapsed/(float(m["hours"])*3600.0)
    if mined>0:
        u["balance"]+=mined
        u["machine_started"]=now
        db["transactions"].append({
            "id":uuid.uuid4().hex[:10],
            "user_id":uid,"type":"mining","amount":mined,
            "machine":m["id"],"time":now
        })
        save()
    return mined

def bar(p, n=16):
    p=max(0,min(1,p))
    x=int(p*n)
    return "▰"*x+"▱"*(n-x)

def menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⛏️ MINING",callback_data="mining"),
         InlineKeyboardButton(text="🖥️ MACHINES",callback_data="machines")],
        [InlineKeyboardButton(text="💎 BALANCE",callback_data="balance"),
         InlineKeyboardButton(text="👥 REFERRALS",callback_data="referrals")],
        [InlineKeyboardButton(text="🎯 EARN",callback_data="earn"),
         InlineKeyboardButton(text="👛 WALLET",callback_data="wallet")],
        [InlineKeyboardButton(text="💸 WITHDRAW",callback_data="withdraw"),
         InlineKeyboardButton(text="📜 HISTORY",callback_data="history")],
        [InlineKeyboardButton(text="📊 PROFILE",callback_data="profile")],
    ])

def back():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="↩️ MAIN MENU",callback_data="home")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 STATS",callback_data="adm:stats"),
         InlineKeyboardButton(text="💸 WITHDRAWALS",callback_data="adm:withdrawals")],
        [InlineKeyboardButton(text="📢 BROADCAST",callback_data="adm:broadcast"),
         InlineKeyboardButton(text="📢 CHANNELS",callback_data="adm:channels")],
        [InlineKeyboardButton(text="🎯 EARN TASKS",callback_data="adm:tasks"),
         InlineKeyboardButton(text="🖥️ MACHINES",callback_data="adm:machines")],
        [InlineKeyboardButton(text="⚙️ SETTINGS",callback_data="adm:settings")]
    ])

def required_kb():
    rows=[]
    for c in db["settings"]["required_channels"]:
        rows.append([InlineKeyboardButton(text=f"📢 {c['name']}",url=c["url"])])
    rows.append([InlineKeyboardButton(text="✅ VERIFY & CONTINUE",callback_data="verify")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

async def member(uid, target):
    try:
        m=await bot.get_chat_member(target, uid)
        return m.status not in ("left","kicked")
    except Exception:
        return False

async def all_required_joined(uid):
    for c in db["settings"]["required_channels"]:
        if not await member(uid,c["chat_id"]):
            return False
    return True

async def validate_access(uid):
    u=user(uid)
    ok=await all_required_joined(uid)
    if ok:
        u["verified"]=True
        # Referral is valid only after required join + wallet.
        if u["wallet"] and u["referrer"]:
            ref=user(u["referrer"])
            if uid not in ref["valid_referrals"]:
                ref["valid_referrals"].append(uid)
                save()
                try:
                    await bot.send_message(
                        ref["id"],
                        "🎉 <b>REFERRAL VERIFIED</b>\n\n"
                        "Your referral completed verification and connected a wallet."
                    )
                except Exception:
                    pass
        save()
    return ok

async def dashboard(message):
    u=user(message.from_user.id)
    accrue(u["id"])
    m=get_machine(u["machine_id"])
    await message.answer(
        "<b>⚡ TON MINER</b>\n"
        "<i>NETWORK STATUS • ONLINE</i>\n\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"💎 Balance      <b>{fmt(u['balance'])} TON</b>\n"
        f"⛏️ Machine      <b>{m['name']}</b>\n"
        f"👥 Referrals    <b>{len(u['valid_referrals'])}/{db['settings']['required_referrals']}</b>\n"
        f"👛 Wallet       <b>{'CONNECTED ✅' if u['wallet'] else 'NOT CONNECTED ❌'}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "<code>MINING ENGINE • ACTIVE</code>",
        reply_markup=menu()
    )

bot=Bot(TOKEN,default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp=Dispatcher()
wallet_wait=set()
broadcast_wait=set()

@dp.message(CommandStart())
async def start(message:Message):
    u=user(message.from_user.id,message.from_user.username,message.from_user.first_name)
    parts=(message.text or "").split(maxsplit=1)
    if len(parts)==2 and parts[1].startswith("ref_"):
        try:
            rid=int(parts[1][4:])
            if rid!=u["id"] and not u["referrer"]:
                u["referrer"]=rid
                r=user(rid)
                if u["id"] not in r["referrals"]:
                    r["referrals"].append(u["id"])
                save()
        except ValueError:
            pass

    if db["settings"]["required_channels"] and not await all_required_joined(u["id"]):
        await message.answer(
            "<b>🔐 ACCESS VERIFICATION</b>\n\n"
            "Join every required channel/group below.\n"
            "After joining, press <b>VERIFY & CONTINUE</b>.",
            reply_markup=required_kb()
        )
        return
    await validate_access(u["id"])
    await dashboard(message)

@dp.callback_query(F.data=="verify")
async def verify(c:CallbackQuery):
    if not await validate_access(c.from_user.id):
        await c.answer("❌ Join every required channel/group first.",show_alert=True)
        return
    await c.message.edit_text("<b>✅ VERIFICATION COMPLETE</b>\n\nWelcome to TON MINER.",reply_markup=back())
    await c.answer()

@dp.callback_query(F.data=="home")
async def home(c:CallbackQuery):
    await c.message.delete()
    await dashboard(c.message)
    await c.answer()

@dp.callback_query(F.data=="mining")
async def mining(c:CallbackQuery):
    u=user(c.from_user.id); accrue(u["id"]); m=get_machine(u["machine_id"])
    interval=float(m["hours"])*3600
    remain=max(0, interval-(time.time()-u["machine_started"]))
    pct=1-remain/interval
    h=int(remain//3600); mi=int(remain%3600//60); s=int(remain%60)
    await c.message.edit_text(
        "<b>⛏️ MINING CORE</b>\n\n"
        f"🖥️ Hardware: <b>{m['name']}</b>\n"
        f"⚡ Rate: <b>1 TON / {m['hours']} hours</b>\n"
        f"💎 Balance: <b>{fmt(u['balance'])} TON</b>\n\n"
        f"{bar(pct)} <b>{pct*100:.1f}%</b>\n"
        f"⏳ Cycle timer: <b>{h:02d}:{mi:02d}:{s:02d}</b>\n\n"
        "<i>Continuous elapsed-time accounting.</i>",
        reply_markup=back()
    )
    await c.answer()

@dp.callback_query(F.data=="balance")
async def balance(c:CallbackQuery):
    u=user(c.from_user.id); accrue(u["id"])
    await c.message.edit_text(
        "<b>💎 BALANCE CENTER</b>\n\n"
        f"Available: <b>{fmt(u['balance'])} TON</b>\n"
        f"Minimum withdrawal: <b>{fmt(db['settings']['min_withdrawal'])} TON</b>\n"
        f"Valid referrals: <b>{len(u['valid_referrals'])}/{db['settings']['required_referrals']}</b>",
        reply_markup=back()
    )
    await c.answer()

@dp.callback_query(F.data=="machines")
async def machines(c:CallbackQuery):
    rows=[]
    for m in db["machines"]:
        price="FREE" if m["stars"]==0 else f"{m['stars']} ⭐"
        rows.append([InlineKeyboardButton(text=f"{m['name']} • {price}",callback_data=f"machine:{m['id']}")])
    rows.append([InlineKeyboardButton(text="↩️ MAIN MENU",callback_data="home")])
    await c.message.edit_text(
        "<b>🖥️ MACHINE GARAGE</b>\n\n"
        "Upgrade your mining hardware with Telegram Stars.\n\n"
        "🟢 FREE → 1 TON / 20h\n"
        "⭐ 50 → 1 TON / 10h\n"
        "⚡ 100 → 1 TON / 5h\n"
        "🔥 200 → 1 TON / 1.25h",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows)
    )
    await c.answer()

@dp.callback_query(F.data.startswith("machine:"))
async def machine_detail(c:CallbackQuery):
    mid=c.data.split(":",1)[1]; m=get_machine(mid)
    if not m: return await c.answer("Machine unavailable.",show_alert=True)
    if m["stars"]==0:
        u=user(c.from_user.id)
        u["machine_id"]="free"; u["machine_started"]=time.time(); save()
        await c.message.edit_text(
            f"<b>🟢 {m['name']}</b>\n\n"
            f"⚡ Production: <b>1 TON / {m['hours']} hours</b>\n\n"
            "Machine activated.",
            reply_markup=back())
        return
    await c.message.edit_text(
        f"<b>⚡ {m['name']}</b>\n\n"
        f"⭐ Price: <b>{m['stars']} Telegram Stars</b>\n"
        f"⛏️ Production: <b>1 TON / {m['hours']} hours</b>\n\n"
        "Payment is processed through Telegram Stars.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text=f"⭐ BUY FOR {m['stars']} STARS",callback_data=f"buy:{m['id']}")],
            [InlineKeyboardButton(text="↩️ BACK",callback_data="machines")]
        ])
    )
    await c.answer()

@dp.callback_query(F.data.startswith("buy:"))
async def buy(c:CallbackQuery):
    mid=c.data.split(":",1)[1]; m=get_machine(mid)
    if not m or m["stars"]<=0:
        return await c.answer("Invalid machine.",show_alert=True)
    payload=f"machine:{mid}:{c.from_user.id}:{uuid.uuid4().hex[:8]}"
    await bot.send_invoice(
        chat_id=c.from_user.id,
        title=m["name"],
        description=f"Mining machine — 1 TON / {m['hours']} hours",
        payload=payload,
        currency="XTR",
        prices=[LabeledPrice(label=m["name"],amount=int(m["stars"]))]
    )
    await c.answer()

@dp.pre_checkout_query()
async def pre_checkout(q:PreCheckoutQuery):
    await q.answer(ok=True)

@dp.message(F.successful_payment)
async def payment(message:Message):
    p=message.successful_payment.invoice_payload
    if not p.startswith("machine:"): return
    parts=p.split(":")
    if len(parts)<4: return
    _,mid,uid,_=parts
    if int(uid)!=message.from_user.id: return
    m=get_machine(mid)
    if not m: return
    payment_id=message.successful_payment.telegram_payment_charge_id
    if payment_id in db["stars_payments"]:
        return
    db["stars_payments"][payment_id]={
        "user_id":message.from_user.id,"machine_id":mid,
        "stars":message.successful_payment.total_amount,"time":time.time()
    }
    u=user(message.from_user.id)
    u["machine_id"]=mid; u["machine_started"]=time.time()
    db["transactions"].append({
        "id":uuid.uuid4().hex[:10],"user_id":u["id"],
        "type":"machine_purchase","amount":0,
        "stars":message.successful_payment.total_amount,
        "machine":mid,"time":time.time()
    })
    save()
    await message.answer(
        "<b>💳 PAYMENT CONFIRMED</b>\n\n"
        f"🖥️ Machine: <b>{m['name']}</b>\n"
        f"⭐ Paid: <b>{message.successful_payment.total_amount} Stars</b>\n"
        f"⚡ Production: <b>1 TON / {m['hours']} hours</b>\n\n"
        "<code>MINING CYCLE • STARTED</code>",
        reply_markup=menu()
    )

@dp.callback_query(F.data=="referrals")
async def referrals(c:CallbackQuery):
    u=user(c.from_user.id); me=await bot.get_me()
    link=f"https://t.me/{me.username}?start=ref_{u['id']}"
    await c.message.edit_text(
        "<b>👥 REFERRAL NETWORK</b>\n\n"
        f"Valid referrals: <b>{len(u['valid_referrals'])}/{db['settings']['required_referrals']}</b>\n"
        f"Total invited: <b>{len(u['referrals'])}</b>\n\n"
        f"🔗 <code>{link}</code>\n\n"
        "<i>A referral counts only after the invited user passes channel verification and connects a wallet.</i>",
        reply_markup=back())
    await c.answer()

@dp.callback_query(F.data=="wallet")
async def wallet(c:CallbackQuery):
    u=user(c.from_user.id)
    wallet_wait.add(c.from_user.id)
    await c.message.edit_text(
        "<b>👛 CONNECT TON WALLET</b>\n\n"
        f"Current: <code>{u['wallet'] or 'Not connected'}</code>\n\n"
        "Send your TON wallet address in the next message.\n\n"
        "⚠️ Never send a seed phrase or private key.",
        reply_markup=back())
    await c.answer()

@dp.callback_query(F.data=="earn")
async def earn(c:CallbackQuery):
    rows=[]
    u=user(c.from_user.id)
    for t in db["earn_tasks"]:
        done=t["id"] in u["earn_done"]
        rows.append([InlineKeyboardButton(
            text=f"{'✅' if done else '🎯'} {t['name']} • +{fmt(t['reward'])} TON",
            callback_data=f"earn:{t['id']}")])
    rows.append([InlineKeyboardButton(text="↩️ MAIN MENU",callback_data="home")])
    await c.message.edit_text(
        "<b>🎯 EARN CENTER</b>\n\n"
        "Only channel-join tasks are available.\n"
        "Join a channel, then press CHECK.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows))
    await c.answer()

@dp.callback_query(F.data.startswith("earn:"))
async def earn_detail(c:CallbackQuery):
    tid=c.data.split(":",1)[1]
    t=next((x for x in db["earn_tasks"] if x["id"]==tid),None)
    if not t: return await c.answer("Task removed.",show_alert=True)
    u=user(c.from_user.id)
    if tid in u["earn_done"]: return await c.answer("Already rewarded.",show_alert=True)
    await c.message.edit_text(
        "<b>🎯 CHANNEL TASK</b>\n\n"
        f"📢 Channel: <b>{t['name']}</b>\n"
        f"💎 Reward: <b>+{fmt(t['reward'])} TON</b>\n\n"
        "Join the channel, then tap CHECK JOIN.",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="📢 JOIN CHANNEL",url=t["url"])],
            [InlineKeyboardButton(text="✅ CHECK JOIN",callback_data=f"checkearn:{tid}")],
            [InlineKeyboardButton(text="↩️ BACK",callback_data="earn")]
        ]))
    await c.answer()

@dp.callback_query(F.data.startswith("checkearn:"))
async def check_earn(c:CallbackQuery):
    tid=c.data.split(":",1)[1]
    t=next((x for x in db["earn_tasks"] if x["id"]==tid),None)
    u=user(c.from_user.id)
    if not t: return await c.answer("Task removed.",show_alert=True)
    if tid in u["earn_done"]: return await c.answer("Already rewarded.",show_alert=True)
    if not await member(u["id"],t["chat_id"]):
        return await c.answer("❌ Join the channel first.",show_alert=True)
    reward=float(t["reward"])
    u["earn_done"].append(tid); u["balance"]+=reward
    db["transactions"].append({
        "id":uuid.uuid4().hex[:10],"user_id":u["id"],
        "type":"channel_earn","amount":reward,"task":tid,"time":time.time()
    })
    save()
    await c.message.edit_text(
        "<b>🎉 TASK VERIFIED</b>\n\n"
        f"Reward credited: <b>+{fmt(reward)} TON</b>",
        reply_markup=back())
    await c.answer("Reward credited.")

@dp.callback_query(F.data=="withdraw")
async def withdraw(c:CallbackQuery):
    u=user(c.from_user.id); accrue(u["id"])
    minimum=float(db["settings"]["min_withdrawal"])
    if u["withdrawal_id"]:
        text="⏳ <b>WITHDRAWAL ACTIVE</b>\n\nYou already have one request in progress."
    elif not u["wallet"]:
        text="❌ <b>STEP 1 — WALLET</b>\n\nConnect your TON wallet first."
    elif len(u["valid_referrals"])<int(db["settings"]["required_referrals"]):
        text=(f"❌ <b>STEP 2 — REFERRALS</b>\n\n"
              f"Valid: <b>{len(u['valid_referrals'])}/{db['settings']['required_referrals']}</b>")
    elif u["balance"]<minimum:
        text=(f"❌ <b>STEP 3 — MINIMUM</b>\n\n"
              f"Required: <b>{fmt(minimum)} TON</b>\n"
              f"Current: <b>{fmt(u['balance'])} TON</b>")
    elif db["settings"]["machine_gate"] and u["machine_id"]=="free":
        text=("❌ <b>STEP 4 — MACHINE</b>\n\n"
              "A paid machine purchase is required before withdrawal.\n"
              "Go to MACHINES and pay with Telegram Stars.")
    else:
        wid=uuid.uuid4().hex[:10]
        amount=float(u["balance"])
        db["withdrawals"][wid]={
            "id":wid,"user_id":u["id"],"amount":amount,
            "wallet":u["wallet"],"status":"pending","created":time.time()
        }
        u["withdrawal_id"]=wid
        save()
        text=(
            "<b>💸 WITHDRAWAL REQUEST SENT</b>\n\n"
            f"Amount: <b>{fmt(amount)} TON</b>\n"
            f"Wallet: <code>{u['wallet']}</code>\n\n"
            "Status: <b>⏳ PENDING ADMIN</b>\n\n"
            "<i>Your request has been forwarded to the admin for the real TON payout.</i>"
        )
        try:
            await bot.send_message(
                ADMIN_ID,
                "<b>🚨 NEW TON WITHDRAWAL</b>\n\n"
                f"User ID: <code>{u['id']}</code>\n"
                f"Amount: <b>{fmt(amount)} TON</b>\n"
                f"Wallet: <code>{u['wallet']}</code>\n"
                f"Request: <code>{wid}</code>\n\n"
                "Admin: complete the real TON transfer externally, then use MARK PAID.",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="✅ APPROVE",callback_data=f"wd:approve:{wid}")],
                    [InlineKeyboardButton(text="❌ REJECT",callback_data=f"wd:reject:{wid}")],
                    [InlineKeyboardButton(text="💎 MARK PAID",callback_data=f"wd:paid:{wid}")],
                ])
            )
        except Exception:
            pass
    await c.message.edit_text(text,reply_markup=back())
    await c.answer()

@dp.callback_query(F.data.startswith("wd:"))
async def withdrawal_admin(c:CallbackQuery):
    if c.from_user.id!=ADMIN_ID:
        return await c.answer("Admin only.",show_alert=True)
    _,action,wid=c.data.split(":")
    w=db["withdrawals"].get(wid)
    if not w: return await c.answer("Not found.",show_alert=True)
    u=user(w["user_id"])
    if action=="approve":
        w["status"]="approved"
        await bot.send_message(u["id"],
            "<b>✅ WITHDRAWAL APPROVED</b>\n\n"
            f"Amount: <b>{fmt(w['amount'])} TON</b>\n"
            "Admin is completing the real TON payout.")
    elif action=="reject":
        w["status"]="rejected"; u["withdrawal_id"]=None
        await bot.send_message(u["id"],"<b>❌ WITHDRAWAL REJECTED</b>\n\nPlease contact admin.")
    elif action=="paid":
        w["status"]="paid"
        u["withdrawal_id"]=None
        u["balance"]=max(0,float(u["balance"])-float(w["amount"]))
        await bot.send_message(u["id"],
            "<b>💎 PAYMENT COMPLETED</b>\n\n"
            f"Amount: <b>{fmt(w['amount'])} TON</b>\n"
            "The admin marked your real payout as paid.")
    save()
    await c.message.edit_reply_markup(reply_markup=None)
    await c.answer("Withdrawal updated.")

@dp.callback_query(F.data=="history")
async def history(c:CallbackQuery):
    tx=[x for x in db["transactions"] if x["user_id"]==c.from_user.id][-12:]
    body="\n".join(
        f"• {x['type'].upper()} — <b>{fmt(x['amount'])} TON</b>"
        for x in reversed(tx)
    ) or "No transactions yet."
    await c.message.edit_text(f"<b>📜 HISTORY</b>\n\n{body}",reply_markup=back())
    await c.answer()

@dp.callback_query(F.data=="profile")
async def profile(c:CallbackQuery):
    u=user(c.from_user.id)
    await c.message.edit_text(
        "<b>📊 PROFILE</b>\n\n"
        f"ID: <code>{u['id']}</code>\n"
        f"Balance: <b>{fmt(u['balance'])} TON</b>\n"
        f"Valid referrals: <b>{len(u['valid_referrals'])}</b>\n"
        f"Machine: <b>{get_machine(u['machine_id'])['name']}</b>\n"
        f"Wallet: <b>{'CONNECTED' if u['wallet'] else 'NOT CONNECTED'}</b>",
        reply_markup=back())
    await c.answer()

# ---------- Admin UI ----------
@dp.message(Command("admin"))
async def admin_cmd(m:Message):
    if m.from_user.id!=ADMIN_ID: return await m.answer("⛔ Admin only.")
    await m.answer("<b>⚙️ ADMIN CONTROL CENTER</b>\n\nChoose an option:",reply_markup=admin_menu())

@dp.callback_query(F.data.startswith("adm:"))
async def admin_button(c:CallbackQuery):
    if c.from_user.id!=ADMIN_ID:
        return await c.answer("Admin only.",show_alert=True)
    action=c.data.split(":",1)[1]
    if action=="stats":
        await c.message.edit_text(
            f"<b>📊 SYSTEM STATS</b>\n\n"
            f"Users: <b>{len(db['users'])}</b>\n"
            f"Pending withdrawals: <b>{sum(x['status']=='pending' for x in db['withdrawals'].values())}</b>\n"
            f"Required channels: <b>{len(db['settings']['required_channels'])}</b>\n"
            f"Earn tasks: <b>{len(db['earn_tasks'])}</b>\n"
            f"Machines: <b>{len(db['machines'])}</b>\n"
            f"Min withdrawal: <b>{fmt(db['settings']['min_withdrawal'])} TON</b>\n"
            f"Referral requirement: <b>{db['settings']['required_referrals']}</b>\n"
            f"Machine gate: <b>{'ON' if db['settings']['machine_gate'] else 'OFF'}</b>",
            reply_markup=admin_menu())
    elif action=="withdrawals":
        pending=[w for w in db["withdrawals"].values() if w["status"] in ("pending","approved")]
        if not pending:
            body="No active withdrawals."
        else:
            body="\n\n".join(
                f"ID <code>{w['id']}</code>\nUser <code>{w['user_id']}</code>\n"
                f"{fmt(w['amount'])} TON\nStatus: <b>{w['status'].upper()}</b>\n"
                f"Wallet: <code>{w['wallet']}</code>"
                for w in pending[:10])
        await c.message.edit_text(f"<b>💸 WITHDRAWAL QUEUE</b>\n\n{body}",reply_markup=admin_menu())
    elif action=="channels":
        if db["settings"]["required_channels"]:
            body="\n".join(f"• <code>{x['chat_id']}</code> — {x['name']}" for x in db["settings"]["required_channels"])
        else: body="No required channels."
        await c.message.edit_text(
            f"<b>📢 REQUIRED CHANNELS</b>\n\n{body}\n\n"
            "/addchannel @channel | Name\n/delchannel @channel_or_id",
            reply_markup=admin_menu())
    elif action=="tasks":
        if db["earn_tasks"]:
            body="\n".join(f"• <code>{x['id']}</code> — {x['name']} — {fmt(x['reward'])} TON" for x in db["earn_tasks"])
        else: body="No earn tasks."
        await c.message.edit_text(
            f"<b>🎯 EARN — JOIN CHANNEL ONLY</b>\n\n{body}\n\n"
            "/addearn @channel | Name | 0.10\n/delearntask TASK_ID",
            reply_markup=admin_menu())
    elif action=="machines":
        body="\n".join(f"• <code>{x['id']}</code> — {x['name']} — {x['stars']} ⭐ — 1 TON/{x['hours']}h" for x in db["machines"])
        await c.message.edit_text(
            f"<b>🖥️ MACHINES</b>\n\n{body}\n\n"
            "/addmachine Name | Stars | HoursPerCoin\n/delmachine ID",
            reply_markup=admin_menu())
    elif action=="settings":
        await c.message.edit_text(
            "<b>⚙️ SETTINGS</b>\n\n"
            f"Minimum withdrawal: <b>{fmt(db['settings']['min_withdrawal'])} TON</b>\n"
            f"Valid referrals required: <b>{db['settings']['required_referrals']}</b>\n"
            f"Machine purchase gate: <b>{'ON' if db['settings']['machine_gate'] else 'OFF'}</b>\n\n"
            "/setmin 5\n/setrefs 5\n/setmachinegate on/off",
            reply_markup=admin_menu())
    elif action=="broadcast":
        broadcast_wait.add(ADMIN_ID)
        await c.message.edit_text("<b>📢 BROADCAST</b>\n\nSend the message you want to broadcast.",reply_markup=admin_menu())
    await c.answer()

@dp.message(Command("setmin"))
async def setmin(m:Message):
    if m.from_user.id!=ADMIN_ID:return
    try:
        x=float((m.text or "").split()[1]); assert x>0
        db["settings"]["min_withdrawal"]=x; save()
        await m.answer(f"✅ Minimum withdrawal: <b>{fmt(x)} TON</b>")
    except: await m.answer("Usage: /setmin 5")

@dp.message(Command("setrefs"))
async def setrefs(m:Message):
    if m.from_user.id!=ADMIN_ID:return
    try:
        x=int((m.text or "").split()[1]); assert x>=0
        db["settings"]["required_referrals"]=x; save()
        await m.answer(f"✅ Referral requirement: <b>{x}</b>")
    except: await m.answer("Usage: /setrefs 5")

@dp.message(Command("setmachinegate"))
async def setgate(m:Message):
    if m.from_user.id!=ADMIN_ID:return
    args=(m.text or "").split()
    if len(args)!=2 or args[1].lower() not in ("on","off"):
        return await m.answer("Usage: /setmachinegate on")
    db["settings"]["machine_gate"]=args[1].lower()=="on"; save()
    await m.answer(f"✅ Machine purchase requirement: <b>{'ON' if db['settings']['machine_gate'] else 'OFF'}</b>")

@dp.message(Command("addchannel"))
async def addchannel(m:Message):
    if m.from_user.id!=ADMIN_ID:return
    raw=(m.text or "").split(maxsplit=1)
    if len(raw)<2 or "|" not in raw[1]:
        return await m.answer("Usage: /addchannel @channel | Name")
    target,name=[x.strip() for x in raw[1].split("|",1)]
    chat_id=int(target) if target.startswith("-100") else target
    url=target if target.startswith("http") else f"https://t.me/{target.lstrip('@')}"
    db["settings"]["required_channels"].append({"chat_id":chat_id,"name":name,"url":url})
    save(); await m.answer("✅ Required channel added.")

@dp.message(Command("delchannel"))
async def delchannel(m:Message):
    if m.from_user.id!=ADMIN_ID:return
    raw=(m.text or "").split(maxsplit=1)
    if len(raw)<2:return
    target=raw[1].strip()
    old=len(db["settings"]["required_channels"])
    db["settings"]["required_channels"]=[x for x in db["settings"]["required_channels"] if str(x["chat_id"])!=target]
    save(); await m.answer(f"✅ Removed {old-len(db['settings']['required_channels'])} channel(s).")

@dp.message(Command("addearn"))
async def addearn(m:Message):
    if m.from_user.id!=ADMIN_ID:return
    raw=(m.text or "").split(maxsplit=1)
    if len(raw)<2 or raw[1].count("|")<2:
        return await m.answer("Usage: /addearn @channel | Name | 0.10")
    target,name,reward=[x.strip() for x in raw[1].split("|",2)]
    try:r=float(reward)
    except:return await m.answer("Invalid reward.")
    chat_id=int(target) if target.startswith("-100") else target
    url=target if target.startswith("http") else f"https://t.me/{target.lstrip('@')}"
    tid=uuid.uuid4().hex[:6]
    db["earn_tasks"].append({"id":tid,"chat_id":chat_id,"name":name,"url":url,"reward":r})
    save(); await m.answer(f"✅ Earn task added. ID: <code>{tid}</code>")

@dp.message(Command("delearntask"))
async def delearntask(m:Message):
    if m.from_user.id!=ADMIN_ID:return
    raw=(m.text or "").split(maxsplit=1)
    if len(raw)<2:return
    tid=raw[1].strip()
    old=len(db["earn_tasks"])
    db["earn_tasks"]=[x for x in db["earn_tasks"] if x["id"]!=tid]
    save(); await m.answer(f"✅ Removed {old-len(db['earn_tasks'])} task(s).")

@dp.message(Command("addmachine"))
async def addmachine(m:Message):
    if m.from_user.id!=ADMIN_ID:return
    raw=(m.text or "").split(maxsplit=1)
    if len(raw)<2 or raw[1].count("|")<2:
        return await m.answer("Usage: /addmachine Name | Stars | HoursPerCoin")
    name,stars,hours=[x.strip() for x in raw[1].split("|",2)]
    try:s=int(stars); h=float(hours); assert s>=0 and h>0
    except:return await m.answer("Invalid machine values.")
    mid="m"+uuid.uuid4().hex[:6]
    db["machines"].append({"id":mid,"name":name,"stars":s,"hours":h})
    save(); await m.answer(f"✅ Machine added: <code>{mid}</code>")

@dp.message(Command("delmachine"))
async def delmachine(m:Message):
    if m.from_user.id!=ADMIN_ID:return
    raw=(m.text or "").split(maxsplit=1)
    if len(raw)<2:return
    mid=raw[1].strip()
    if mid=="free": return await m.answer("❌ Free machine cannot be removed.")
    db["machines"]=[x for x in db["machines"] if x["id"]!=mid]
    save(); await m.answer("✅ Machine removed.")

@dp.message(Command("broadcast"))
async def broadcast(m:Message):
    if m.from_user.id!=ADMIN_ID:return
    parts=(m.text or "").split(maxsplit=1)
    if len(parts)==2:
        await send_broadcast(parts[1],m)
    else:
        broadcast_wait.add(ADMIN_ID)
        await m.answer("📢 Send the broadcast text now.")

async def send_broadcast(text, admin_message):
    broadcast_wait.discard(ADMIN_ID)
    sent=0
    for uid in list(db["users"]):
        try:
            await bot.send_message(int(uid),text)
            sent+=1
        except Exception:
            pass
    await admin_message.answer(f"📢 <b>BROADCAST COMPLETE</b>\nSent: <b>{sent}</b> users.")

@dp.message()
async def text_handler(m:Message):
    uid=m.from_user.id
    if uid==ADMIN_ID and uid in broadcast_wait:
        await send_broadcast(m.text or "",m)
        return
    if uid in wallet_wait:
        address=(m.text or "").strip()
        if len(address)<20 or " " in address:
            return await m.answer("❌ Send only a valid TON wallet address.")
        u=user(uid)
        u["wallet"]=address
        wallet_wait.discard(uid)
        save()
        # Now that wallet exists, referral can become valid if verification is already complete.
        if u["verified"] and u["referrer"]:
            ref=user(u["referrer"])
            if uid not in ref["valid_referrals"]:
                ref["valid_referrals"].append(uid); save()
                try:
                    await bot.send_message(ref["id"],"🎉 <b>REFERRAL VERIFIED</b>\nWallet connected — referral is now valid.")
                except: pass
        await m.answer(
            "<b>👛 WALLET CONNECTED</b>\n\n"
            f"Address: <code>{address}</code>\n\n"
            "Your wallet is now registered. Never share a seed phrase/private key.",
            reply_markup=menu())
        return
    await m.answer("Use the buttons below.",reply_markup=menu())

async def main():
    print("⚡ TON MINER is online")
    await dp.start_polling(bot)

if __name__=="__main__":
    asyncio.run(main())
