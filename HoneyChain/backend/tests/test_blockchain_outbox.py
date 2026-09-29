"""Phase 8 outbox tests: no fake ids, retries and logical-event idempotency."""

from __future__ import annotations

from app.core.config import get_settings
from app.models.blockchain import BlockchainStatus
from app.services.blockchain_client import BlockchainClientError
from app.services.blockchain_service import BlockchainService


class RecordingFabric:
    def __init__(self) -> None:
        self.transactions: list[dict] = []
        self.posts = 0

    def get_transactions(self):
        return list(self.transactions)

    def create_transaction(self, *, tx_type, batch_id, payload):
        self.posts += 1
        row = {
            "tx_id": f"fabric-{self.posts}",
            "tx_type": tx_type,
            "batch_id": batch_id,
            "payload": dict(payload),
            "timestamp": "2026-09-29T12:00:00Z",
        }
        self.transactions.append(row)
        return row


class FailingFabric:
    def get_transactions(self):
        return []

    def create_transaction(self, **_kwargs):
        raise BlockchainClientError("connection unavailable")


def _settings():
    return get_settings().model_copy(update={"BLOCKCHAIN_ENABLED": True, "ENVIRONMENT": "testing"})


def test_one_logical_event_posts_one_real_transaction_even_when_queued_twice(db):
    fabric = RecordingFabric()
    service = BlockchainService(db, settings=_settings(), client=fabric)
    one = service.queue_event(
        event_id="BATCH-HC-BATCH-2026-000001-CREATED",
        tx_type="BATCH_CREATED",
        batch_code="HC-BATCH-2026-000001",
        payload={"batch_id": "HC-BATCH-2026-000001", "quantity_kg": 25},
    )
    two = service.queue_event(
        event_id="BATCH-HC-BATCH-2026-000001-CREATED",
        tx_type="BATCH_CREATED",
        batch_code="HC-BATCH-2026-000001",
        payload={"batch_id": "HC-BATCH-2026-000001", "quantity_kg": 25},
    )
    assert one.id == two.id
    db.commit()

    service.submit(one.event_id)
    service.submit(one.event_id)

    refreshed = service.events.by_event_id(one.event_id)
    assert refreshed is not None
    assert refreshed.status == BlockchainStatus.CONFIRMED
    assert refreshed.tx_id == "fabric-1"
    assert fabric.posts == 1
    assert fabric.transactions[0]["payload"]["event_id"] == one.event_id


def test_failed_submission_keeps_a_retryable_outbox_event(db):
    service = BlockchainService(db, settings=_settings(), client=FailingFabric())
    event = service.queue_event(
        event_id="PROC-HC-PROC-2026-000001-COMPLETED",
        tx_type="PROCESSING_COMPLETED",
        batch_code="HC-BATCH-2026-000001",
        payload={"processing_id": "HC-PROC-2026-000001", "status": "COMPLETED"},
    )
    db.commit()

    service.submit(event.event_id)
    failed = service.events.by_event_id(event.event_id)
    assert failed is not None
    assert failed.status == BlockchainStatus.FAILED
    assert failed.tx_id is None
    assert failed.attempt_count == 1
    assert "connection unavailable" in (failed.last_error or "")
