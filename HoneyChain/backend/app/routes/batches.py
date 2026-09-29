"""Honey batch routes — read-only by construction.

There is no ``POST /batches``, no ``PATCH /batches/{id}`` and no status endpoint
in this file, and that is a deliberate design decision rather than an omission: a
batch exists because a beekeeper completed a harvest. Offering a manual status
endpoint would let a caller claim processing, laboratory testing, packaging or
distribution that this build cannot perform, so the capability is simply absent.

The sub-resources answer the traceability questions one at a time — where did
this honey come from (``/sources``), which harvest produced it (``/collection``),
what did the hives that produced it look like (``/sources/hives``) — so a screen
never has to guess a relationship from a summary string.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.permissions import Permission, require_any_permission
from app.models.enums import BatchStatus
from app.models.user import User
from app.schemas.batch import (
    BatchCollectionRef,
    BatchDetail,
    BatchHiveRef,
    BatchListItem,
    BatchSourceHive,
    BatchSummary,
    BatchTraceStage,
)
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.services.batch_service import BatchService
from app.services.blockchain_service import BlockchainService

router = APIRouter(prefix="/batches", tags=["Honey batches"])

READ_BATCHES = require_any_permission(Permission.BATCH_READ_SELF, Permission.BATCH_READ_ALL)


@router.get(
    "/summary",
    response_model=ApiResponse[BatchSummary],
    summary="Batch counters",
    description="Counts and batched totals for the caller's scope, counted from stored rows.",
)
def batch_summary(
    user: User = Depends(READ_BATCHES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(BatchService(session).summary(user))


@router.get(
    "",
    response_model=ApiResponse[list[BatchListItem]],
    summary="List honey batches",
    description=(
        "Paginated batch listing. A beekeeper sees the batches their own harvests produced; "
        "a cluster officer sees the batches of the beekeepers in the clusters they oversee; "
        "an administrator sees all."
    ),
)
def list_batches(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Batch code."),
    status_filter: BatchStatus | None = Query(default=None, alias="status"),
    cluster_id: uuid.UUID | None = Query(default=None),
    beekeeper_id: uuid.UUID | None = Query(default=None, description="Administrators only."),
    hive_id: uuid.UUID | None = Query(default=None, description="Batches fed by this hive."),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    user: User = Depends(READ_BATCHES),
    session: Session = Depends(db_session),
) -> dict:
    items, total = BatchService(session).list_batches(
        user,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status_filter,
        cluster_id=cluster_id,
        beekeeper_id=beekeeper_id,
        hive_id=hive_id,
        date_from=date_from,
        date_to=date_to,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/{batch_id}",
    response_model=ApiResponse[BatchDetail],
    summary="Get a batch",
    description=(
        "The batch with its source hives, the collection it came from, the AI context recorded "
        "at harvest time and the traceability timeline (Collection complete, later stages not "
        "started)."
    ),
)
def get_batch(
    batch_id: uuid.UUID,
    user: User = Depends(READ_BATCHES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(BatchService(session).get_batch(user, batch_id))


@router.get(
    "/{batch_id}/sources",
    response_model=ApiResponse[list[BatchSourceHive]],
    summary="Hives that produced this batch",
    description=(
        "One row per contributing hive with the quantity it gave and its share of the batch — "
        "never collapsed into a hive count."
    ),
)
def batch_sources(
    batch_id: uuid.UUID,
    user: User = Depends(READ_BATCHES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(BatchService(session).get_batch(user, batch_id).sources)


@router.get(
    "/{batch_id}/hives",
    response_model=ApiResponse[list[BatchHiveRef]],
    summary="Source hives of this batch",
    description=(
        "The hive records this batch traces back to, read from the hive registry through the "
        "collection. Status shown is the hive's status today, which is stated explicitly "
        "because it may differ from the day the honey was taken."
    ),
)
def batch_hives(
    batch_id: uuid.UUID,
    user: User = Depends(READ_BATCHES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(BatchService(session).source_hives(user, batch_id))


@router.get(
    "/{batch_id}/collection",
    response_model=ApiResponse[BatchCollectionRef],
    summary="The collection this batch came from",
    description="The harvest record behind the batch: its code, date, quantity, unit and status.",
)
def batch_collection(
    batch_id: uuid.UUID,
    user: User = Depends(READ_BATCHES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(BatchService(session).get_batch(user, batch_id).collection)


@router.get(
    "/{batch_id}/traceability",
    response_model=ApiResponse[dict],
    summary="Unified HoneyChain and blockchain traceability for one batch",
)
def batch_traceability(
    batch_id: uuid.UUID,
    user: User = Depends(READ_BATCHES),
    session: Session = Depends(db_session),
) -> dict:
    batch = BatchService(session).get_batch(user, batch_id)
    from app.repositories.distribution_repository import DistributionRepository
    from app.repositories.packaging_repository import PackageRepository

    transactions = BlockchainService(session).batch_transactions(batch.batch_code)
    packages = PackageRepository(session).for_batch(batch_id)
    shipments = DistributionRepository(session).for_batch(batch_id)
    return ok(
        {
            "batch": batch.model_dump(mode="json"),
            "collection": batch.collection.model_dump(mode="json"),
            "processing": batch.processing.model_dump(mode="json") if batch.processing else None,
            "laboratory": batch.laboratory.model_dump(mode="json") if batch.laboratory else None,
            "packaging": batch.packaging.model_dump(mode="json") if batch.packaging else None,
            "packages": [
                {"id": str(item.id), "package_id": item.package_code, "status": str(item.status), "size": str(item.package_size), "unit": str(item.unit)}
                for item in packages
            ],
            "distribution": [
                {"id": str(item.id), "distribution_id": item.distribution_code, "status": str(item.status), "destination": item.destination, "delivered_at": item.delivered_at, "received_at": item.received_at}
                for item in shipments
            ],
            "blockchain": {
                "transactions": transactions,
                "synchronized": bool(transactions)
                and all(row.get("blockchain_status") == "CONFIRMED" for row in transactions),
            },
            "timeline": batch.timeline,
        }
    )


@router.get(
    "/{batch_id}/timeline",
    response_model=ApiResponse[list[BatchTraceStage]],
    summary="Traceability timeline",
    description=(
        "Stages of the supply chain with only the truth marked as reached: Collection is "
        "COMPLETED because the harvest is stored; processing, laboratory, packaging, "
        "distribution and completion are NOT STARTED."
    ),
)
def batch_timeline(
    batch_id: uuid.UUID,
    user: User = Depends(READ_BATCHES),
    session: Session = Depends(db_session),
) -> dict:
    return ok(BatchService(session).get_batch(user, batch_id).timeline)


__all__ = ["router"]
