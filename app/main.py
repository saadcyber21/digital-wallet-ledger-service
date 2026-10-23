import hashlib
import json
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import LedgerEntry, LedgerTransaction, RiskFlag, Wallet
from app.risk import inspect_transfer
from app.schemas import RiskFlagOut, TransferCreate, TransferOut, WalletCreate, WalletOut

Base.metadata.create_all(bind=engine)
app = FastAPI(title="Digital Wallet and Ledger Service", version="0.1.0", description="Double-entry wallet transfers with idempotency and reconciliation support.")


@app.exception_handler(RequestValidationError)
async def validation_handler(request: Request, exc: RequestValidationError):
    details = [{"type": e.get("type"), "loc": e.get("loc"), "msg": e.get("msg")} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"error": {"code": "validation_error", "message": "Request validation failed", "details": jsonable_encoder(details)}})


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "request_error", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content={"error": {**detail, "details": detail.get("details", [])}})


def request_hash(payload: TransferCreate) -> str:
    value = json.dumps(payload.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def to_transfer(tx: LedgerTransaction, source: str, destination: str) -> dict:
    return TransferOut(id=tx.id, source_wallet_id=source, destination_wallet_id=destination, amount_minor=tx.amount_minor, currency=tx.currency).model_dump(mode="json")


@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


@app.post("/v1/wallets", response_model=WalletOut, status_code=201, tags=["wallets"])
def create_wallet(payload: WalletCreate, db: Session = Depends(get_db)):
    wallet = Wallet(id=str(uuid4()), owner_id=payload.owner_id, currency=payload.currency, balance_minor=0)
    db.add(wallet)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail={"code": "wallet_exists", "message": "A wallet for this owner and currency already exists"}) from exc
    db.refresh(wallet)
    return wallet


@app.get("/v1/wallets/{wallet_id}", response_model=WalletOut, tags=["wallets"])
def get_wallet(wallet_id: str, db: Session = Depends(get_db)):
    wallet = db.get(Wallet, wallet_id)
    if wallet is None:
        raise HTTPException(status_code=404, detail={"code": "wallet_not_found", "message": "Wallet not found"})
    return wallet


@app.post("/v1/transfers", response_model=TransferOut, status_code=201, tags=["transfers"])
def create_transfer(payload: TransferCreate, idempotency_key: str = Header(alias="Idempotency-Key", min_length=1, max_length=255), db: Session = Depends(get_db)):
    digest = request_hash(payload)
    previous = db.scalar(select(LedgerTransaction).where(LedgerTransaction.idempotency_key == idempotency_key))
    if previous is not None:
        if previous.request_hash != digest:
            raise HTTPException(status_code=409, detail={"code": "idempotency_conflict", "message": "Idempotency-Key was already used with a different request"})
        return to_transfer(previous, payload.source_wallet_id, payload.destination_wallet_id)

    # Always lock wallets in a stable order to reduce deadlocks on PostgreSQL.
    ids = sorted([payload.source_wallet_id, payload.destination_wallet_id])
    wallets = db.scalars(select(Wallet).where(Wallet.id.in_(ids)).order_by(Wallet.id).with_for_update()).all()
    by_id = {wallet.id: wallet for wallet in wallets}
    source = by_id.get(payload.source_wallet_id)
    destination = by_id.get(payload.destination_wallet_id)
    if source is None or destination is None:
        raise HTTPException(status_code=404, detail={"code": "wallet_not_found", "message": "Source or destination wallet not found"})
    if source.currency != payload.currency or destination.currency != payload.currency:
        raise HTTPException(status_code=422, detail={"code": "currency_mismatch", "message": "Transfer currency must match both wallets"})
    if source.balance_minor < payload.amount_minor:
        raise HTTPException(status_code=409, detail={"code": "insufficient_funds", "message": "Source wallet has insufficient funds"})

    tx = LedgerTransaction(id=str(uuid4()), idempotency_key=idempotency_key, request_hash=digest, currency=payload.currency, amount_minor=payload.amount_minor)
    source.balance_minor -= payload.amount_minor
    destination.balance_minor += payload.amount_minor
    db.add(tx)
    db.flush()
    db.add_all([
        LedgerEntry(transaction_id=tx.id, wallet_id=source.id, amount_minor=payload.amount_minor, direction="debit"),
        LedgerEntry(transaction_id=tx.id, wallet_id=destination.id, amount_minor=payload.amount_minor, direction="credit"),
    ])
    risk_flag = inspect_transfer(payload.amount_minor, payload.currency, tx.id)
    if risk_flag:
        db.add(risk_flag)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        previous = db.scalar(select(LedgerTransaction).where(LedgerTransaction.idempotency_key == idempotency_key))
        if previous is not None and previous.request_hash == digest:
            return to_transfer(previous, payload.source_wallet_id, payload.destination_wallet_id)
        raise HTTPException(status_code=409, detail={"code": "idempotency_conflict", "message": "Conflicting transfer request"}) from exc
    return to_transfer(tx, source.id, destination.id)


@app.get("/v1/transfers/{transaction_id}/risk-flags", response_model=list[RiskFlagOut], tags=["risk"])
def get_risk_flags(transaction_id: str, db: Session = Depends(get_db)):
    tx = db.get(LedgerTransaction, transaction_id)
    if tx is None:
        raise HTTPException(status_code=404, detail={"code": "transaction_not_found", "message": "Transaction not found"})
    return list(db.scalars(select(RiskFlag).where(RiskFlag.transaction_id == transaction_id)))
