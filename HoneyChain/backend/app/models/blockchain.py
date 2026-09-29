"""Durable blockchain traceability outbox and QR resolver records.

Operational records remain in their own tables.  This module only records the
one logical ledger event that was created from an operational transition, and an
opaque QR resolver for a package.  The unique ``event_id`` is the idempotency
boundary: a browser retry or a retry worker can never turn the same HoneyChain
fact into a second Fabric transaction.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin, UUIDPrimaryKeyMixin, UUID_TYPE


class BlockchainStatus:
    """Values stored in ``blockchain_transactions.status``.

    These are intentionally strings instead of a PostgreSQL enum.  An outbox row
    must remain readable and retryable even while a deployment rolls forward.
    """

    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    FAILED = "FAILED"

    VALUES = (PENDING, SUBMITTED, CONFIRMED, FAILED)


class BlockchainTransaction(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One logical HoneyChain traceability event and its Fabric submission state."""

    __tablename__ = "blockchain_transactions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PENDING', 'SUBMITTED', 'CONFIRMED', 'FAILED')",
            name="ck_blockchain_transactions_status",
        ),
        Index("ix_blockchain_transactions_batch_created", "batch_code", "created_at"),
        Index("ix_blockchain_transactions_status_created", "status", "created_at"),
        Index("ix_blockchain_transactions_tx_id", "tx_id"),
    )

    # Deterministic logical id, e.g. ``PROC-HC-PROC-2026-000001-COMPLETED``.
    event_id: Mapped[str] = mapped_column(String(180), nullable=False, unique=True, index=True)
    tx_id: Mapped[str | None] = mapped_column(String(255), nullable=True, unique=True, index=True)
    tx_type: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    # Public HoneyChain batch code sent to Fabric, not a private UUID.
    batch_code: Mapped[str] = mapped_column(String(80), nullable=False, index=True)

    # Linked operational records. They make local scope checks and batch details
    # efficient without copying any operational entity into a ledger table.
    collection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("honey_collections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    processing_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("honey_processing_records.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lab_test_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("lab_tests.id", ondelete="SET NULL"), nullable=True, index=True
    )
    packaging_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("packaging_records.id", ondelete="SET NULL"), nullable=True, index=True
    )
    package_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("packages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    distribution_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("distributions.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # JSON contains only the small, allow-listed traceability payload sent to
    # Fabric. It never holds credentials, documents, telemetry or internal notes.
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    payload_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default=BlockchainStatus.PENDING, server_default=BlockchainStatus.PENDING
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    collection: Mapped["HoneyCollection | None"] = relationship()  # noqa: F821
    processing: Mapped["HoneyProcessing | None"] = relationship()  # noqa: F821
    lab_test: Mapped["LabTest | None"] = relationship()  # noqa: F821
    packaging: Mapped["PackagingRun | None"] = relationship()  # noqa: F821
    package: Mapped["HoneyPackage | None"] = relationship()  # noqa: F821
    distribution: Mapped["Distribution | None"] = relationship()  # noqa: F821


class PackageQrCode(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stable opaque QR resolver for one physical package.

    The QR itself contains only ``public_token`` (or a URL ending in it).  The
    customer page resolves that token server-side, then builds a deliberately
    redacted traceability response from the existing HoneyChain records.
    """

    __tablename__ = "package_qr_codes"
    __table_args__ = (Index("ix_package_qr_codes_token", "public_token", unique=True),)

    qr_code: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    public_token: Mapped[str] = mapped_column(String(96), nullable=False, unique=True, index=True)
    package_id: Mapped[uuid.UUID] = mapped_column(
        UUID_TYPE, ForeignKey("packages.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )
    generated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID_TYPE, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ACTIVE", server_default="ACTIVE")

    package: Mapped["HoneyPackage"] = relationship()  # noqa: F821
    generated_by: Mapped["User | None"] = relationship(foreign_keys=[generated_by_id])  # noqa: F821


__all__ = ["BlockchainStatus", "BlockchainTransaction", "PackageQrCode"]
