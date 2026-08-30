# ⚡ TON MINER — Professional Telegram Bot

A Telegram bot that provides a **simulated mining ledger** with a premium mining-style UI.

> Important: the mining shown in the bot is an in-app simulation/ledger. It does not perform real TON blockchain mining. Real TON payouts are manually completed by the admin.

## Included

- ⛏️ Live elapsed-time mining screen
- 🔄 Refresh button
- 💰 Collect button
- "Mining active for" duration
- Progress percentage + cycle countdown
- Free machine: 1 TON / 20h
- 50 Stars machine: 1 TON / 10h
- 100 Stars machine: 1 TON / 5h
- 200 Stars machine: 1 TON / 1.25h
- Telegram Stars (`XTR`) invoice payments
- Wallet address collection
- Start verification with admin-configured channels/groups
- Referral requirement; default 5
- Referral counts only after verification + wallet connection
- Earn section: join channel → verify → TON reward
- Admin-configured minimum withdrawal
- Optional paid-machine requirement before withdrawal
- Withdrawal requests sent to admin
- Admin approve/reject/mark-paid buttons
- Broadcast
- SQLite persistent database
- Admin commands for channels, tasks, machines and settings

## 1. Install

Python 3.10+ recommended.

```bash
python -m venv .venv
```

Linux/macOS:
```bash
source .venv/bin/activate
```

Windows:
```bash
.venv\Scripts\activate
```

Install:
```bash
pip install -r requirements.txt
```

## 2. Configure

Copy `.env.example` to `.env`.

Put:
```env
BOT_TOKEN=YOUR_BOT_TOKEN
ADMIN_ID=YOUR_TELEGRAM_NUMERIC_ID
```

## 3. Run

```bash
python bot.py
```

## 4. Required channel setup

The bot needs permission to check channel/group membership.

For reliable membership verification, add the bot to each required channel/group with appropriate admin permissions.

Admin:
```text
/addstart @channel | Channel Name
/delstart @channel
```

## 5. Earn tasks

Admin:
```text
/addearn @channel | Channel Name | 0.10
/delearntask TASK_ID
```

Users see the task under 🎯 EARN.

## 6. Machines

Default machines:

| Machine | Stars | Rate |
|---|---:|---:|
| FREE MINER | 0 | 1 TON / 20h |
| TURBO MINER | 50 | 1 TON / 10h |
| HYPER MINER | 100 | 1 TON / 5h |
| ULTRA MINER | 200 | 1 TON / 1.25h |

Add:
```text
/addmachine Name | Stars | Hours
```

Remove:
```text
/delmachine MACHINE_ID
```

## 7. Withdrawal settings

```text
/setmin 5
/setrefs 5
/setmachinegate on
```

The withdrawal flow is:

1. Wallet connected
2. Required valid referrals completed
3. Minimum balance reached
4. Paid machine purchased (if machine gate is ON)
5. Request goes to admin
6. Admin manually sends the real TON
7. Admin presses MARK PAID

The bot does not fabricate blockchain transaction IDs.

## 8. Broadcast

From admin panel:
**📢 BROADCAST**

Or:
```text
/broadcast Your message here
```

## 9. Telegram Stars

Paid machines use Telegram's `XTR` invoice system. The bot receives successful-payment callbacks and activates the purchased machine.

Stars are handled by Telegram's payment system; the bot does not pretend that Stars are TON.

## 10. Admin panel

Use:
```text
/admin
```

It includes:
- stats
- payout queue
- start-channel management
- earn tasks
- machine management
- minimum withdrawal
- referral requirement
- machine gate
- broadcast

## Security notes

- Never put your bot token in GitHub.
- Never ask users for seed phrases/private keys.
- Use a dedicated wallet for real payouts.
- Keep regular backups of `ton_miner.db`.
