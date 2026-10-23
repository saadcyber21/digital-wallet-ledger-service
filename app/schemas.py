from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class WalletCreate(BaseModel):
    owner_id: str = Field(min_length=1, max_length=120)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @field_validator("owner_id")
    @classmethod
    def trim_owner(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("owner_id must not be blank")
        return value


class WalletOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    owner_id: str
    currency: str
    balance_minor: int
    created_at: datetime


class TransferCreate(BaseModel):
    source_wallet_id: str = Field(min_length=1, max_length=36)
    destination_wallet_id: str = Field(min_length=1, max_length=36)
    amount_minor: int = Field(gt=0, le=9_000_000_000_000_000)
    currency: str = Field(min_length=3, max_length=3, pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def distinct_wallets(self):
        if self.source_wallet_id == self.destination_wallet_id:
            raise ValueError("source and destination wallets must differ")
        return self


class TransferOut(BaseModel):
    id: str
    source_wallet_id: str
    destination_wallet_id: str
    amount_minor: int
    currency: str
    status: Literal["posted"] = "posted"


class RiskFlagOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    transaction_id: str
    reason: str
    score: int
    explanation: str | None
    created_at: datetime
