from sqlalchemy import case, func, select

from app.database import Base, SessionLocal, engine
from app.models import LedgerEntry, Wallet


def reconcile() -> list[dict]:
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        ledger_balances = dict(db.execute(
            select(
                LedgerEntry.wallet_id,
                func.coalesce(func.sum(case((LedgerEntry.direction == "credit", LedgerEntry.amount_minor), else_=-LedgerEntry.amount_minor)), 0),
            ).group_by(LedgerEntry.wallet_id)
        ).all())
        mismatches = []
        for wallet in db.scalars(select(Wallet)):
            expected = int(ledger_balances.get(wallet.id, 0))
            if wallet.balance_minor != expected:
                mismatches.append({"wallet_id": wallet.id, "cached_balance_minor": wallet.balance_minor, "ledger_balance_minor": expected, "currency": wallet.currency})
        return mismatches


if __name__ == "__main__":
    problems = reconcile()
    if problems:
        for problem in problems:
            print(problem)
        raise SystemExit(1)
    print("Reconciliation passed: all wallet balances match the ledger.")
