# ⚡ TON MINER — FINAL

Normal Telegram bot. No Mini App.

## Exact requested flow

1. User starts bot.
2. User must join all admin-required channels/groups.
3. User verifies membership.
4. User connects a TON wallet/address.
5. A referral only becomes VALID after the invited user completes the required join verification AND connects a wallet.
6. Default referral requirement is 5, configurable by admin.
7. User mines with the selected machine.
8. Withdrawal requires:
   - wallet connected
   - required valid referrals
   - minimum balance
   - paid machine purchase (admin can turn this requirement on/off)
9. Withdrawal request goes to admin.
10. Admin handles the real TON payout externally and then marks the request PAID.

## Machines

- FREE MINER — 1 TON / 20 hours
- 50 ⭐ TURBO — 1 TON / 10 hours
- 100 ⭐ HYPER — 1 TON / 5 hours
- 200 ⭐ ULTRA — 1 TON / 1.25 hours

The engine calculates continuously from elapsed time instead of pretending to mine at an unrelated per-second rate.

## Earn

Only one earn type:
- JOIN CHANNEL
- Admin adds a channel and sets a TON reward.
- User joins it and presses CHECK.
- Bot verifies Telegram membership and credits the reward once.

## Telegram Stars

Paid machines use Telegram Stars (`XTR`) invoices. Successful payment activates the selected machine.

## Admin

Admin-only button panel and commands for:
- required channels: add/remove
- referral requirement
- minimum withdrawal
- machine-purchase withdrawal requirement
- machine add/remove
- earn channel add/remove/reward
- withdrawal queue
- broadcast
- statistics

## Real payout

The bot does not store a TON private key or seed phrase. Withdrawal requests are sent to the admin with the user's wallet address and amount. The admin performs the actual TON transfer and presses MARK PAID.

The bot never claims an on-chain transaction happened before the admin actually completes it.

## Install

Python 3.10+:

pip install -r requirements.txt

Copy `.env.example` to `.env`, fill in BOT_TOKEN and ADMIN_ID, then:

python bot.py

The bot must be an administrator in channels/groups where Telegram membership checks are required.
