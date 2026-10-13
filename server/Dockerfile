# Katha image — builds the PWA client, then serves it (and the API) from
# one FastAPI process on one port. Build context is the REPO ROOT.

# --- stage 1: build the PWA client ---------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY desktop/package.json desktop/package-lock.json ./
RUN npm ci
COPY desktop/ ./
RUN npm run build

# --- stage 2: API + static PWA host --------------------------------------
FROM python:3.12-slim

WORKDIR /srv
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/app ./app
COPY server/seed.py .

# The built client, served at `/` by the API (same origin, one port).
COPY --from=web /web/dist ./web
ENV KATHA_WEB_DIR=/srv/web

RUN mkdir -p /data/archive /data/index

EXPOSE 4901
# Seed then serve. Seeding is cheap and idempotent.
CMD ["sh", "-c", "python seed.py && uvicorn app.main:app --host 0.0.0.0 --port 4901"]
