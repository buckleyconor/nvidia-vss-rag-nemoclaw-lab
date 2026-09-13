# mock-wo/Dockerfile — operator dashboard backend + UI (operator-dashboard-spec
# ADR-V08, D6; spec/03 as amended).
#
# Stage 1 builds the React bundle with a pinned Node image from a committed
# lockfile. Stage 2 is the runtime and carries no Node: only the built
# static files, fonts included, are copied in — no CDN, no runtime fetch.
# Both base images are multi-arch (aarch64 dev machine, x86 lab VM).

FROM node:22.23.0-bookworm-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY ui/ ./
RUN npm run typecheck && npx vite build --outDir /ui/dist --emptyOutDir

FROM python:3.12-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MOCK_WO_DB_PATH=/data/mock-wo/work-orders.db \
    MOCK_WO_PACKS_DIR=/packs \
    MOCK_WO_UI_DIST=/app/app/ui_dist
# Both ports must answer: :8090 agent API, :8091 operator dashboard.
HEALTHCHECK --interval=10s --timeout=3s --retries=12 \
    CMD python -c "import urllib.request as u; [u.urlopen(f'http://127.0.0.1:{p}/health', timeout=2) for p in (8090, 8091)]"
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY app/ ./app/
COPY --from=ui /ui/dist ./app/ui_dist
EXPOSE 8090 8091
ENTRYPOINT ["python", "-m", "app.server"]
