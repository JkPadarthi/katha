# Katha Archive image (0.2)
FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY seed.py .

# Seed the archive on first boot if empty (idempotent).
RUN mkdir -p /data/archive /data/index

EXPOSE 4901
# Seed then serve. Seeding is cheap and idempotent.
CMD ["sh", "-c", "python seed.py && uvicorn app.main:app --host 0.0.0.0 --port 4901"]
