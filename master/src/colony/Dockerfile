FROM python:3.12-slim AS build
WORKDIR /build
COPY colony/requirements.txt ./requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/src:/app CK_ARTIFACT_ROOT=/artifacts CK_COLONY_DATA=/data
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home-dir /app app \
    && mkdir -p /artifacts /data && chown -R app:app /artifacts /data
COPY --from=build /wheels /wheels
COPY colony/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels
COPY agents /app/src/agents
COPY bridge /app/src/bridge
COPY colony /app/src/colony
COPY evolution /app/src/evolution
RUN chmod -R a=rX /app/src/agents /app/src/bridge /app/src/colony /app/src/evolution
USER app
EXPOSE 8500
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD curl -fsS http://127.0.0.1:8500/health || exit 1
CMD ["uvicorn", "colony.main:app", "--host", "0.0.0.0", "--port", "8500"]
