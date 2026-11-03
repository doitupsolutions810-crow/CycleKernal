# Local shim only. master/docker-compose.yml builds ../src/bridge (the canonical image).
# This Dockerfile cannot see that tree when the context is master/src/bridge.
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY main.py traits.py ns_fusion.py ./
EXPOSE 8090
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8090"]
