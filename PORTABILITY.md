# Standalone portability

Verified 2026-09-16. No fleet sibling is required. Use a recent start date for
the installation smoke rather than the 523-window full backfill.

```powershell
git clone https://github.com/lucasweber1202/collector_elexon_uk.git
Set-Location collector_elexon_uk
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m pytest -q
ruff check .
mypy .
$env:COLLECTOR_ELEXON_START = (Get-Date).AddDays(-2).ToString('yyyy-MM-dd')
python main.py --source-id elexon_market_index_prices
```

Python 3.11/3.12. Local collection requires `COLLECTOR_DB_URL`; Databricks is
optional. Network: HTTPS to `data.elexon.co.uk`. Snapshots use
`COLLECTOR_RAW_DIR`. TLS verification remains enabled.

Certification: standalone code PASS; sibling required NO; database and internet
required for collection; Databricks not required.
