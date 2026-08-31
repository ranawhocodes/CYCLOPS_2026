FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PYTHONPATH=/app:/app/src
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
      libgomp1 curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
# CPU-only torch: the default wheel pulls ~2 GB of CUDA libraries that are dead
# weight on a demo laptop.
RUN pip install --index-url https://download.pytorch.org/whl/cpu torch torchvision \
 && pip install -r requirements.txt

COPY src /app/src
COPY api /app/api

EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
