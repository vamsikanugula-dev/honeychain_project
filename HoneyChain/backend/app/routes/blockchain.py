"""Blockchain ledger, synchronization controls and public QR traceability.

No endpoint here accepts a transaction type or a blockchain payload from the
browser.  The workflow services own event creation.  This router only reads the
real Fabric ledger / local synchronization state, retries durable outbox events,
and resolves an opaque package QR token.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.exceptions import NotFoundError
from app.core.permissions import Permission, require_permission
from app.models.user import User
from app.repositories.batch_repository import BatchRepository
from app.schemas.common import ApiResponse, ok
from app.services.blockchain_service import BlockchainService
from app.services.collection_service import CollectionService
from app.services.packaging_service import PackagingService

router = APIRouter(tags=["Blockchain traceability"])
LEDGER_READ = require_permission(Permission.BLOCKCHAIN_LEDGER_READ)
SYNC_RETRY = require_permission(Permission.BLOCKCHAIN_SYNC_RETRY)


def _scoped_batch_codes(user: User, session: Session) -> list[str] | None:
    """None means raw admin ledger; KVIC gets only real batches in its scope."""
    if str(user.role) == "ADMIN":
        return None
    collections = CollectionService(session)
    cluster_ids = collections.officer_cluster_ids(user)
    rows, _total = BatchRepository(session).search(page=1, page_size=1000, cluster_ids=cluster_ids)
    return [row.batch_code for row in rows]


@router.get(
    "/blockchain/transactions",
    response_model=ApiResponse[dict],
    summary="Read the real Fabric ledger with HoneyChain synchronization state",
)
def list_transactions(
    search: str | None = Query(default=None, max_length=160),
    tx_type: str | None = Query(default=None, max_length=80),
    status: Literal["PENDING", "SUBMITTED", "CONFIRMED", "FAILED"] | None = Query(default=None),
    user: User = Depends(LEDGER_READ),
    session: Session = Depends(db_session),
) -> dict:
    service = BlockchainService(session)
    rows, remote_error = service.ledger_transactions(
        batch_codes=_scoped_batch_codes(user, session), search=search, tx_type=tx_type, status=status
    )
    return ok({"transactions": rows, "remote_ledger_error": remote_error})


@router.get(
    "/blockchain/transactions/{tx_id}",
    response_model=ApiResponse[dict],
    summary="Open one ledger transaction",
)
def transaction_detail(
    tx_id: str,
    user: User = Depends(LEDGER_READ),
    session: Session = Depends(db_session),
) -> dict:
    rows, remote_error = BlockchainService(session).ledger_transactions(
        batch_codes=_scoped_batch_codes(user, session), search=tx_id
    )
    match = next((row for row in rows if row.get("tx_id") == tx_id or row.get("event_id") == tx_id), None)
    if match is None:
        raise NotFoundError("Blockchain transaction not found", details={"tx_id": tx_id})
    return ok({"transaction": match, "remote_ledger_error": remote_error})


@router.get(
    "/blockchain/batches/{batch_id}",
    response_model=ApiResponse[dict],
    summary="Blockchain history for one authorised batch",
)
def batch_ledger(
    batch_id: uuid.UUID,
    user: User = Depends(LEDGER_READ),
    session: Session = Depends(db_session),
) -> dict:
    from app.services.batch_service import BatchService

    batch = BatchService(session).get_batch(user, batch_id)
    rows = BlockchainService(session).batch_transactions(batch.batch_code)
    return ok({"batch_id": batch.batch_code, "transactions": rows})


@router.get(
    "/blockchain/health",
    response_model=ApiResponse[dict],
    summary="Actual Fabric connectivity and durable outbox health",
)
def blockchain_health(
    user: User = Depends(LEDGER_READ),
    session: Session = Depends(db_session),
) -> dict:
    return ok(BlockchainService(session).health())


@router.post(
    "/blockchain/retry",
    response_model=ApiResponse[dict],
    summary="Retry failed or pending blockchain synchronization",
)
def retry_blockchain(
    event_id: str | None = Query(default=None, max_length=180),
    limit: int = Query(default=100, ge=1, le=500),
    user: User = Depends(SYNC_RETRY),
    session: Session = Depends(db_session),
) -> dict:
    service = BlockchainService(session)
    if event_id:
        record = service.submit(event_id)
        if record is None:
            raise NotFoundError("Blockchain outbox event not found", details={"event_id": event_id})
        return ok({"retried": [service.serialize_event(record)]})
    remaining = service.retry_pending(limit=limit)
    return ok({"remaining_retryable": [service.serialize_event(record) for record in remaining]})


@router.post(
    "/packages/{package_id}/qr",
    response_model=ApiResponse[dict],
    summary="Generate the stable QR resolver for a traceable package",
)
def generate_package_qr(
    package_id: uuid.UUID,
    user: User = Depends(require_permission(Permission.PACKAGING_WRITE)),
    session: Session = Depends(db_session),
) -> dict:
    return ok(PackagingService(session).generate_package_qr(user, package_id))


# This route deliberately has no authentication dependency: an opaque QR token
# is what a consumer presents at the shelf. It exposes a curated response only.
@router.get(
    "/public/traceability/{public_token}",
    response_model=ApiResponse[dict],
    summary="Resolve a package QR token to customer-safe traceability",
)
def public_qr_traceability(public_token: str, session: Session = Depends(db_session)) -> dict:
    trace = BlockchainService(session).public_traceability(public_token)
    if trace is None:
        raise NotFoundError("QR traceability record not found", details={"resource": "qr"})
    return ok(trace)


__all__ = ["router"]
