# ☁️ Nimbus: company briefings for relationship managers

Nimbus turns three separate Python notebooks (company financials, company news,
stock prices and analyst ratings) into one browser-based application. A
relationship manager (RM) can compare companies, review formatted financials,
read sourced news, record meeting notes, save the whole briefing, and later
search for it and reopen it exactly as it was.

Built for SMU DS600 *Cloud Computing for Economics* (end-term group project).

> **Status (v0.8.0).** Features 1–5 work end to end in GitHub Codespaces
> (SQLite and local files). On AWS, Stage 1 (VPC + EC2 via CloudFormation) has
> been deployed in the Sandbox; Stage 2 adds Amazon RDS for MySQL and is ready
> for its Sandbox run. Auto scaling (Feature 6) follows the Week 9 lesson; see
> [Project status](#project-status) and [Known limitations](#known-limitations).

---

## Contents

1. [Quick start (Codespaces)](#quick-start-codespaces)
2. [Using Nimbus: the demo flow](#using-nimbus-the-demo-flow)
3. [Project status](#project-status)
4. [How it works](#how-it-works)
5. [Project structure](#project-structure)
6. [Data sources and calculation methods](#data-sources-and-calculation-methods)
7. [Storage and database design](#storage-and-database-design)
8. [Configuration](#configuration)
9. [Testing](#testing)
10. [Deploying to AWS](#deploying-to-aws)
11. [Known limitations](#known-limitations)
12. [Team and contributions](#team-and-contributions)

---

## Quick start (Codespaces)

From the repository folder in a terminal:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 -m streamlit run src/app.py
```

Codespaces then offers to open port 8501. Make the port **Public** if asked,
then choose **Open in Browser**.

`src/app.py` is the only application entry point. The app needs internet
access because it retrieves live data from Yahoo Finance.

The notebooks in `notebooks/` are the original prototypes. To run them, also
install Jupyter support: `pip install jupyter ipykernel`.

---

## Using Nimbus: the demo flow

1. **New briefing:** in **Find companies**, type a company name or ticker and
   press Enter (`nvidia`, `Google`, `MU`), or a list (`Apple, Microsoft, DBS`).
   - Well-known names are added at once. For other names Nimbus searches Yahoo
     Finance and lists the matches (e.g. *NVIDIA Corporation (NVDA) · NASDAQ*)
     with an **Add** button.
   - A misspelling gives one short message with a suggestion
     ("No company found for “Microsft”. Did you mean Microsoft Corporation (MSFT)?").
   - Chosen companies appear as chips (click × to remove) and in a check list
     showing name, ticker and exchange. Where a name has several listings
     (Google → GOOGL or GOOG), the list lets you switch.
   - **Quick add** in the sidebar adds popular tickers. Up to 6 companies.

   Then choose a share-price period and select **Generate briefing**. Any
   company Yahoo cannot supply is listed in one collapsible notice.
2. **📊 Compare:** a card per company (last close with period return, market
   cap, P/E), the financial comparison table, an interactive share-price chart
   rebased to 100 (hover for date and actual price), the **analyst view**
   (share of buy/hold/sell ratings, consensus, mean price target and upside)
   and **earnings** (next date and EPS estimate; last result as beat or miss).
3. **📑 Financials:** annual statement line items, formatted in millions,
   billions or trillions.
4. **📰 News:** one feed for all companies, newest first, filterable by
   company. Each card shows the linked headline, company, publisher, how long
   ago it was published, the summary and a thumbnail where Yahoo provides one.
   **Save to note** keeps an article with the RM note.
5. **📝 Notes:** fill in the meeting note (any articles you saved are
   listed), then select **💾 Save briefing and RM notes**. You can also save
   from any tab with **💾 Save briefing** next to the briefing summary: it saves
   at once if the note is filled in, or opens the note in a pop-up if not. An
   "Unsaved briefing" marker shows until it is saved; a confirmation appears
   and the briefing is listed under Recent briefings straight away. Each
   briefing can be saved once.
6. **🗂️ History:** filter by ticker, date range, client reference or analysis
   type; choose a result and select **Open briefing**. The five most recent
   briefings are also one click away in the sidebar. A reopened briefing is
   labelled as a historical snapshot and is never refreshed.

---

## Project status

Features are those agreed in the Lesson 4 Feature Request Workshop. Marking
criteria are from the Lesson 5 slides.

| # | Feature | What Nimbus does | Status |
|---|---|---|---|
| 1 | Unified UI | One app combining financials, news and price/ratings; numbers formatted ($416.16B, 12.3%); news shows summary, publisher, date and source link; companies can be found by name or ticker | ✅ Working locally |
| 2 | Company comparison | Two or more companies; revenue and net-income growth, net margin, return on assets, debt-to-assets, P/E, market cap; rebased share-price chart and holding-period return | ✅ Working locally |
| 3 | Storage: save analysis | Complete briefing saved as a Markdown file (plus JSON snapshot) in `analyses-data/`; listed and reopened without re-downloading | ✅ Working locally; on EC2 the folder is on the instance's EBS volume |
| 4 | Storage: RM notes | Structured meeting note saved with, and linked to, its briefing | ✅ Working locally |
| 5 | Database search | Metadata in SQL tables; search by ticker, date range, client reference, analysis type; open the matching briefing | ✅ Working with SQLite; tests also pass on MySQL-compatible MariaDB. ⏳ RDS template ready, Sandbox run pending |
| 6 | Scaling | Automatically add and remove capacity | ⏳ Not started (taught in Week 9) |

| Marking area | Where to look |
|---|---|
| Repo completeness | This README, `requirements.txt`, `.gitignore`, `.env.example`, `tests/`, `scripts/` |
| Features & functionality | Table above; acceptance test in `tests/test_app_workflow.py` |
| Cloud hosting | [Deploying to AWS](#deploying-to-aws) |

---

## How it works

```mermaid
flowchart LR
    RM([RM in a browser]) --> UI[src/app.py<br/>Streamlit UI]
    UI -->|tickers, period| B[services/briefing_builder.py]
    B -->|cached 15 min| Y[services/yahoo.py] --> YF[(Yahoo Finance<br/>via yfinance)]
    B --> A[analytics/<br/>ratios, performance]
    UI -->|Save briefing + note| S[storage/briefing_store.py]
    S --> F[(analyses-data/<br/>.md + .json files<br/>EBS on AWS)]
    S --> D[(SQL metadata<br/>SQLite locally<br/>RDS MySQL on AWS)]
    UI -->|Search history| D
    UI -->|Open briefing| F
```

**Generate.** `briefing_builder` fetches prices and company data per ticker.
Results are cached for 15 minutes, so changing other widgets never calls
Yahoo again. If one ticker fails it is reported, and the others continue.

**Compare.** `analytics/` computes normalized measures. Missing inputs give
N/A, never zero.

**Save.** The briefing and note are written first to two files, then to the
database in one transaction. If the database write fails, the files are
removed, so file storage and database never disagree. Saving the same
briefing twice is refused.

**Search and reopen.** SQL queries on the metadata find the briefing. The app
then reads its JSON snapshot. Reopening never contacts Yahoo.

---

## Project structure

```text
.
├── src/
│   ├── app.py                    # Streamlit UI: the only entry point
│   ├── config.py                 # settings read from environment variables
│   ├── models/briefing.py        # Briefing, CompanySnapshot, NewsItem, RmNote
│   ├── services/
│   │   ├── yahoo.py              # all yfinance calls and parsing (from the notebooks)
│   │   ├── company_lookup.py     # resolve_company(): names/tickers -> ranked matches
│   │   └── briefing_builder.py   # combines several companies into one briefing
│   ├── ui/
│   │   ├── theme.py              # design system: palette, CSS, chips, section titles
│   │   ├── charts.py             # Altair: rebased share prices, analyst ratings bar
│   │   └── tables.py             # comparison table styling, analyst/earnings tables, ⚠ flags
│   ├── analytics/
│   │   ├── ratios.py             # growth rates and financial ratios
│   │   ├── performance.py        # rebased prices, holding-period return
│   │   └── formatting.py         # $M/$B, percentages, N/A
│   └── storage/
│       ├── snapshots.py          # Markdown + JSON files in analyses-data/
│       ├── database.py           # SQL schema, insert, search (SQLite or RDS)
│       └── briefing_store.py     # save once / reopen, keeping files and DB in step
├── tests/                        # pytest: calculations, parsing, storage, full UI workflow
├── notebooks/                    # original notebooks (unchanged)
├── scripts/                      # nimbus-stack.yaml (deployment), check_database.py, debug_news.py, lesson templates
├── docs/aws-deployment.md        # step-by-step AWS deployment and evidence checklist
├── lessons/                      # course lesson notes
├── requirements.txt              # app dependencies
├── requirements-dev.txt          # + pytest
├── .streamlit/config.toml        # dark theme, one accent colour (#2563EB)
├── .env.example                  # configuration variable names (no secrets)
└── .gitignore                    # excludes .venv/, analyses-data/, *.db, .env
```

`src/analysis.py` and `src/analysis_storage.py` from the Lesson 5–7 version
were replaced by `services/yahoo.py` and `storage/snapshots.py`. They remain
in the Git history on `main`.

---

## Data sources and calculation methods

**Source.** All data comes from Yahoo Finance through the `yfinance` package:
daily adjusted prices, annual income statement, balance sheet and cash flow,
market cap, trailing P/E, analyst recommendation counts and news. Every saved
company records its source, a link to its Yahoo quote page and the time it
was retrieved. Every news item keeps its own publisher, publication date and
source link. Nimbus never writes its own news summaries or links: if Yahoo
gives none, the app says so.

**Measures** (FY = latest fiscal year, FY−1 = the previous one):

| Measure | Formula |
|---|---|
| Revenue growth | Revenue(FY) ÷ Revenue(FY−1) − 1 |
| Net income growth | Net income(FY) ÷ Net income(FY−1) − 1; N/A if FY−1 is zero or negative |
| Net profit margin | Net income(FY) ÷ Revenue(FY) |
| Return on assets | Net income(FY) ÷ Total assets at FY year-end |
| Debt-to-assets | Total debt ÷ Total assets at FY year-end |
| P/E (trailing), market cap | As reported by Yahoo at retrieval time; a negative P/E shows N/A |
| Rebased share price | Adjusted close ÷ adjusted close on the first common date × 100 |
| Holding-period return | Last ÷ first adjusted close − 1, over dates every company traded |
| Upside to target | Analysts' mean price target ÷ last close − 1 |
| Earnings surprise | (Reported EPS − estimate) ÷ \|estimate\|; beat if reported > estimate |

**Rules.**
- A measure is N/A when an input is missing or a denominator is zero or negative.
- Balance-sheet values are only combined with income-statement values from the same fiscal year-end.
- Companies may have different fiscal year-ends; the comparison table shows which year each uses.
- Adjusted prices include dividends and splits.
- All measures are historical, not forecasts.

---

## Storage and database design

This follows the course design:
- **Lesson 7:** save the analysis as a Markdown file on disk, which is EBS on AWS.
- **Lesson 8:** save metadata about each file in a database and search it with SQL instead of guessing filenames.

**Files** (`analyses-data/`, excluded from Git):
- `AAPL-MSFT__company-briefing__20261024T130501Z__1a2b3c4d.md`: readable briefing, downloadable from the app.
- The matching `.json` file: the exact snapshot used to reopen the briefing.

**Tables:**

| Table | Columns | Purpose |
|---|---|---|
| `briefings` | `briefing_id` (PK, UUID), `created_at`, `saved_at`, `analysis_date`, `analysis_type`, `analysis_period`, `client_reference`, `tickers`, `filename`, `json_filename`, `schema_version`, `app_version` | One row per saved briefing |
| `briefing_tickers` | `id` (PK), `briefing_id` (FK), `ticker` | One row per company in a briefing |
| `rm_notes` | `note_id` (PK), `briefing_id` (FK, unique), `meeting_date`, `next_review_date`, `discussion_summary`, `client_priorities`, `follow_up_actions`, `free_text`, `created_at` | The RM's meeting note |

Joining `briefings` and `briefing_tickers` gives the Lesson 8 example table
(`ticker`, `analysis_type`, `date`, `filename`). For example, every briefing
that includes Micron:

```sql
SELECT b.saved_at, b.tickers, b.client_reference, b.filename
FROM briefings b
WHERE b.briefing_id IN (SELECT briefing_id FROM briefing_tickers WHERE ticker = 'MU')
ORDER BY b.saved_at DESC;
```

Tables are created automatically on first run. The code uses SQLAlchemy, so
the same queries run on SQLite locally and on Amazon RDS for MySQL on AWS;
only `NIMBUS_DATABASE_URL` changes.

---

## Configuration

Nimbus reads environment variables; see `.env.example` for the names. With
nothing set, it uses `analyses-data/` and a SQLite file inside it.

| Variable | Default | Purpose |
|---|---|---|
| `NIMBUS_DATA_DIR` | `<repo>/analyses-data` | Where briefing files are written |
| `NIMBUS_DATABASE_URL` | `sqlite:///<repo>/analyses-data/nimbus.db` | Metadata database; for RDS: `mysql+pymysql://<user>:<password>@<endpoint>:3306/<db>` |

Never commit real credentials. `.env` files are ignored by Git.

---

## Testing

**Automated tests.** These need no internet; Yahoo is replaced by
`tests/fake_yahoo.py`:

```bash
pip install -r requirements-dev.txt
python -m pytest
```

They cover:
- formatting, ratio and return calculations, including N/A cases;
- news and statement parsing;
- saving exactly once;
- rollback when the database fails;
- search filters;
- reopening without calling Yahoo;
- `tests/test_app_workflow.py`, which drives the real Streamlit app through
  the full acceptance workflow: generate → compare → note → save → search →
  reopen → restart → reopen → invalid ticker.

**Against MySQL.** The same suite can run against a MySQL database instead of
SQLite (use an empty, throwaway database; its Nimbus tables are dropped before
each test):

```bash
NIMBUS_TEST_DATABASE_URL='mysql+pymysql://<user>:<password>@127.0.0.1:3306/nimbus_test' python -m pytest
```

All 88 tests pass on MariaDB 10.11 (MySQL-compatible) through PyMySQL.
`python scripts/check_database.py` checks that the configured database is
reachable and its tables exist, printing only the host and row counts, never
the password.

Verified on Python 3.13 (Streamlit 1.66, pandas 3.1, Altair 6) and Python 3.9
(Streamlit 1.50, pandas 2.3, Altair 5). Python 3.9 is the version on Amazon
Linux 2023. Streamlit 1.44 or newer is required.

**News troubleshooting.** If the News tab says news could not be retrieved,
see exactly what Yahoo returns:

```bash
python scripts/debug_news.py AAPL MSFT
```

It prints the raw output of yfinance's news feed and of Yahoo search (which
Nimbus falls back to when the feed is empty), any yfinance warnings, and how
many articles Nimbus could read.

**Manual check with live data** (run in Codespaces before every demo):

1. Fresh venv, `pip install -r requirements.txt`, start the app.
2. In Find companies type `nvid` and press Enter: NVIDIA (NVDA) · NASDAQ is
   offered; add it. Then type `Apple, Microsoft` and press Enter. Check the
   list shows names, tickers and exchanges, then generate.
3. Check the chart, comparison table and formatted financials.
4. Check that news shows links, publishers and dates.
5. Enter a note and save. The save button disappears and the filename is shown.
6. In Briefing history, the caption shows 1 briefing, 2 ticker records and 1 RM note.
7. Search `MSFT`, then open the briefing. It shows the snapshot banner and your note.
8. Stop the app (Ctrl+C), start it again, then search and open again.
9. Generate `AAPL, ZZZZ, MSFT`. ZZZZ is reported and the others still load.

---

## Deploying to AWS

Nimbus is deployed with CloudFormation from [`scripts/nimbus-stack.yaml`](scripts/nimbus-stack.yaml).
Full steps, evidence checklist, troubleshooting and clean-up are in
[`docs/aws-deployment.md`](docs/aws-deployment.md).

In short:
1. Push to GitHub. EC2 clones from GitHub.
2. In the Sandbox, open **CloudFormation → Create stack → Upload a template file**, choose
   `scripts/nimbus-stack.yaml`, name the stack `nimbus`, type a new `DBPassword`
   (letters and digits, never a real password), and set `GitBranch` if not `main`.
3. Wait for `CREATE_COMPLETE` (about 15–20 minutes, mostly RDS). It is only reported after
   Nimbus has connected to RDS and answers its health check.
4. Open the `NimbusUrl` output (http://…:8501).

| Stage | What it adds | Status |
|---|---|---|
| 1 | VPC with public and private subnets, security group, EC2 installed by user data and run as a systemd service | ✅ Deployed in the Sandbox (`CREATE_COMPLETE`, app reachable) |
| 2 | Amazon RDS for MySQL in the private subnets, reachable only from the app server | Template ready (cfn-lint clean); Sandbox run pending |
| 3 | Scaling (Week 9 lesson) | Not started |

`scripts/lesson5.yaml` and `scripts/lesson5-nimbus.yaml` are the course's
Lesson 6–7 templates, kept for reference.

## Known limitations

- **Yahoo Finance via yfinance** is an unofficial interface. Fields can be
  missing or change format; Nimbus shows N/A or "not provided" rather than
  guessing. Statement coverage is usually the last four fiscal years.
- **News** is the latest available at retrieval time; Yahoo does not provide
  historical news searches. yfinance's news feed returns an empty list rather
  than an error when Yahoo's news service misbehaves, so Nimbus then tries
  Yahoo search and reports which source it used, or the real error.
- **Ratios** use annual statements only (no quarterly or trailing-twelve-month
  figures).
- **Analyst targets and earnings dates** are third-party figures from Yahoo at
  the time of retrieval; earnings dates can move, and coverage is thinner for
  non-US listings (shown as N/A). Nimbus shows them for context and makes no
  recommendation of its own.
- **Saved articles** are stored in the briefing's snapshot files (Markdown and
  JSON), not as separate database rows.
- **Unusual values are flagged, not changed.** A trailing P/E above 100x or an
  EPS surprise above ±100% is shown as reported with a ⚠ marker, because such
  figures often reflect one-off items or depressed earnings.
- **Layout** is capped at 1300px wide. If the page still looks narrow, check
  **⋮ → Settings → Wide mode** in the app menu (a per-browser setting).
- **Files are local to one machine.** Briefings saved in Codespaces and on EC2
  are separate. With auto scaling (several EC2 instances), a briefing saved on
  one instance's disk would not be readable from another. The storage design
  must be revisited for Feature 6.
- **Database password handling.** The RDS password is a `NoEcho` CloudFormation
  parameter. On the instance it is kept in `/etc/nimbus.env` (readable by root
  only) and setup logging is switched off before it is written. It is still
  part of the instance's user data, which anyone with EC2 console access to the
  account can view. AWS Secrets Manager would avoid that; it is beyond the
  course requirements and was not used.
- **Sandbox database settings:** single-AZ, 20 GB, no automated backups, and
  deleted together with the stack. These keep the Sandbox cost and creation
  time low; production would use Multi-AZ and backups.
- **No user accounts:** everyone using an instance sees the same history.
- **Analysis type** is always `company_briefing` in this version; the filter
  exists so other analysis types can be added later.
- **Company search** runs when you press Enter, not on every keystroke
  (true as-you-type search would need a third-party Streamlit component and a
  Yahoo call per key press). Results are cached for a day.
- **Name lookup** first checks a built-in list of about 90 well-known names
  (US large caps, major SGX stocks), then Yahoo Finance search. Search results
  are ranked by listing (US primary exchanges, then other primary exchanges,
  then over-the-counter) and Yahoo's relevance, not by market capitalisation.
  If Yahoo search is unreachable, ticker symbols still work.
- **Windows:** keep the project outside Google Drive, OneDrive or Dropbox
  folders. Cloud-synced folders lock files and cause "Permission denied"
  errors (and can corrupt `.git`).

---

## Team and contributions

| Member | Responsibilities | Main contributions |
|---|---|---|
| _Name_ | _e.g. data layer, calculations_ | _to be completed by the team_ |
| _Name_ | _e.g. UI, storage, database_ | _to be completed by the team_ |
| _Name_ | _e.g. CloudFormation, AWS deployment_ | _to be completed by the team_ |

Course: SMU DS600 Cloud Computing for Economics. Starter repository and lessons
by Gaurav Chaturvedi.
