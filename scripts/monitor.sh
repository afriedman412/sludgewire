#!/bin/bash
# Unified monitoring for GitHub Actions, Cloud Run, and Cloud Scheduler

PROJECT="freeway2026"
REGION="us-central1"
SERVICE="fec-monitor"
SCHEDULER_JOB="fec-monitor-check"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}========== GitHub Actions (last 5 runs) ==========${NC}"
gh run list --limit 5 2>/dev/null || echo "  (gh CLI not authenticated or no runs)"

echo ""
echo -e "${BLUE}========== Cloud Run Logs (last 10) ==========${NC}"
gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=${SERVICE}" \
  --project="${PROJECT}" \
  --limit=10 \
  --format="table(timestamp,severity,textPayload)" \
  2>/dev/null || echo "  (error fetching Cloud Run logs)"

echo ""
echo -e "${BLUE}========== Cloud Scheduler (last 5 executions) ==========${NC}"
gcloud logging read "resource.type=cloud_scheduler_job AND resource.labels.job_id=${SCHEDULER_JOB}" \
  --project="${PROJECT}" \
  --limit=5 \
  --format="table(timestamp,jsonPayload.status,jsonPayload.targetType)" \
  2>/dev/null || echo "  (error fetching Scheduler logs)"

echo ""
echo -e "${YELLOW}Tip: Run with 'watch -n 30 ./scripts/monitor.sh' to auto-refresh every 30s${NC}"
