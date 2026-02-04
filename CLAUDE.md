# FEC Monitor

FastAPI application that monitors FEC filings (F3X and Schedule E) and provides dashboards and email alerts.

## GCP Deployment

All resources are in the **freeway-2026** GCP project:
- **Service**: `fec-monitor` (Cloud Run)
- **Job**: `fec-ingest-job` (Cloud Run Job)
- **Cron**: `fec-ingest-job-trigger` (Cloud Scheduler)
- **Database**: `fec-db` (Cloud SQL Postgres)
  - User: `fec`
  - Password: `dkDoB85i6u`

Note: Other resources in this project are outdated and no longer relevant.

## Project Structure

```
app/
  api.py          # FastAPI routes (dashboards, API, config)
  backfill.py     # Historical data backfill from FEC API
  db.py           # Database engine setup
  schemas.py      # SQLModel schemas (FilingF3X, IEScheduleE, etc.)
  ingest_f3x.py   # F3X RSS feed ingestion
  ingest_ie.py    # Schedule E RSS feed ingestion
  fec_parse.py    # FEC file parsing (includes light header-only parser)
  fec_lookup.py   # Committee name resolution
  email_service.py # Email alert sending
  repo.py         # Database helpers (claim_filing, config getters)
  settings.py     # Environment config
  auth.py         # Admin authentication
  templates/      # Jinja2 HTML templates

scripts/
  ingest_job.py   # Cloud Run Job for continuous ingestion
```

## Architecture

### Cloud Run Service vs Job

- **Service** (`fec-monitor`): Web UI, dashboards, config page, cron endpoint
- **Job** (`fec-ingest-job`): Continuous ingestion that loops until caught up

The job is triggered by Cloud Scheduler every 5 minutes. It processes filings in batches until no new filings are found, then exits.

### Ingestion Flow

1. RSS feed is fetched (contains ~5000+ items)
2. For each item, `claim_filing()` marks it as seen in `seen_filings` table
3. FEC file is downloaded and parsed (header only for F3X)
4. Filing data is saved to database
5. After all batches complete, email alerts are sent (if enabled)

**Important**: If a filing is claimed but the download/parse fails (e.g., OOM), it won't be retried automatically. See "Recovering Failed Filings" below.

## Config Settings (via /config page)

- **Email alerts enabled**: Toggle to disable emails during backfill
- **Max filings per run**: Limit per batch to avoid OOM (default: 50)

These are stored in the `app_config` table and read at runtime.

## Memory Optimization

The app runs on Cloud Run with limited memory. Key optimizations:

1. **Light header-only parser** - `parse_f3x_header_only()` extracts just summary fields without loading itemizations
2. **Lazy fecfile import** - Heavy library only loaded when needed
3. **Explicit gc cleanup** - `del fec_text; del parsed; gc.collect()` after each filing
4. **Truncated raw_line** - Schedule E events store only first 200 chars
5. **Batch limits** - Configurable `max_new_per_run` to prevent runaway memory

### Recommended Memory Settings

- **Service**: 2 GiB (handles web requests)
- **Job**: 8 GiB (processes large filings)

Some FEC filings are enormous (100MB+). If OOM occurs:
1. Increase job memory
2. Or lower `max_new_per_run` in config
3. The problematic filing will be skipped (already marked as seen)

## Deployment

### Service
```bash
gcloud run deploy fec-monitor \
  --image=us-central1-docker.pkg.dev/PROJECT/fec-monitor/fec-monitor:TAG \
  --region=us-central1 \
  --memory=2Gi
```

### Job
```bash
gcloud run jobs update fec-ingest-job \
  --image=us-central1-docker.pkg.dev/PROJECT/fec-monitor/fec-monitor:TAG \
  --region=us-central1 \
  --memory=8Gi
```

### Cloud Scheduler
- `fec-ingest-job-trigger`: Runs every 5 min, triggers the job
- `fec-monitor-check`: Old HTTP cron (can be disabled if using job)

## Environment Variables

See `app/settings.py`:
- `POSTGRES_URL` - PostgreSQL connection string
- `CONFIG_PASSWORD` - Password for /config endpoints
- `GOV_API_KEY` - FEC API key (optional, falls back to DEMO_KEY)
- `GOOGLE_APP_PW` - Gmail app password for email alerts
- `EMAIL_FROM` - Sender email address
- `RECEIPTS_THRESHOLD` - Min receipts for F3X alerts (default: 50000)

## Endpoints

### Dashboards (HTML)
- `GET /dashboard/3x` - Today's F3X filings
- `GET /dashboard/e` - Today's Schedule E events
- `GET /{year}/{month}/{day}/3x` - Historical F3X
- `GET /{year}/{month}/{day}/e` - Historical Schedule E

### API (JSON)
- `GET /api/3x/today` - Today's F3X filings
- `GET /api/e/today` - Today's Schedule E events
- `GET /api/cron/check-new` - Cron endpoint for ingestion + alerts

### Admin (password-protected)
- `GET /config` - Config page (settings, email recipients, job status)
- `POST /config/settings/email_enabled` - Toggle email alerts
- `POST /config/settings/max_new_per_run` - Set batch size limit
- `POST /config/recipients` - Add email recipient
- `POST /config/backfill/{year}/{month}/{day}/{type}` - Trigger manual backfill

## TODO / Known Issues

### Recovering Failed Filings

Some filings may be "claimed but not saved" if OOM occurred during download/parse. To find and retry them:

```sql
-- Find claimed filings that don't have data
SELECT sf.filing_id
FROM seen_filings sf
LEFT JOIN filing_f3x f ON sf.filing_id = f.filing_id
WHERE f.filing_id IS NULL AND sf.source_feed != 'BACKFILL';

-- Delete from seen_filings to allow retry
DELETE FROM seen_filings WHERE filing_id IN (...);
```

Then run the job again with sufficient memory.
