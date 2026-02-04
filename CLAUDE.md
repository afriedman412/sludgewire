# FEC Monitor

FastAPI application that monitors FEC filings (F3X and Schedule E) and provides dashboards and email alerts.

## Project Structure

```
app/
  api.py          # FastAPI routes (dashboards, API, config)
  backfill.py     # Historical data backfill from FEC API
  db.py           # Database engine setup
  schemas.py      # SQLModel schemas (FilingF3X, IEScheduleE, etc.)
  ingest_f3x.py   # F3X RSS feed ingestion
  ingest_ie.py    # Schedule E RSS feed ingestion
  fec_parse.py    # FEC file parsing utilities
  fec_lookup.py   # Committee name resolution
  email_service.py # Email alert sending
  settings.py     # Environment config
  auth.py         # Admin authentication
  templates/      # Jinja2 HTML templates
```

## Key Concepts

### Ingestion vs Backfill

- **Ingestion**: Polls RSS feeds for new filings as they're published. Used for current-day data.
- **Backfill**: Fetches all filings for a historical date from the FEC API. Memory-intensive.

### Current-Day Ingestion

Dashboard pages trigger rate-limited ingestion on load:
- 5-minute cooldown between runs (`INGESTION_COOLDOWN_MINUTES`)
- Runs in background thread
- Resets on deploy (in-memory state)

### Historical Backfill

Auto-backfill is **disabled** to prevent memory issues. To backfill historical dates:

```bash
# Admin-only endpoint
POST /config/backfill/{year}/{month}/{day}/{filing_type}

# filing_type: "3x" or "e"
# Example:
curl -X POST "https://app/config/backfill/2024/1/15/3x" -u "admin:password"

# Check status:
GET /api/backfill/status/2024/1/15/3x
```

## Memory Optimization

The app runs on Cloud Run with limited memory. Key optimizations:

1. **Explicit gc cleanup** - `del fec_text; del parsed; gc.collect()` after processing each filing
2. **No double-parsing** - `extract_schedule_e_best_effort()` accepts pre-parsed dict
3. **Truncated raw_line** - Schedule E events store only first 200 chars of raw line
4. **No auto-backfill** - Historical pages don't spawn background threads

## Deployment

```bash
# Build and deploy to Cloud Run
gcloud run deploy SERVICE_NAME \
  --source . \
  --memory 1Gi \
  --region REGION
```

### Cloud Run Settings

- **Memory**: 1-2 GiB recommended
- **CPU**: 1-2 recommended
- **CPU allocation**: "Always allocated" if using background threads
- **Concurrency**: 20-40 (with 2 gunicorn workers)

## Environment Variables

See `app/settings.py` for required env vars:
- `DATABASE_URL` - PostgreSQL connection string
- `ADMIN_PASSWORD` - Password for /config endpoints
- `GOV_API_KEY` - FEC API key (optional, falls back to DEMO_KEY)
- `SENDGRID_API_KEY` - For email alerts
- `RECEIPTS_THRESHOLD` - Minimum receipts to include F3X filings (default: 50000)

## Endpoints

### Dashboards (HTML)
- `GET /dashboard/3x` - Today's F3X filings
- `GET /dashboard/e` - Today's Schedule E events
- `GET /{year}/{month}/{day}/3x` - Historical F3X
- `GET /{year}/{month}/{day}/e` - Historical Schedule E

### API (JSON)
- `GET /api/3x/today` - Today's F3X filings
- `GET /api/e/today` - Today's Schedule E events
- `GET /api/3x` - Query F3X with filters
- `GET /api/e` - Query Schedule E with filters
- `GET /api/backfill/status/{year}/{month}/{day}/{type}` - Backfill job status

### Admin (password-protected)
- `GET /config` - Config page (email recipients)
- `POST /config/recipients` - Add email recipient
- `POST /config/recipients/{id}/delete` - Remove recipient
- `POST /config/backfill/{year}/{month}/{day}/{type}` - Trigger manual backfill

### System
- `GET /healthz` - Health check
- `GET /api/cron/check-new` - Cron endpoint for ingestion + email alerts
