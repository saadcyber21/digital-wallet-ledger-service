from fastapi.testclient import TestClient

from app.database import Base, SessionLocal, engine
from app.main import app
from app.models import LedgerEntry, LedgerTransaction, Wallet as WalletModel
from app.reconcile import reconcile

client = TestClient(app)


def setup_function():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)


def wallet(owner: str) -> str:
    response = client.post("/v1/wallets", json={"owner_id": owner, "currency": "USD"})
    assert response.status_code == 201
    return response.json()["id"]


def test_wallet_create_and_duplicate():
    assert client.post("/v1/wallets", json={"owner_id": "alice", "currency": "USD"}).status_code == 201
    duplicate = client.post("/v1/wallets", json={"owner_id": "alice", "currency": "USD"})
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "wallet_exists"


def test_transfer_requires_funds_and_is_balanced():
    source, destination = wallet("alice"), wallet("bob")
    response = client.post("/v1/transfers", headers={"Idempotency-Key": "funds-001"}, json={"source_wallet_id": source, "destination_wallet_id": destination, "amount_minor": 100, "currency": "USD"})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "insufficient_funds"


def test_transfer_is_idempotent_and_reconciles():
    source, destination = wallet("carol"), wallet("dave")
    # Seed funds as a posted ledger transaction so that all balances remain ledger-backed.
    with SessionLocal() as db:
        tx = LedgerTransaction(id="seed-tx", idempotency_key="seed-001", request_hash="seed", currency="USD", amount_minor=500)
        db.add(tx)
        db.flush()
        db.add_all([LedgerEntry(transaction_id=tx.id, wallet_id=source, amount_minor=500, direction="credit"), LedgerEntry(transaction_id=tx.id, wallet_id=destination, amount_minor=500, direction="debit")])
        db.get(WalletModel, source).balance_minor = 500
        db.get(WalletModel, destination).balance_minor = -500
        db.commit()
    payload = {"source_wallet_id": source, "destination_wallet_id": destination, "amount_minor": 100, "currency": "USD"}
    first = client.post("/v1/transfers", headers={"Idempotency-Key": "transfer-001"}, json=payload)
    second = client.post("/v1/transfers", headers={"Idempotency-Key": "transfer-001"}, json=payload)
    assert first.status_code == 201
    assert second.json()["id"] == first.json()["id"]
    assert client.get(f"/v1/wallets/{source}").json()["balance_minor"] == 400
    assert client.get(f"/v1/wallets/{destination}").json()["balance_minor"] == -400
    assert reconcile() == []


def test_idempotency_key_conflict():
    source, destination = wallet("erin"), wallet("frank")
    payload = {"source_wallet_id": source, "destination_wallet_id": destination, "amount_minor": 10, "currency": "USD"}
    first = client.post("/v1/transfers", headers={"Idempotency-Key": "conflict-001"}, json=payload)
    assert first.status_code == 409
    changed = {**payload, "amount_minor": 20}
    second = client.post("/v1/transfers", headers={"Idempotency-Key": "conflict-001"}, json=changed)
    assert second.status_code == 409


def test_validation_contract():
    response = client.post("/v1/wallets", json={"owner_id": "x", "currency": "usd"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
