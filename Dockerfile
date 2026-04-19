FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    cron tzdata \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz0b \
    libcairo2 libgdk-pixbuf-2.0-0 shared-mime-info \
    fonts-liberation fonts-dejavu \
    cups-client \
 && rm -rf /var/lib/apt/lists/*
ENV TZ=America/New_York

WORKDIR /app

COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .
COPY jina_clone/ ./jina_clone/

RUN pip install --no-cache-dir -e .

COPY crontab /etc/cron.d/jina-clone
RUN chmod 0644 /etc/cron.d/jina-clone && crontab /etc/cron.d/jina-clone

COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

ENV PORT=8080
EXPOSE ${PORT}

CMD ["./entrypoint.sh"]
