# FEC Monitor

FastAPI application that monitors FEC filings (F3X and Schedule E) and provides dashboards and email alerts. Also serves Category View API for the Issue Map frontend.

## GCP Deployment

All resources are in the **freeway2026** GCP project:
- **Service**: `fec-monitor` (Cloud Run)
- **Job**: `fec-ingest-job` (Cloud Run Job)
- **Cron**: `fec-ingest-job-trigger` (Cloud Scheduler)
- **Database**: `fec-db` (Cloud SQL Postgres)
  - User: `fec`
  - Password: `dkDoB85i6u`

Note: Other resources in this project are outdated and no longer relevant.

### CI/CD

GitHub Actions workflow (`.github/workflows/deploy.yml`) auto-deploys on push to `main`:
1. Builds Docker image, pushes to Artifact Registry
2. Deploys Cloud Run service (`fec-monitor`, 2Gi)
3. Updates Cloud Run job (`fec-ingest-job`, 4Gi)

Required GitHub secrets: `GCP_PROJECT_ID`, `GCP_SA_KEY`, `POSTGRES_URL`, `GOOGLE_APP_PW`, `EMAIL_FROM`, `CONFIG_PASSWORD`, `GOV_API_KEY`, `CLOUD_SQL_CONNECTION`.

### Local Development

```bash
# Start Cloud SQL proxy (port 5433)
cloud-sql-proxy freeway2026:us-central1:fec-db

# Run app (reads .env for POSTGRES_URL, etc.)
uvicorn app.main:app --reload --port 8080
```

## Project Structure

```
app/
  api.py          # FastAPI routes (dashboards, API, config, category view)
  backfill.py     # Historical data backfill from FEC API
  db.py           # Database engine setup
  schemas.py      # SQLModel schemas (FilingF3X, IEScheduleE, ScheduleA, DonorIndustry, OrgIndustry, etc.)
  ingest_f3x.py   # F3X RSS feed ingestion
  ingest_ie.py    # Schedule E RSS feed ingestion
  ingest_sa.py    # Schedule A second-pass ingestion (target PACs only)
  fec_parse.py    # FEC file parsing (includes light header-only parser + SA/SE extractors)
  fec_lookup.py   # Committee name resolution
  email_service.py # Email alert sending
  repo.py         # Database helpers (claim_filing, config getters, PAC groups)
  settings.py     # Environment config
  auth.py         # Admin authentication
  templates/      # Jinja2 HTML templates

scripts/
  ingest_job.py        # Cloud Run Job for continuous ingestion
  load_industries.py   # Load OpenSecrets industry CSVs into Postgres
  test_sa_parse.py     # Smoke test for Schedule A parsing
```

## Architecture

### Cloud Run Service vs Job

- **Service** (`fec-monitor`): Web UI, dashboards, config page, cron endpoint, Category View API
- **Job** (`fec-ingest-job`): Continuous ingestion that loops until caught up

The job is triggered by Cloud Scheduler every 5 minutes. It processes filings in batches until no new filings are found, then exits.

### RSS Feed

The FEC RSS feed (`efilingapps.fec.gov/rss/generate`) returns all filings from the **last 7 days**. There is no documented item limit or hard cap — the feed appears to return everything within that window regardless of volume. The feed is not paginated. On quiet days this may be a few hundred items; on quarterly deadline days it could be much larger.

### Ingestion Flow

1. RSS feed is fetched and walked newest-first
2. Only today's filings are processed (stops when `pub_date < today`)
3. For each item, `claim_filing()` attempts an INSERT into `ingestion_tasks` with `status='claimed'` — if the row already exists, the filing is skipped
4. Status is updated through substeps: `claimed` → `downloading` → `downloaded` → `parsing` → `ingested`
5. On download failure: status set to `failed` with `failed_step='downloading'` and error details
6. On parse failure: status set to `failed` with `failed_step='parsing'` and error details
7. On oversized files: status set to `skipped` with `skip_reason='too_large'` and file size
8. After all batches complete, email alerts are sent (if enabled) and `emailed_at` is set

The `ingestion_tasks` table tracks the full lifecycle in one place: status, substep, error details, skip metadata, and email tracking. Use `reset_failed_tasks()` in `app/repo.py` to retry failed filings programmatically.

### Schedule A Ingestion (Second Pass)

After F3X header + IE ingestion, a second pass downloads the full F3X file for **target PACs only** (configurable via `sa_target_committee_ids` in `app_config`) and extracts Schedule A (individual contribution) items.

- Uses `source_feed="SA"` in `ingestion_tasks` for independent tracking from `"F3X"` header pass
- Processes one filing at a time with `gc.collect()` after each (memory safety)
- 50MB file size limit
- Manual parse endpoint: `POST /config/parse-sa` (accepts `filing_id`)

## Config Settings (via /config page)

- **Email alerts enabled**: Toggle to disable emails during backfill
- **Max filings per run**: Limit per batch to avoid OOM (default: 50)
- **Per-recipient committee filtering**: Each email recipient can optionally have a `committee_ids` list (JSONB)
- **SA target committee IDs**: Comma-separated list of PAC committee IDs for Schedule A parsing
- **PAC groups**: JSON editor for themed PAC groups (used by Category View API)

These are stored in the `app_config` table (settings) and `email_recipients` table (recipient filters) and read at runtime.

## Memory Optimization

The app runs on Cloud Run with limited memory. Key optimizations:

1. **Light header-only parser** - `parse_f3x_header_only()` extracts just summary fields without loading itemizations
2. **Lazy fecfile import** - Heavy library only loaded when needed
3. **Explicit gc cleanup** - `del fec_text; del parsed; gc.collect()` after each filing
4. **Truncated raw_line** - Schedule E/A events store only first 200 chars
5. **Batch limits** - Configurable `max_new_per_run` to prevent runaway memory

### Recommended Memory Settings

- **Service**: 2 GiB (handles web requests)
- **Job**: 8 GiB (processes large filings)

## Deployment

Deployment is automatic via GitHub Actions on push to `main`. For manual deployment:

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
- `GET /dashboard/3x` - Today's F3X filings (supports `?threshold=` filter, default $50k)
- `GET /dashboard/e` - Today's Schedule E events
- `GET /{year}/{month}/{day}/3x` - Historical F3X (supports `?threshold=` filter)
- `GET /{year}/{month}/{day}/e` - Historical Schedule E

Dashboard nav links are date-aware — clicking "3X Dashboard" or "Schedule E Dashboard" navigates to the currently displayed date, not always today.

### API (JSON)
- `GET /api/3x/today` - Today's F3X filings
- `GET /api/e/today` - Today's Schedule E events
- `GET /api/cron/check-new` - Cron endpoint for ingestion + alerts

### Category View API (JSON, CORS enabled)
- `GET /api/category/groups` - All PAC groups with summary totals (contributions + IE spending)
- `GET /api/category/pac/{committee_id}/industries` - Industry breakdown for a PAC
- `GET /api/category/pac/{committee_id}/donors` - Top donors with industry (filterable by `?industry=`)
- `GET /api/category/pac/{committee_id}/candidates` - IE spending by candidate
- `GET /api/category/pac/{committee_id}/candidates/{candidate_id}/industries` - Attributed industry spending for a candidate

### Admin (password-protected)
- `GET /config` - Config page (settings, email recipients, job status, PAC groups)
- `POST /config/settings/email_enabled` - Toggle email alerts
- `POST /config/settings/max_new_per_run` - Set batch size limit
- `POST /config/settings/sa_target_committee_ids` - Set Schedule A target PACs
- `POST /config/settings/pac_groups` - Update PAC groups JSON
- `POST /config/parse-sa` - Manually parse Schedule A from a filing
- `POST /config/recipients` - Add email recipient (with optional `committee_ids`)
- `POST /config/recipients/{id}/committees` - Update recipient's committee filter
- `POST /config/recipients/{id}/delete` - Remove recipient
- `POST /config/backfill/{year}/{month}/{day}/{type}` - Trigger manual backfill

## Industry Matching

Two lookup tables loaded from OpenSecrets data (`scripts/load_industries.py`):
- `donor_industries` (58,802 rows) — individual donor name → industry
- `org_industries` (18,697 rows) — organization name → industry

Industry matching SQL pattern (used in all Category View endpoints):
```sql
COALESCE(
    NULLIF(o.industry, ''),   -- org match on contributor_name
    NULLIF(e.industry, ''),   -- employer match on contributor_employer
    NULLIF(d.industry, ''),   -- donor match on contributor_name
    'Unclassified'
) AS industry
FROM schedule_a sa
LEFT JOIN donor_industries d ON UPPER(sa.contributor_name) = d.name_upper
LEFT JOIN org_industries o ON UPPER(sa.contributor_name) = o.org_upper
LEFT JOIN org_industries e ON UPPER(sa.contributor_employer) = e.org_upper
```

Priority: org match > employer match > donor name match > Unclassified.

### PAC Groups

Stored as JSONB in `app_config` key `pac_groups`. Four groups:
- **Pro-Israel**: UDP (C00799031), DMFI (C00710848)
- **Pro-Trump**: MAGA Inc. (C00825851), AmericaPAC (C00879510), Preserve America (C00878801), American Crossroads (C00487363), Right for America (C00867036), Restoration PAC (C00571588)
- **Crypto**: Fairshake (C00835959), Protect Progress (C00848440), Defend American Jobs (C00836221), Digital Freedom Fund (C00911610)
- **AI**: Leading the Future (C00916114), Think Big (C00923417), American Mission (C00916692), Public First (C00930503), Defending our Values (C00928390), Jobs and Democracy (C00928374)

Editable via `/config` page (JSON textarea).

### Reloading Industry Data

```bash
python -m scripts.load_industries \
  --donors-csv ~/Documents/code/issue_map/data/donors_by_industry.csv \
  --orgs-csv ~/Documents/code/issue_map/data/orgs_by_industry.csv \
  --truncate-first
```

## TODO / Known Issues

### Recovering Failed Filings

```sql
-- Find failed filings with error details
SELECT filing_id, source_feed, status, failed_step, error_message, updated_at
FROM ingestion_tasks
WHERE status IN ('failed', 'claimed');

-- Reset failed filings for retry
UPDATE ingestion_tasks
SET status = 'claimed', failed_step = NULL, error_message = NULL, updated_at = NOW()
WHERE status = 'failed';
```

Or use `reset_failed_tasks()` from `app/repo.py` programmatically.

### Future Improvements

- **Stream F3X header parsing** — Currently `download_fec_text` downloads the entire file even though F3X only needs the first ~100 lines. Streaming just the first ~50KB would eliminate the large file problem for F3X entirely.
- **Functional indexes for industry joins** — Consider adding `CREATE INDEX ON schedule_a (UPPER(contributor_name))` and `CREATE INDEX ON schedule_a (UPPER(contributor_employer))` for better query performance as schedule_a grows.
- **org_industries dedup** — The same org name can appear multiple times with different committee IDs, potentially inflating join results. Monitor and add LATERAL/DISTINCT if needed.
