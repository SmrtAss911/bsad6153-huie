# BSAD 6153 Project: Datacenter Parts Sourcing Assistant

**Student:** Anthony Huie
**My decision:** Weekly parts sourcing: for each standard datacenter part on my weekly pick list, whether to buy from my preferred vendor or an alternate distributor, based on price, stock, and lead time (data source: Mouser Search API).
**Website:** &lt;your domain, from Week 4&gt;

This repository is one complete AI system, built over eight weeks: a real API, synced on a schedule into a
PostgreSQL database, shown on a public website, with a chatbot and an agent that answer and act from your
own data. You build it with an AI coding agent, and you read and verify everything it writes.

---

## Setting up your computer (Week 1 Setup)

You need a **Windows 10/11 or macOS computer where you can install software**, Git, Python 3.12, and your AI
coding agent (Claude Code, Codex, Antigravity, or Copilot). Let your agent help with the installs, but read
every command before you approve it, and keep auto-approve off.

1. **Clone this repository** into a short folder path that isn't synced by OneDrive or Dropbox, for example
   `C:\dev\bsad6153` on Windows or `~/dev/bsad6153` on macOS.
2. **Create and activate a virtual environment** from the project folder:

   | | Windows (PowerShell) | macOS (Terminal) |
   |---|---|---|
   | Create | `py -3.12 -m venv .venv` | `python3.12 -m venv .venv` |
   | Activate | `.venv\Scripts\Activate.ps1` | `source .venv/bin/activate` |

   You'll see `(.venv)` at the start of your prompt when it's active. Activate it every time you open a new terminal.
3. **Install the packages:** `pip install -r requirements.txt`
4. **Create your secrets file:** copy `.env.example` to `.env`, and put a fake value on the `TEST_SECRET=` line.
5. **Check everything:** `python scripts/check_setup.py` should end with `Setup OK`.
6. **Try the website:** `streamlit run app/streamlit_app.py` opens it in your browser. Press Ctrl+C to stop it.

### Working with your AI agent

- **You approve every command.** Read it first, and if you don't understand it, ask the agent what it does.
- **Ask for a plan before code:** "Before writing anything, tell me your plan."
- **Never paste a real key into the chat,** and never ask the agent to print your `.env` file.
- **The agent never gets the owner database password or deploy tokens.** That's how agents delete databases.
- **Record what you directed, read, verified, and decided** in each pull request's AI review log.

---

## Project layout

| Folder | What goes there | When |
|---|---|---|
| `ingest/` | Fetch, load, and sync code | Weeks 1&ndash;3 |
| `db/` | `schema.sql`, `roles.sql`, `queries.sql` | Weeks 2&ndash;6 |
| `docs/` | Data dictionary, logs, reports (see `docs/README.md`) | Every week |
| `evals/` | Golden questions and evaluation runs | Weeks 3&ndash;7 |
| `app/` | Your website (Streamlit) | Weeks 4&ndash;6 |
| `examples/` | A reference tool-using chatbot loop | Week 5 |
| `scripts/` | Setup and database checks | Weeks 0&ndash;2 |
| `data/sample/` | A small sample of raw API data (large downloads go in `data/raw/`, which Git ignores) | Week 1 |

## Secrets: where each one lives

| Secret | On your computer | On Render (website) | In GitHub Actions (sync) |
|---|---|---|---|
| `DATABASE_URL` (owner) | `.env` | **never** | Actions secret |
| `APP_DATABASE_URL` (read-only) | `.env` | environment setting | if your checks need it |
| `AGENT_DATABASE_URL` | `.env` | environment setting | no |
| LLM key, `APP_PASSWORD` | `.env` | environment setting | no |
| Data API key | `.env` | no | Actions secret |

`.env.example` lists the names only. If a secret ever leaks, revoke or rotate it first, then tell the instructor.

---

## Deploying on Render (Week 4)

1. Claim your free domain through the GitHub Student Developer Pack.
2. In Render, choose **New &gt; Blueprint**, pick this repository, and enter each secret when asked.
   (`render.yaml` describes the service.) Or create a **Web Service** by hand with:
   - Build command: `pip install -r requirements.txt`
   - Start command: `streamlit run app/streamlit_app.py --server.port $PORT --server.address 0.0.0.0 --server.headless true`
   - Environment variables: `PYTHON_VERSION=3.12.4`, `APP_DATABASE_URL`, and later your LLM key and `APP_PASSWORD`
3. Under **Settings &gt; Custom Domains**, add your domain, then add the DNS records Render shows you at your
   registrar. Ask your agent to explain each record before you add it. HTTPS turns on automatically.
4. Free services sleep when idle and take about a minute to wake. Say so on your site.

---

## Troubleshooting

- **`pip install` fails with "No such file or directory" on Windows:** the folder path is too long. Move the
  project to a short path such as `C:\dev\bsad6153` and recreate `.venv`.
- **PowerShell says running scripts is disabled when you activate:** use Command Prompt instead and run
  `.venv\Scripts\activate.bat`, or ask the instructor. Don't change system security settings without asking.
- **`python` opens the Microsoft Store or isn't found:** use `py -3.12` on Windows or `python3.12` on macOS.
- **The database check can't connect:** use Supabase's Session pooler string, check the password, and check
  that your Supabase project isn't paused.

---

## Project proposal (Week 1)

**Data source and backup.** My data source is the Mouser Search API. Twelve keyword searches for datacenter parts (patch cables, fiber, power cords, PDUs, shelves, cable managers, SFPs) returned 1,456 unique parts from 56 manufacturers and 8,453 price breaks. Stock, lead time and price change over time, which is what my decision depends on. My backup is the Digi-Key Product Information API v4; its adapter is stubbed in `ingest/sources/digikey.py`. Mouser is not on the course menu, so I am asking for approval here. Mouser's terms restrict storing their data, so raw files stay local and gitignored, only a 3 part sample is committed, and the site attributes Mouser.

**Decision and workflow.** For each item on a datacenter pick list I decide what to buy and where, based on spec, stock, lead time and price. Cables can come from any brand if the spec matches; PDUs and racks need exact model numbers. My baseline log showed the lookup starts on Google and ends in an email quote from one or two vendors. Hands-on time is 5 to 15 minutes for cables and optics and about two hours for PDUs and cabinets, but calendar time is a couple of days to a week because every quote and order is an email round trip. I make these decisions anywhere from several times a day to once a week depending on workload. The bigger cost is wrong parts: 16 amp PDUs instead of 20 amp, 23 inch telco racks instead of 19 inch, a network cabinet instead of a server cabinet. Each came from part numbers and titles that look alike. My goal is to narrow purchasing to one vendor, two at most.

**Agent idea (Week 6).** An agent takes my pick list, matches commodity items by spec and exact items by manufacturer part number, checks stock, lead time and price breaks, and builds a recommended cart with its reasoning. It flags spec mismatches (amperage, rack width, cabinet type) against my saved standards, and it never places an order; I approve everything. Success means no wrong parts, no rework, and a cart in minutes instead of days.

**Risks.** Vendor terms on storage and display; keyword search returns unrelated parts (a voltage regulator under "cable manager"); stock and price go stale between syncs; 30 calls a minute and 1,000 a day limit refreshes.

AI use: drafted with Claude from my fetched data and notes; verified and revised by Anthony Huie.

## How to run this project

<!-- Keep this current: how to run the sync, the website, and the evaluations. -->

### Run instructions (Milestone 1: fetch)

1. **Set up once** (see "Setting up your computer" above): create `.venv` with Python 3.12 and
   `pip install -r requirements.txt`.
2. **Add your keys to `.env`** (never to `.env.example`, and never paste them into a chat):
   - `MOUSER_API_KEY=` your Mouser Search API key (required)
   - `DIGIKEY_CLIENT_ID=` and `DIGIKEY_CLIENT_SECRET=` for the Digi-Key backup (optional; the adapter is not finished yet)
3. **Fetch:** with `.venv` active, from the project folder:

   ```
   python ingest/fetch.py --source mouser
   ```

   It makes up to 36 calls (12 keywords, up to 3 pages of 50), waits 2.5 s between calls, and takes about 1.5 minutes.
   Raw responses go to `data/raw/mouser/` (ignored by Git). It ends with a summary of calls, records, retries, and errors.
   Exit code 0 means OK, 1 means it stopped early or got no parts, and 2 means the source isn't configured.
4. **Options:** `--max-pages N` (pages per keyword, default 3) and `--max-calls N` (cap per run, default 100).
   `--source digikey` currently prints "not configured."

See `docs/data_dictionary.md` for what the data means.

### Run instructions (Milestone 3: sync)

With `.venv` active and `DATABASE_URL`, `APP_DATABASE_URL`, and `MOUSER_API_KEY` in `.env`:

```
python ingest/sync.py                 # manual sync: refresh known parts, search for new ones
python scripts/status.py              # last successful sync, its age, and 7-day totals
```

- `sync.py` re-checks every part already in the database (10 part numbers per call) and runs the
  12 keyword searches for new parts. It makes about 200 calls and takes 8 to 12 minutes.
  It changes a row only when a value really changed, and it records every run in `sync_runs`.
- Options: `--trigger schedule|manual` (default `manual`), `--no-keywords` (known parts only),
  `--max-calls N` (default 250), `--dry-run` (fetch and compare, then roll back; writes nothing).
- Exit code 0 means `success` or `partial` (a partial run prints its reasons); 1 means `failed`.
- Only one sync runs at a time. A second one records a `failed` row ("another sync is running")
  and exits without calling Mouser.
- `status.py` uses the read-only role. Exit code 1 means the last successful sync is older than 13 hours.
- GitHub Actions runs the same sync on a schedule (`.github/workflows/sync.yml`), using the
  `DATABASE_URL` and `MOUSER_API_KEY` repository secrets. Run it by hand from the Actions tab
  with **Run workflow**.

### Sync schedule (Milestone 3)

The sync runs every 12 hours, at 11:41 and 23:41 UTC (5:41 am and 5:41 pm US Central).

- **The data changes faster than I expected.** Between my Oct 28 fetch and the first sync on Nov 14,
  561 of 1,462 parts (38%) changed stock, lead time, or price, and 149 new parts appeared. Between two
  syncs 17 hours apart, 124 parts changed and 28 were new. Two runs 11 minutes apart changed nothing,
  so more often than a few times a day would mostly re-read the same values.
- **My decisions need same-day data, not up-to-the-minute data.** I build pick lists
  anywhere from several times a day to once a week, and a quote or order still takes an email round trip,
  so stock that is at most 12 hours old is good enough to choose a vendor.
- **It fits the API limit with room to spare.** Each run makes about 200 calls, so two runs use about 400
  of Mouser's 1,000 calls a day and leave room for manual runs and testing.
- The morning run gives me fresh data before I start my day; the evening run keeps it on a 12-hour cycle.
- `scripts/status.py` flags the data as stale after 13 hours (12 plus an hour for GitHub's schedule delays).

## Credits

<!-- Your data API's required attribution, plus any open-source code or samples you used. -->

Part data: Mouser Electronics Search API (https://www.mouser.com). Data shown is attributed to Mouser Electronics.
