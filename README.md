# 1. Authenticate your local machine with your GCP account
gcloud auth login
gcloud config set project YOUR_PROJECT_ID

# 2. Deploy directly from your source directory
gcloud run deploy analysis-agent \
    --source . \
    --region us-central1 \
    --allow-unauthenticated
