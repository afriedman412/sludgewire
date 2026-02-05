gcloud run services describe fec-monitor \
    --region=us-central1 \
    --format="value(spec.template.spec.containers[0].image)"