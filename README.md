# Moneris to NetSuite Journal Entries

![Python](https://img.shields.io/badge/python-3.10%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)

Automates posting Moneris POS settlement data to NetSuite as journal entries. The Python backend validates CSV exports, builds balanced JE payloads, uploads them to a NetSuite RESTlet via OAuth 1.0, and stores run history in SQLite.

---

## Workflows

This project supports two Moneris report types:

| Workflow | Entry point | Moneris report | Output |
|----------|-------------|----------------|--------|
| **Sales summary** | `main.py` | Sales Summary by Merchant | SQLite (`Raw_Data`, `JE_Summary`) + CSV in `Summary_Csv_Files/` |
| **Financial adjustment** | `main_finadj.py` | Financial Adjustment | Console summary only |

Both workflows share the same NetSuite RESTlet endpoint and OAuth credentials.

---

## Project structure

```
Moneris/
├── main.py                  # Sales summary pipeline (validate → transform → upload → store)
├── classes.py               # Checkpoint, Transformation, FinalCheckpoint, Loader, Summary
├── main_finadj.py           # Financial adjustment pipeline
├── class_finadj.py          # LoadFinAdj, TransformFinAdj, UploadFinAdj, SummaryFinAdj
├── netsuite_posting_je.js   # NetSuite RESTlet script (deploy in NetSuite)
├── moneris_practice_mapping.csv   # Merchant → NetSuite subsidiary mapping
├── Moneris.db               # SQLite database (not in git)
├── Summary_Csv_Files/       # Generated JE summary CSVs (created on run)
└── .env                     # NetSuite OAuth credentials (not in git)
```

---

## Prerequisites

- Python 3.10+
- Access to **Moneris Merchant Direct**
- NetSuite role with permission to post journal entries and deploy RESTlets
- A deployed copy of `netsuite_posting_je.js` in NetSuite (script/deploy IDs must match the URL in `classes.py` / `class_finadj.py`)

---

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/tzuying-nicoleyu/Moneris_automated_JournalEntry.git
cd Moneris_automated_JournalEntry
pip install pandas requests requests-oauthlib oauthlib aiohttp python-dotenv
```

### 2. Configure NetSuite credentials

Create a `.env` file in the project root (never commit this file):

```env
CLIENT_KEY=your_consumer_key
CLIENT_SECRET=your_consumer_secret
OWNER_KEY=your_token_id
OWNER_SECRET=your_token_secret
REALM=your_account_id
```

### 3. Add required local files

Place these in the project root:

- **`moneris_practice_mapping.csv`** — maps Moneris merchant numbers to NetSuite Internal ID and practice name. Required columns: `Merchant Number`, `Internal ID`, `Name (no hierarchy)`, `Is Practice Closed?`
- **`Moneris.db`** — SQLite database with `Raw_Data` and `JE_Summary` tables (sales summary workflow only)

### 4. Set download folder paths

Update the `download_folder_path` in:

- `classes.py` → `Checkpoint` class (sales summary files matching `Sales Summary by Merchant_Download Date *`)
- `class_finadj.py` → `LoadFinAdj` class (financial adjustment files matching `Financial Adjustment*`)

### 5. Deploy the NetSuite RESTlet

Upload `netsuite_posting_je.js` to NetSuite as a RESTlet. Update the RESTlet URL in `Loader` (`classes.py`) and `UploadFinAdj` (`class_finadj.py`) if your script or deploy ID differs.

---

## Running — Sales summary (`main.py`)

1. Log in to the [Moneris portal](https://www.moneris.com/en/login-portal-hub).
2. Go to **Reports → CSV Downloader**.
3. Select **Sales summary by merchant**, choose the settlement date (or a date range), and download the CSV to your configured folder.
4. Make sure amount columns have **no thousands separators** (see [Input file requirements](#input-file-requirements)).
5. Run:

```bash
python main.py
```

### What `main.py` does

1. **Checkpoint** — reads the latest sales summary CSV, validates columns, totals, card types, and optionally every settlement date in the file
2. **Store raw data** — inserts validated rows into `Moneris.db` (`Raw_Data` table)
3. **Transformation** — merges merchant mapping and builds one NetSuite JE payload per **practice per settlement date**. Warns about merchants missing from the mapping file and lists, for each date, active practices with no payload
4. **FinalCheckpoint** — verifies each payload is balanced (debits = credits)
5. **Loader** — uploads payloads asynchronously to NetSuite (OAuth 1.0, with retries)
6. **Summary** — prints results (one row per journal entry, with that entry's own Net Deposit), saves to `JE_Summary` in SQLite, and exports `Summary_Csv_Files/JE_Summary_YYYY-MM-DD.csv`

### Single-date and multi-date files

The pipeline handles both without any setting:

| File contains | Payloads created | Example `externalid` |
|---------------|------------------|----------------------|
| One settlement date | One per practice | `moneris_83_2026-09-29` |
| Several settlement dates | One per practice per date | `moneris_83_2026-09-01`, `moneris_83_2026-09-02`, … |

Each journal entry's `trandate`, header memo, and `externalid` use its own settlement date. Because the `externalid` format is unchanged for single-date files, NetSuite's duplicate check still recognizes entries posted before this change.

In the summary, results are matched to the source data by `payloadExternalId`, so each row shows the Net Deposit for that practice on that date.

### Options in `main.py`

- Pass a test file: `Checkpoint(test_file_path="path/to/file.csv")`
- Disable settlement date validation: `Checkpoint().run_all_checks(check_date=False)`
- Enable date validation (default): `Checkpoint().run_all_checks()`

With date validation on, **every** settlement date in the file must be expected:

- **Monday** — last Friday and/or last Saturday
- **Any other day** — yesterday only

Any other date raises an error. Turn date validation off (`check_date=False`) when back-loading a date range, such as a month-to-date file.

> **Note:** The script processes one file per run (the most recently modified file in the download folder, or the `test_file_path` you pass). A single file may contain one or many settlement dates.

### Input file requirements

- Required columns: `Settlement Date` (`YYYYMMDD`), `Merchant Number`, `Card Type`, `Net Total`, `Net Deposit`
- Valid card types: 1 (Visa), 2 (Mastercard), 3 (Amex), 6 (Discover), 10 (Interac), 16 (UnionPay)
- **Amounts must be plain numbers** — no thousands separators (`1717.00`, not `"1,717.00"`). Moneris exports sometimes include commas; `pd.read_csv` then reads the amounts as text, and the run fails at `FinalCheckpoint` with `TypeError: unsupported operand type(s) for +: 'int' and 'str'`. Fix it in Excel before running: format `Net Total` and `Net Deposit` as **General** (or **Number** with *Use 1000 Separator* unticked), then save as CSV.

> **Heads-up:** `store_to_sql` runs before `FinalCheckpoint`, so a failed run still writes raw rows to `Raw_Data`. Because inserts use `INSERT OR IGNORE`, a rerun will not overwrite them — delete those rows first if they were stored with bad amounts.

---

## Running — Financial adjustment (`main_finadj.py`)

1. Download the **Financial Adjustment** report from Moneris to your configured folder.
2. Run:

```bash
python main_finadj.py
```

This validates the adjustment CSV, builds one payload per row, uploads to NetSuite, and prints a success/failure/duplicate summary. Unlike the sales workflow, it does not write to SQLite or export a summary CSV.

> **Note:** This workflow still assumes a single `Deposit Date` per file (it uses the first date for every payload). Multi-date support has only been added to the sales summary workflow.

---

## NetSuite RESTlet (`netsuite_posting_je.js`)

The RESTlet accepts a JSON journal entry payload with `trandate`, `memo`, `subsidiary`, `externalid`, and a `lines` array. It validates line shape and balance, checks for duplicate `externalid`, and creates the journal entry. Responses include `report: "success"`, `report: "duplicate"`, or an error object.

---

## Files excluded from git

See `.gitignore`. Do not commit:

- `.env` (credentials)
- `Moneris.db`, `*.csv` (data)
- `debug.ipynb`, `venv/`, `__pycache__/`
