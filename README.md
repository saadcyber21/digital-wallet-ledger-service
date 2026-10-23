# Digital Wallet and Ledger Service

A learning-oriented wallet backend built around an immutable, double-entry ledger. Transfers are atomic, use idempotency keys, and update wallet balances with database row locks on PostgreSQL. SQLite is supported for quick local tests, but it does **not** provide PostgreSQL's row-locking guarantees.

## Features

- Integer minor-unit amounts to avoid floating-point money errors.
- Every transfer creates balanced debit and credit ledger entries in one database transaction.
- PostgreSQL `SELECT ... FOR UPDATE` wallet locking and ACID transaction boundaries.
- Idempotent transfer retries with request-hash conflict detection.
- Nightly reconciliation command compares cached wallet balances with ledger-derived balances.
- Rules-based suspicious transaction flags, with optional LLM explanation adapter (no autonomous blocking).
- FastAPI OpenAPI docs and tests.

## Run locally

Requires Python 3.11+. Use PostgreSQL for concurrent transfer behavior; SQLite is provided for development and tests.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
copy .env.example .env  # Windows; on macOS/Linux use: cp .env.example .env
uvicorn app.main:app --reload
```

Docs: <http://127.0.0.1:8000/docs>

## API

Create a wallet:

```bash
curl -X POST http://127.0.0.1:8000/v1/wallets -H "Content-Type: application/json" -d '{"owner_id":"user-1","currency":"USD"}'
```

Transfer 1250 cents:

```bash
curl -X POST http://127.0.0.1:8000/v1/transfers -H "Content-Type: application/json" -H "Idempotency-Key: transfer-001" -d '{"source_wallet_id":"SOURCE_UUID","destination_wallet_id":"DEST_UUID","amount_minor":1250,"currency":"USD"}'
```

## Reconciliation

Run the command nightly via cron, a scheduler, or a managed job:

```bash
python -m app.reconcile
```

It exits nonzero when it finds a balance mismatch and reports the wallet IDs and expected/actual amounts. Wire it to alerts before relying on it operationally.

## Configuration

| Variable | Default | Purpose |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./wallet.db` | SQLAlchemy URL; use PostgreSQL in deployed environments |
| `OPENAI_API_KEY` | unset | Optional suspicious-activity explanation only |
| `OPENAI_MODEL` | `gpt-4o-mini` | Optional explanation model |

## Important limitations

This starter is **not** suitable for handling real funds. It has no authentication, authorization, payment processor integration, regulatory controls, or production observability. Balances are cached for efficient reads and checked against the immutable ledger by reconciliation. In production, use PostgreSQL, migrations, tenant isolation, audited administrative access, retention policies, and independent security/accounting review. The suspicious-activity layer flags for human review; it never makes a payment decision.
