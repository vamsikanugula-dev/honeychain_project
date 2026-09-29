# Phase 8 — Fabric traceability integration

HoneyChain remains the operational source of truth. Phase 8 writes a narrow, durable outbox row inside the same database transaction as a real collection, batch, processing, laboratory, packaging, distribution, retailer-receipt, or QR transition. Only the backend calls the existing Fabric transaction service.

## Configure the backend

Set these **backend-only** values in the deployed environment (the examples are present in `backend/.env.example`):

```env
BLOCKCHAIN_BASE_URL=http://54.160.152.176:3001
BLOCKCHAIN_TIMEOUT_MS=10000
BLOCKCHAIN_RETRY_ATTEMPTS=3
BLOCKCHAIN_ENABLED=true
```

The browser must call HoneyChain API routes only. Do not expose `BLOCKCHAIN_BASE_URL` through Vite configuration, the public QR page, or any other frontend bundle.

Apply migrations before enabling operational traffic:

```bash
cd backend
alembic upgrade head
```

## Synchronization and recovery

Each outbox event has a deterministic `event_id` and is stored as one of:

- `PENDING` — committed locally but not yet submitted;
- `SUBMITTED` — a POST began and must be reconciled after an interruption;
- `CONFIRMED` — a real Fabric response/reference was stored;
- `FAILED` — the local fact remains valid and the event awaits reconciliation/retry.

Run the durable retry worker from a deployment scheduler/cron job, for example every minute:

```bash
cd backend
python -m app.scripts.blockchain_outbox_worker --limit 100
```

Before a retry POST, HoneyChain uses `GET /transactions` to look for its own `payload.event_id`. If a prior submission cannot be reconciled because the GET path is down, it is **not** blindly re-posted; the record remains `FAILED` until it can be safely reconciled. This prevents duplicate immutable entries after an ambiguous timeout.

Admin users can inspect the raw ledger and retry an individual local event at `/api/v1/blockchain/*`. KVIC officers receive only the records for real batches in their authorized cluster scope. No ledger API accepts a browser-supplied transaction type or payload.

## QR traceability

`POST /api/v1/packages/{package_id}/qr` creates one stable opaque resolver token for a real package. The returned URL is `/trace/{token}` on the configured HoneyChain frontend. The public endpoint resolves the token against HoneyChain package/batch data and returns only curated provenance, processing, quality, packaging, distribution and ledger status—never credentials, private notes, documents, or raw IoT/AI telemetry.
