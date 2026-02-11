# FEC Monitor

Real-time monitoring of FEC campaign finance filings with email alerts.

## Architecture

- **Cloud Run Service** (`fec-monitor`): Web UI, dashboards, config page
- **Cloud Run Job** (`fec-ingest-job`): Continuous ingestion, runs every 5 min via Cloud Scheduler
- **Cloud SQL** (`fec-db`): PostgreSQL database

The job processes today's filings from the RSS feed and sends email alerts for new high-value filings.

## Quick Start (Local)

```bash
# Install dependencies
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set environment variables (see .env.example)
cp .env.example .env

# Run the server
make guni
# or: gunicorn app.main:app --bind 0.0.0.0:5000 --workers 2 --worker-class uvicorn.workers.UvicornWorker
```

## Dashboards

| Endpoint | Description |
|----------|-------------|
| `GET /` | Redirect to `/dashboard/3x` |
| `GET /dashboard/3x` | F3X filings dashboard (today, ≥$50k receipts) |
| `GET /dashboard/e` | Schedule E events dashboard (today) |
| `GET /{year}/{month}/{day}/3x` | F3X filings for specific date |
| `GET /{year}/{month}/{day}/e` | Schedule E events for specific date |

## Config Page (`/config`)

Password-protected admin page for:

- **Email recipients**: Add/remove alert recipients
- **Email enabled**: Toggle email alerts on/off
- **Max filings per run**: Limit batch size to avoid OOM
- **Backfill**: Trigger historical data import for specific dates

### Backfill

To load historical data:
1. Go to `/config`
2. Select date and type (F3X or Schedule E)
3. Click "Start Backfill"
4. Monitor progress in the Active Jobs section

Backfill uses the FEC API (not RSS) to fetch filings for a specific date.

## JSON APIs

| Endpoint | Description |
|----------|-------------|
| `GET /api/3x/today` | F3X filings from today |
| `GET /api/e/today` | Schedule E events from today |
| `GET /api/backfill/status/{year}/{month}/{day}/{type}` | Check backfill job status |

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_URL` | Yes | PostgreSQL connection string |
| `CONFIG_PASSWORD` | Yes | Password for /config page (user: admin) |
| `GOV_API_KEY` | No | FEC API key (uses DEMO_KEY if not set) |
| `RECEIPTS_THRESHOLD` | No | Min receipts to show (default: 50000) |
| `GOOGLE_APP_PW` | No | Gmail app password for email alerts |
| `EMAIL_FROM` | No | Sender email address |

## Deployment

All resources are in the **freeway-2026** GCP project.

### Deploy Service
```bash
gcloud run deploy fec-monitor \
  --image=us-central1-docker.pkg.dev/freeway-2026/fec-monitor/fec-monitor:TAG \
  --region=us-central1 \
  --memory=2Gi
```

### Deploy Job
```bash
gcloud run jobs update fec-ingest-job \
  --image=us-central1-docker.pkg.dev/freeway-2026/fec-monitor/fec-monitor:TAG \
  --region=us-central1 \
  --memory=8Gi
```

### Cloud Scheduler
The job is triggered every 5 minutes by `fec-ingest-job-trigger`.

## Development

```bash
# Run locally
uvicorn app.main:app --reload --port 5000

# Run ingestion job locally
PYTHONPATH=. python -m scripts.ingest_job

# Connect to Cloud SQL via proxy
cloud-sql-proxy freeway2026:us-central1:fec-db --port=5433
```
