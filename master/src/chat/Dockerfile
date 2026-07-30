FROM python:3.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY scraper.py reasoner.py tools.py main.py ./
EXPOSE 8300
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8300"]
