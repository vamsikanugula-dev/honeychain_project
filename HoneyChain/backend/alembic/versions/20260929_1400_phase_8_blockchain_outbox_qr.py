"""Phase 8: durable blockchain outbox and package QR resolver.

Revision ID: phase8_blockchain_outbox_qr
Revises: af972db73f13
Create Date: 2026-09-29 14:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "phase8_blockchain_outbox_qr"
down_revision = "af972db73f13"
branch_labels = None
depends_on = None

UUID = postgresql.UUID(as_uuid=True)
JSON = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")


def upgrade() -> None:
    op.create_table(
        "blockchain_transactions",
        sa.Column("event_id", sa.String(length=180), nullable=False),
        sa.Column("tx_id", sa.String(length=255), nullable=True),
        sa.Column("tx_type", sa.String(length=80), nullable=False),
        sa.Column("batch_code", sa.String(length=80), nullable=False),
        sa.Column("collection_id", UUID, nullable=True),
        sa.Column("processing_id", UUID, nullable=True),
        sa.Column("lab_test_id", UUID, nullable=True),
        sa.Column("packaging_id", UUID, nullable=True),
        sa.Column("package_id", UUID, nullable=True),
        sa.Column("distribution_id", UUID, nullable=True),
        sa.Column("payload", JSON, nullable=False),
        sa.Column("payload_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("status IN ('PENDING', 'SUBMITTED', 'CONFIRMED', 'FAILED')", name="ck_blockchain_transactions_status"),
        sa.ForeignKeyConstraint(["collection_id"], ["honey_collections.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["processing_id"], ["honey_processing_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lab_test_id"], ["lab_tests.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["packaging_id"], ["packaging_records.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["distribution_id"], ["distributions.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id"),
        sa.UniqueConstraint("tx_id"),
    )
    op.create_index("ix_blockchain_transactions_event_id", "blockchain_transactions", ["event_id"])
    op.create_index("ix_blockchain_transactions_tx_id", "blockchain_transactions", ["tx_id"])
    op.create_index("ix_blockchain_transactions_batch_code", "blockchain_transactions", ["batch_code"])
    op.create_index("ix_blockchain_transactions_tx_type", "blockchain_transactions", ["tx_type"])
    op.create_index("ix_blockchain_transactions_batch_created", "blockchain_transactions", ["batch_code", "created_at"])
    op.create_index("ix_blockchain_transactions_status_created", "blockchain_transactions", ["status", "created_at"])

    op.create_table(
        "package_qr_codes",
        sa.Column("qr_code", sa.String(length=80), nullable=False),
        sa.Column("public_token", sa.String(length=96), nullable=False),
        sa.Column("package_id", UUID, nullable=False),
        sa.Column("generated_by_id", UUID, nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="ACTIVE"),
        sa.Column("id", UUID, nullable=False, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["package_id"], ["packages.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["generated_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("qr_code"),
        sa.UniqueConstraint("public_token"),
        sa.UniqueConstraint("package_id"),
    )
    op.create_index("ix_package_qr_codes_qr_code", "package_qr_codes", ["qr_code"])
    op.create_index("ix_package_qr_codes_public_token", "package_qr_codes", ["public_token"])


def downgrade() -> None:
    op.drop_index("ix_package_qr_codes_public_token", table_name="package_qr_codes")
    op.drop_index("ix_package_qr_codes_qr_code", table_name="package_qr_codes")
    op.drop_table("package_qr_codes")
    op.drop_index("ix_blockchain_transactions_status_created", table_name="blockchain_transactions")
    op.drop_index("ix_blockchain_transactions_batch_created", table_name="blockchain_transactions")
    op.drop_index("ix_blockchain_transactions_tx_type", table_name="blockchain_transactions")
    op.drop_index("ix_blockchain_transactions_batch_code", table_name="blockchain_transactions")
    op.drop_index("ix_blockchain_transactions_tx_id", table_name="blockchain_transactions")
    op.drop_index("ix_blockchain_transactions_event_id", table_name="blockchain_transactions")
    op.drop_table("blockchain_transactions")
