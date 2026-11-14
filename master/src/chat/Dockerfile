FROM python:3.12-slim AS build
WORKDIR /build
COPY chat/requirements.txt ./requirements.txt
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/* \
    && groupadd --system app && useradd --system --gid app --home-dir /app app
COPY --from=build /wheels /wheels
COPY chat/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt && rm -rf /wheels
COPY chat/scraper.py chat/reasoner.py chat/tools.py chat/tools_advanced.py chat/circuit_breaker.py chat/bulkhead.py chat/priority_queue.py chat/__init__.py chat/main.py ./
COPY agents /app/agents
RUN chmod -R a=rX /app
USER app
EXPOSE 8300
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 CMD curl -fsS http://127.0.0.1:8300/health || exit 1
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8300"]
