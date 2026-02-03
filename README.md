# FEC Monitor

Real-time monitoring of FEC campaign finance filings with email alerts.

## Quick Start

```bash
# Install dependencies
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Set environment variables (see .env.example)
cp .env.example .env

# Create database tables
PYTHONPATH=. python scripts/debug_db.py

# Run the server
make guni
# or: gunicorn app.main:app --bind 0.0.0.0:5000 --workers 2 --worker-class uvicorn.workers.UvicornWorker
```

## API Documentation

Interactive API docs available at:
- **Swagger UI**: `/docs`
- **ReDoc**: `/redoc`

## Endpoints

### Dashboards (HTML)

| Endpoint | Description |
|----------|-------------|
| `GET /` | Redirect to `/dashboard/3x` |
| `GET /dashboard/3x` | F3X filings dashboard (today, ≥$50k receipts) |
| `GET /dashboard/e` | Schedule E events dashboard (today) |
| `GET /{year}/{month}/{day}/3x` | F3X filings for specific date (triggers backfill) |
| `GET /{year}/{month}/{day}/e` | Schedule E events for specific date (triggers backfill) |
| `GET /config` | Email recipient management (password protected) |

### JSON APIs

| Endpoint | Description |
|----------|-------------|
| `GET /api/3x/today` | F3X filings from today (JSON) |
| `GET /api/e/today` | Schedule E events from today (JSON) |
| `GET /api/3x` | Query F3X filings with filters |
| `GET /api/e` | Query Schedule E events with filters |
| `GET /api/backfill/status/{year}/{month}/{day}/{type}` | Check backfill job status |

### Cron / Automation

| Endpoint | Description |
|----------|-------------|
| `GET /api/cron/check-new` | **Check for new filings and send email alerts** |
| `GET /healthz` | Health check |

### Config (Protected)

| Endpoint | Description |
|----------|-------------|
| `GET /config` | View/manage email recipients |
| `POST /config/recipients` | Add email recipient |
| `POST /config/recipients/{id}/delete` | Remove email recipient |

## Cron Endpoint

The `/api/cron/check-new` endpoint:
1. Fetches the FEC RSS feeds for new F3X and Schedule E filings
2. Parses and stores any new filings in the database
3. Sends email alerts to configured recipients if new filings are found

**Call this endpoint on a schedule** (e.g., every 15 minutes via Cloud Scheduler):

```bash
curl https://your-service.run.app/api/cron/check-new
```

Response:
```json
{
  "f3x_new": 5,
  "ie_filings_new": 2,
  "ie_events_new": 12,
  "email_sent": true
}
```

Note: Backfill (historical data fetch) does NOT send emails - only the cron endpoint does.

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `POSTGRES_URL` | Yes | PostgreSQL connection string |
| `GOV_API_KEY` | No | FEC API key (uses DEMO_KEY if not set) |
| `RECEIPTS_THRESHOLD` | No | Min receipts to show (default: 50000) |
| `F3X_FEED` | No | F3X RSS feed URL |
| `IE_FEEDS` | No | Comma-separated IE RSS feed URLs |
| `GOOGLE_APP_PW` | No | Gmail app password for email alerts |
| `EMAIL_FROM` | No | Sender email address |
| `CONFIG_PASSWORD` | No | Password for /config page (user: admin) |

## Deployment to Cloud Run

### Prerequisites

1. GCP project with Cloud Run and Cloud SQL enabled
2. Service account with Cloud Run Admin and Cloud SQL Client roles
3. Artifact Registry repository created

### GitHub Secrets Required

| Secret | Description |
|--------|-------------|
| `GCP_PROJECT_ID` | Your GCP project ID |
| `GCP_SA_KEY` | Service account JSON key |
| `CLOUD_SQL_CONNECTION` | Cloud SQL connection name (project:region:instance) |
| `POSTGRES_URL` | PostgreSQL connection string |
| `GOV_API_KEY` | FEC API key |
| `GOOGLE_APP_PW` | Gmail app password |
| `EMAIL_FROM` | Sender email address |
| `CONFIG_PASSWORD` | Admin password for config page |

### Deploy

Push to `main` branch to trigger automatic deployment:

```bash
git add .
git commit -m "Deploy FEC Monitor"
git push origin main
```

The GitHub Actions workflow will:
1. Build the Docker image
2. Push to Artifact Registry
3. Deploy to Cloud Run

### Manual Deployment

```bash
# Build and push image
gcloud builds submit --tag gcr.io/PROJECT_ID/fec-monitor

# Deploy to Cloud Run
gcloud run deploy fec-monitor \
  --image gcr.io/PROJECT_ID/fec-monitor \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "POSTGRES_URL=..." \
  --add-cloudsql-instances PROJECT:REGION:INSTANCE
```

### Set Up Cron Job

Use Cloud Scheduler to call the cron endpoint:

```bash
gcloud scheduler jobs create http fec-monitor-check \
  --schedule "*/15 * * * *" \
  --uri "https://your-service.run.app/api/cron/check-new" \
  --http-method GET \
  --location us-central1
```

## Development

```bash
# Run locally
uvicorn app.main:app --reload --port 5000

# Test cron endpoint
curl http://localhost:5000/api/cron/check-new

# Test config page
curl -u admin:$CONFIG_PASSWORD http://localhost:5000/config
```
