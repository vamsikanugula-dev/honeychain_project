"""Data access for the persistent blockchain outbox and package QR resolvers."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from app.models.blockchain import BlockchainStatus, BlockchainTransaction, PackageQrCode
from app.repositories.base import BaseRepository


class BlockchainTransactionRepository(BaseRepository[BlockchainTransaction]):
    model = BlockchainTransaction

    def by_event_id(self, event_id: str) -> BlockchainTransaction | None:
        return self.get_by(event_id=event_id)

    def by_tx_id(self, tx_id: str) -> BlockchainTransaction | None:
        return self.get_by(tx_id=tx_id)

    def for_batch(self, batch_code: str) -> list[BlockchainTransaction]:
        statement = (
            select(BlockchainTransaction)
            .where(BlockchainTransaction.batch_code == batch_code)
            .order_by(BlockchainTransaction.created_at.asc())
        )
        return list(self.session.execute(statement).scalars().all())

    def search(
        self,
        *,
        batch_codes: list[str] | None = None,
        search: str | None = None,
        tx_type: str | None = None,
        status: str | None = None,
        limit: int = 500,
    ) -> list[BlockchainTransaction]:
        statement = select(BlockchainTransaction).order_by(BlockchainTransaction.created_at.desc())
        if batch_codes is not None:
            if not batch_codes:
                return []
            statement = statement.where(BlockchainTransaction.batch_code.in_(batch_codes))
        if search:
            term = f"%{search.strip().lower()}%"
            statement = statement.where(
                func.lower(BlockchainTransaction.event_id).like(term)
                | func.lower(BlockchainTransaction.batch_code).like(term)
                | func.lower(func.coalesce(BlockchainTransaction.tx_id, "")).like(term)
            )
        if tx_type:
            statement = statement.where(BlockchainTransaction.tx_type == tx_type)
        if status:
            statement = statement.where(BlockchainTransaction.status == status)
        return list(self.session.execute(statement.limit(limit)).scalars().all())

    def retryable(self, *, limit: int = 100) -> list[BlockchainTransaction]:
        # A process can stop between persisting SUBMITTED and receiving Fabric's
        # response. It must be reconciled on a later worker run rather than left
        # indefinitely outside the retry queue.
        statement = (
            select(BlockchainTransaction)
            .where(
                BlockchainTransaction.status.in_(
                    [BlockchainStatus.PENDING, BlockchainStatus.SUBMITTED, BlockchainStatus.FAILED]
                )
            )
            .order_by(BlockchainTransaction.created_at.asc())
            .limit(limit)
        )
        return list(self.session.execute(statement).scalars().all())

    def health(self) -> dict:
        rows = self.session.execute(
            select(BlockchainTransaction.status, func.count(), func.max(BlockchainTransaction.confirmed_at)).group_by(
                BlockchainTransaction.status
            )
        ).all()
        by_status = {status: int(count) for status, count, _latest in rows}
        last_success = max((latest for _status, _count, latest in rows if latest is not None), default=None)
        return {
            "pending": by_status.get(BlockchainStatus.PENDING, 0),
            "failed": by_status.get(BlockchainStatus.FAILED, 0),
            "confirmed": by_status.get(BlockchainStatus.CONFIRMED, 0),
            "last_successful_transaction_at": last_success,
        }


class PackageQrCodeRepository(BaseRepository[PackageQrCode]):
    model = PackageQrCode

    def for_package(self, package_id: uuid.UUID) -> PackageQrCode | None:
        return self.get_by(package_id=package_id)

    def by_token(self, token: str) -> PackageQrCode | None:
        statement = (
            select(PackageQrCode)
            .options(
                joinedload(PackageQrCode.package),
            )
            .where(PackageQrCode.public_token == token)
        )
        return self.session.execute(statement).scalars().first()


__all__ = ["BlockchainTransactionRepository", "PackageQrCodeRepository"]
