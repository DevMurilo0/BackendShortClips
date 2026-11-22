# Build template: pin this base to a reviewed digest before publishing the image.
# Vercel Sandbox boots linux/amd64 OCI images; ENTRYPOINT is deliberately absent.
FROM python:3.14-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    MKL_NUM_THREADS=2 TOKENIZERS_PARALLELISM=false HF_HOME=/opt/models/huggingface
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg tesseract-ocr fonts-dejavu-core ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY worker/requirements.lock /tmp/worker-requirements.txt
RUN python -m venv /opt/shortforge \
    && /opt/shortforge/bin/pip install --no-cache-dir -r /tmp/worker-requirements.txt \
    && rm /tmp/worker-requirements.txt
# Add pinned model assets here after measuring a cold worker. No snapshots of
# job files, Blob credentials, or user media. Code is transferred by the API.
WORKDIR /tmp
