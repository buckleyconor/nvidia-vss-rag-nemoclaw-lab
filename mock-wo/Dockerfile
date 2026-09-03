# mock-wo/Dockerfile — contract (03-build-decisions.md) + the HEALTHCHECK
# line (08 item 34: 05's TC-031 and the container-smoke step 5 require the
# raw `docker run` container to report Health; the parameters mirror the
# 03 compose healthcheck exactly). Pinned base + pinned deps; arch-neutral
# by design (multi-arch python base).
FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MOCK_WO_DB_PATH=/data/mock-wo/work-orders.db
HEALTHCHECK --interval=10s --timeout=3s --retries=12 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health')"
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
EXPOSE 8090
ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1"]
