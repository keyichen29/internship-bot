# Hardware + Product Management internship bot (Discord)

Checks three public internship lists (Jobright, Simplify/Pitt CSC, zshah101) every 5 minutes.
Keeps hardware-engineering and product/program-management roles (skips purely software roles)
and posts each NEW one to your Discord channel as a clickable card with the apply link.

## Your channels (one Discord channel + one GitHub secret each)

| Channel | GitHub secret | What it gets |
|---|---|---|
| #hardware | `DISCORD_WEBHOOK_URL` | NEW hardware engineering roles only (no PM, no software titles, no mechanical) |
| #pm | `DISCORD_PM_WEBHOOK_URL` | NEW product / program management roles |
| #prestige | `DISCORD_PRESTIGE_WEBHOOK_URL` | NEW hardware-engineering or PM roles at top-tier companies (NVIDIA, Apple, Google, Tesla, ...) |
| #pick-of-the-day | `DISCORD_DAILY_WEBHOOK_URL` | One best-fit, most-prestigious role per day |

A role can show up in two channels (e.g. a Google hardware role goes to #hardware and #prestige).
Channels you haven't set a secret for are simply skipped, so you can add them one at a time.
**Add all your secrets BEFORE the first run**: the first run quietly memorizes everything currently open
and posts a "bot is live" hello in each channel. Channels added later get no hello and no backlog, only new roles.
Optional `DISCORD_USER_ID` makes the bot @ping you.

PhD, Master's, and MBA roles are removed too (Simplify's 🎓 "advanced degree required" flag, plus degree words in titles).
"BS/MS" and "Undergraduate" roles are kept. Turn this off with `EXCLUDE_ADVANCED_DEGREE = False`.

Mechanical engineering roles are removed completely (the `EXCLUDE` list in `hw_bot.py`).
Roles like systems/test/manufacturing engineer are still listed in `hardware_internships.md`
but aren't pinged, since they aren't "purely hardware engineering".

## Setup (about 5 minutes, no coding)

### 1. Discord: make a webhook
1. In Discord, make a server for yourself (the "+" button, then "Create My Own"). Skip if you have one.
2. Create or pick a text channel (e.g. #internships).
3. Channel settings (gear icon) -> Integrations -> Webhooks -> New Webhook -> **Copy Webhook URL**.
4. Optional, so you get a real @ping on your phone: Discord Settings -> Advanced -> turn on
   **Developer Mode**. Then right-click your own name -> **Copy User ID**.

### 2. GitHub: put the bot online
1. Create a free GitHub account and a new repository. **Make it Public.**
   (Public repos get unlimited free Actions minutes. A private repo would run out in about a week
   at a 5-minute schedule. Nothing sensitive is in the repo: the lists are already public and your
   webhook goes in a secret, not in the files.)
2. Upload `hw_bot.py` and `.github/workflows/hw-bot.yml` (keep the folder structure; dragging in the whole folder works).
3. Repo -> Settings -> Secrets and variables -> Actions -> **New repository secret**:
   - Name `DISCORD_WEBHOOK_URL`, value: the webhook URL you copied
   - Name `DISCORD_USER_ID`, value: your Discord user ID (optional)
4. Repo -> Actions tab -> enable workflows if asked -> **hw-intern-bot** -> **Run workflow**.
   You should get a "bot is live" message in Discord within a minute. After that it runs by itself.

### 3. Second channel: the "one job today" pick
1. In the same Discord server, make another channel (e.g. #pick-of-the-day) and create a second webhook for it.
2. Add a repo secret named `DISCORD_DAILY_WEBHOOK_URL` with that URL.
3. Upload `.github/workflows/hw-daily.yml` too. It posts once a day at 13:00 UTC (9am New York / 6am LA).
   To change the time, edit the `cron:` line (cron is always UTC). Run it manually from the Actions tab any time.

Each day it posts exactly ONE role: the most prestigious company first, with role fit as the tiebreaker
(core hardware > hardware-adjacent > software close to hardware; PM roles score a bit below core hardware;
fresher postings get a small boost). A role is never picked twice. The post says why it was chosen.
Tune it at the top of `hw_bot.py`: `PRESTIGE_TIERS` (company ranking), `BOOST_KEYWORDS` (e.g. "robot"),
`PREFERRED_LOCATIONS` (e.g. "CA", "Boston").

### 4. Phone pings
Install Discord on your phone and make sure notifications are on for that server/channel.

## How it behaves
- First run quietly memorizes everything currently open, so you only get pinged about **new** roles.
- Up to 30 role cards per ping; if more appear at once, the rest are summarized and listed in `hardware_internships.md`.
- If Discord is down, the bot keeps those roles "unseen" and retries on the next run.
- `hardware_internships.md` in the repo is always the full current list.

## Tweaking it
Top of `hw_bot.py`:
- `HARDWARE_KEYWORDS` / `PM_KEYWORDS`: words that make a title count
- `EXCLUDE`: words that drop a role
- `PM_SKIP_PURE_SOFTWARE`: `True` drops PM roles with "software" in the title
- `PRESTIGE_ALERT_MIN`: 100 = only top-tier companies in #prestige, 80 = also the next tier (many more roles)
- `PRESTIGE_TIERS`: which company counts as how prestigious
- `PRIORITY`: optional companies to sort first

## Test the webhook from your own computer
`DISCORD_WEBHOOK_URL="paste-url" python3 hw_bot.py --test` (and `--test-daily` with `DISCORD_DAILY_WEBHOOK_URL`)

## Honest limits
- "As soon as possible" = within about 5-15 minutes of a role appearing **in the lists**. GitHub's scheduler
  is best-effort and sometimes runs late, and the lists update on their own schedules (zshah roughly every
  30 min; Simplify and Jobright about daily). The bot can't beat the source lists.
- If the repo has no activity for 60 days GitHub pauses scheduled runs; the bot's own saves count as activity, so this shouldn't happen.
