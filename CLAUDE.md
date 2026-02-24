# FEC Monitor

FastAPI application that monitors FEC filings (F3X and Schedule E) and provides dashboards and email alerts.

## GCP Deployment

All resources are in the **freeway2026** GCP project:
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

### RSS Feed

The FEC RSS feed (`efilingapps.fec.gov/rss/generate`) returns all filings from the **last 7 days**. There is no documented item limit or hard cap — the feed appears to return everything within that window regardless of volume. The feed is not paginated. On quiet days this may be a few hundred items; on quarterly deadline days it could be much larger.

If the feed ever silently truncates on high-volume days, the FEC eFiling API (`api.open.fec.gov`) could be used as an end-of-day reconciliation pass, but this hasn't been needed yet.

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

## Config Settings (via /config page)

- **Email alerts enabled**: Toggle to disable emails during backfill
- **Max filings per run**: Limit per batch to avoid OOM (default: 50)
- **Per-recipient committee filtering**: Each email recipient can optionally have a `committee_ids` list (JSONB). If set, they only receive alerts for filings from those committees. If null/empty, they receive all alerts.

These are stored in the `app_config` table (settings) and `email_recipients` table (recipient filters) and read at runtime.

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
- `GET /dashboard/3x` - Today's F3X filings (supports `?threshold=` filter, default $50k)
- `GET /dashboard/e` - Today's Schedule E events
- `GET /{year}/{month}/{day}/3x` - Historical F3X (supports `?threshold=` filter)
- `GET /{year}/{month}/{day}/e` - Historical Schedule E

Dashboard nav links are date-aware — clicking "3X Dashboard" or "Schedule E Dashboard" navigates to the currently displayed date, not always today.

### API (JSON)
- `GET /api/3x/today` - Today's F3X filings
- `GET /api/e/today` - Today's Schedule E events
- `GET /api/cron/check-new` - Cron endpoint for ingestion + alerts

### Admin (password-protected)
- `GET /config` - Config page (settings, email recipients, job status)
- `POST /config/settings/email_enabled` - Toggle email alerts
- `POST /config/settings/max_new_per_run` - Set batch size limit
- `POST /config/recipients` - Add email recipient (with optional `committee_ids`)
- `POST /config/recipients/{id}/committees` - Update recipient's committee filter
- `POST /config/recipients/{id}/delete` - Remove recipient
- `POST /config/backfill/{year}/{month}/{day}/{type}` - Trigger manual backfill

## Issue Map Integration (Category View API)

The **Issue Map** project (`~/Documents/code/issue_map/`) is a campaign finance visualization frontend that needs API endpoints from this app to power its "Category View" — a browse-by-category interface showing themed PAC groups, their industry breakdowns, and candidate spending.

### What needs to be built

#### 1. Load OpenSecrets industry lookup tables into Postgres

The Issue Map project has two CSV files with industry classifications:
- `~/Documents/code/issue_map/data/donors_by_industry.csv` — individual donor → industry (columns: `ContribID`, `Contrib`, `Orgname`, `RealCode`, `Catname`, `Industry`, `Sector`, `FECTransIDs`)
- `~/Documents/code/issue_map/data/orgs_by_industry.csv` — organization → industry (columns: `CmteID`, `Org`, `PACShort`, `PrimCode`, `Catname`, `Industry`, `Sector`)

Create two new tables in Postgres:
- `donor_industries` — with a `name_upper` column (UPPER of donor name) indexed for fast joins
- `org_industries` — with an `org_upper` column (UPPER of org name) indexed for fast joins

Write a loader script (like `scripts/ingest_comms.py`) that reads these CSVs and loads them. Add SQLModel schemas to `app/schemas.py`.

#### 2. PAC groups configuration

Store themed PAC groups as JSONB in `app_config` with key `pac_groups`. The groups:

- **Pro-Israel**: UDP (C00799031), DMFI (C00710848)
- **Pro-Trump**: MAGA Inc. (C00825851), AmericaPAC (C00879510), Preserve America (C00878801), American Crossroads (C00487363), Right for America (C00867036), Restoration PAC (C00571588)
- **Crypto**: Fairshake (C00835959), Protect Progress (C00848440), Defend American Jobs (C00836221), Digital Freedom Fund (C00911610)
- **AI**: Leading the Future (C00916114), Think Big (C00923417), American Mission (C00916692), Public First (C00930503), Defending our Values (C00928390), Jobs and Democracy (C00928374)

Make editable via `/config` page and exposed via the API.

#### 3. API endpoints for Category View

Add to `app/api.py`:

**`GET /api/category/groups`** — All PAC groups with summary totals (total receipts + total IE per group, aggregated from `schedule_a` and `ie_schedule_e`).

**`GET /api/category/pac/{committee_id}/industries`** — Industry breakdown for a PAC. Joins `schedule_a` against industry lookup tables using the matching strategy below. Returns list of industries with total amount, percentage, and donor count.

**`GET /api/category/pac/{committee_id}/donors`** — Top donors for a PAC. Query params: `industry` (filter), `sort` (amount|date|name), `order` (desc|asc), `limit` (default 50).

**`GET /api/category/pac/{committee_id}/candidates`** — IE spending by candidate from `ie_schedule_e`. Group by candidate_id, sum amounts, include party/state/office/support_oppose. Sortable by amount, state, name.

**`GET /api/category/pac/{committee_id}/candidates/{candidate_id}/industries`** — Attributed industry spending for a candidate. Uses PAC's industry breakdown percentages applied to the IE amount for that candidate.

#### 4. CORS

Add CORS middleware to allow cross-origin requests from the Issue Map frontend (use `*` for dev).

### Industry matching SQL pattern

Core join for attributing industries to `schedule_a` receipts:
```sql
COALESCE(
    NULLIF(o.industry, ''),   -- org match on contributor_name
    NULLIF(d.industry, ''),   -- donor match on contributor_name
    NULLIF(e.industry, ''),   -- employer match on contributor_employer
    'Unclassified'
) AS industry
FROM schedule_a sa
LEFT JOIN donor_industries d ON UPPER(sa.contributor_name) = d.name_upper
LEFT JOIN org_industries o ON UPPER(sa.contributor_name) = o.org_upper
LEFT JOIN org_industries e ON UPPER(sa.contributor_employer) = e.org_upper
```

Priority: org match > donor name match > employer match > Unclassified.

### Current data status (Feb 2026)

9 of 18 PACs have schedule_a data: DMFI (304), MAGA Inc. (47), UDP (43), Restoration PAC (36), AmericaPAC (25), Preserve America (11), Right for America (7), Protect Progress (4), Fairshake (3).

Ensure all 18 PAC IDs are in the `sa_target_committee_ids` config so new filings get parsed.

## TODO / Known Issues

### Recovering Failed Filings

The `ingestion_tasks` table tracks filing outcomes with substep detail. To find and retry failed filings:

```sql
-- Find failed filings with error details
SELECT filing_id, source_feed, status, failed_step, error_message, updated_at
FROM ingestion_tasks
WHERE status IN ('failed', 'claimed');

-- Reset failed filings for retry (clears error details)
UPDATE ingestion_tasks
SET status = 'claimed', failed_step = NULL, error_message = NULL, updated_at = NOW()
WHERE status = 'failed';
```

Or use `reset_failed_tasks()` from `app/repo.py` programmatically. Then run the job again.

### Future Improvements

- **Stream F3X header parsing** — Currently `download_fec_text` downloads the entire file even though F3X only needs the first ~100 lines. Streaming just the first ~50KB would eliminate the large file problem for F3X entirely. Schedule E still needs the full download since every line is a separate event.
