"""KVIC cluster routes — the registry, its membership and the cluster *view*.

Two layers live here and they are deliberately different in kind:

* **the registry** — create, read, update, activate/deactivate and add/remove
  members. Every write is a privileged, audited action.
* **the view** — ``/clusters/{id}/summary``, ``/hives``, ``/devices``,
  ``/telemetry/latest`` and ``/ai``. These read the *same rows* the beekeepers
  see, reached through the relationships (cluster → beekeepers → hives →
  devices → readings, cluster → hives → analyses). Nothing is copied, and nothing
  is cached: a hive a beekeeper registers appears here because it was stored with
  the cluster link its owner's membership gave it.

Scope never comes from the request. A caller cannot widen what a cluster contains
by supplying a hive id; the hive set is resolved from the cluster itself.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.permissions import Permission, require_permission
from app.models.enums import BatchStatus, CollectionStatus, DeviceStatus, HiveStatus
from app.models.user import User
from app.schemas.beekeeper import BeekeeperListItem, to_beekeeper_list_item
from app.schemas.cluster import (
    ClusterCreate,
    ClusterDetail,
    ClusterPublic,
    ClusterStatusUpdate,
    ClusterUpdate,
    ClusterWithCounts,
    to_cluster_public,
)
from app.schemas.batch import BatchListItem
from app.schemas.cluster_analytics import (
    ClusterAiHiveRow,
    ClusterAiState,
    ClusterLatestTelemetry,
    ClusterOverview,
)
from app.schemas.common import ApiResponse, PaginationParams, ok, paginated
from app.schemas.collection import CollectionListItem
from app.schemas.hive import HiveListItem
from app.schemas.iot import DeviceListItem, ReadingSnapshot, to_reading_snapshot
from app.services.batch_service import BatchService
from app.services.cluster_analytics_service import ClusterAnalyticsService
from app.services.cluster_service import ClusterService
from app.services.collection_service import CollectionService

router = APIRouter(prefix="/clusters", tags=["Clusters"])

#: Reading a cluster as an operational view is staff oversight, not membership:
#: a beekeeper holds CLUSTER_READ (to see their own cluster's name) but never
#: this, so no beekeeper can list another apiary through a cluster.
READ_CLUSTER_VIEW = require_permission(Permission.CLUSTER_ANALYTICS_READ)


@router.get(
    "",
    response_model=ApiResponse[list[ClusterWithCounts]],
    summary="List clusters",
    description="Paginated cluster registry with member counts drawn from the database.",
)
def list_clusters(
    pagination: PaginationParams = Depends(),
    search: str | None = Query(default=None, max_length=120, description="Name, code or coordinator."),
    district: str | None = Query(default=None, max_length=80),
    state: str | None = Query(default=None, max_length=80),
    is_active: bool | None = Query(default=None),
    _: User = Depends(require_permission(Permission.CLUSTER_READ)),
    session: Session = Depends(db_session),
) -> dict:
    service = ClusterService(session)
    rows, total = service.list_clusters(
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        district=district,
        state=state,
        is_active=is_active,
    )
    counts = service.member_counts()
    return paginated(
        [to_cluster_public(row, counts.get(str(row.id), 0)) for row in rows],
        total_items=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post(
    "",
    response_model=ApiResponse[ClusterPublic],
    status_code=201,
    summary="Create a cluster",
    description=(
        "Creates a KVIC cluster. Omit ``cluster_code`` and the backend generates "
        "one (``KVIC-GNT-001``); supply it only when migrating an existing registry."
    ),
)
def create_cluster(
    payload: ClusterCreate,
    actor: User = Depends(require_permission(Permission.CLUSTER_MANAGE)),
    session: Session = Depends(db_session),
) -> dict:
    cluster = ClusterService(session).create_cluster(payload, actor=actor)
    return ok(to_cluster_public(cluster))


@router.get(
    "/{cluster_id}",
    response_model=ApiResponse[ClusterDetail],
    summary="Read a cluster",
    description="Cluster details plus its first page of members.",
)
def read_cluster(
    cluster_id: uuid.UUID,
    members_page_size: int = Query(default=10, ge=1, le=50),
    _: User = Depends(require_permission(Permission.CLUSTER_READ)),
    session: Session = Depends(db_session),
) -> dict:
    service = ClusterService(session)
    cluster = service.get(cluster_id)
    members, total = service.list_members(cluster_id, page=1, page_size=members_page_size)
    return ok(
        ClusterDetail(
            cluster=to_cluster_public(cluster, total),
            member_count=total,
            members=[to_beekeeper_list_item(member).model_dump(mode="json") for member in members],
        )
    )


@router.put(
    "/{cluster_id}",
    response_model=ApiResponse[ClusterPublic],
    summary="Update a cluster",
    description="Partial update of the editable fields. The cluster code is immutable.",
)
def update_cluster(
    cluster_id: uuid.UUID,
    payload: ClusterUpdate,
    actor: User = Depends(require_permission(Permission.CLUSTER_MANAGE)),
    session: Session = Depends(db_session),
) -> dict:
    cluster = ClusterService(session).update_cluster(cluster_id, payload, actor=actor)
    return ok(to_cluster_public(cluster))


@router.patch(
    "/{cluster_id}/status",
    response_model=ApiResponse[ClusterPublic],
    summary="Activate or deactivate a cluster",
    description=(
        "Inactive clusters keep their existing members (history stays accurate) "
        "but cannot accept new ones."
    ),
)
def update_cluster_status(
    cluster_id: uuid.UUID,
    payload: ClusterStatusUpdate,
    actor: User = Depends(require_permission(Permission.CLUSTER_MANAGE)),
    session: Session = Depends(db_session),
) -> dict:
    cluster = ClusterService(session).set_status(
        cluster_id, is_active=payload.is_active, reason=payload.reason, actor=actor
    )
    return ok(to_cluster_public(cluster))


@router.get(
    "/{cluster_id}/beekeepers",
    response_model=ApiResponse[list[BeekeeperListItem]],
    summary="List a cluster's beekeepers",
    description="Paginated membership list for the cluster detail screen.",
)
def list_cluster_beekeepers(
    cluster_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    _: User = Depends(require_permission(Permission.CLUSTER_READ)),
    session: Session = Depends(db_session),
) -> dict:
    rows, total = ClusterService(session).list_members(
        cluster_id, page=pagination.page, page_size=pagination.page_size
    )
    return paginated(
        [to_beekeeper_list_item(row) for row in rows],
        total_items=total,
        page=pagination.page,
        page_size=pagination.page_size,
    )


@router.post(
    "/{cluster_id}/beekeepers/{beekeeper_id}",
    response_model=ApiResponse[ClusterPublic],
    summary="Add a beekeeper to a cluster",
    description="Assigns an existing beekeeper record to this cluster.",
)
def add_cluster_member(
    cluster_id: uuid.UUID,
    beekeeper_id: uuid.UUID,
    actor: User = Depends(require_permission(Permission.CLUSTER_MANAGE)),
    session: Session = Depends(db_session),
) -> dict:
    cluster, _ = ClusterService(session).assign_beekeeper(cluster_id, beekeeper_id, actor=actor)
    return ok(to_cluster_public(cluster))


@router.delete(
    "/{cluster_id}/beekeepers/{beekeeper_id}",
    response_model=ApiResponse[ClusterPublic],
    summary="Remove a beekeeper from a cluster",
    description="Clears the membership; the beekeeper record itself is untouched.",
)
def remove_cluster_member(
    cluster_id: uuid.UUID,
    beekeeper_id: uuid.UUID,
    actor: User = Depends(require_permission(Permission.CLUSTER_MANAGE)),
    session: Session = Depends(db_session),
) -> dict:
    cluster, _ = ClusterService(session).remove_beekeeper(cluster_id, beekeeper_id, actor=actor)
    return ok(to_cluster_public(cluster))


# --------------------------------------------------------------------------- #
# The cluster view — same records, seen through the relationship
# --------------------------------------------------------------------------- #
@router.get(
    "/{cluster_id}/summary",
    response_model=ApiResponse[ClusterOverview],
    summary="Cluster dashboard counters",
    description=(
        "Every figure is counted from stored rows: the cluster's beekeepers by verification "
        "state, its hives by status, the devices on those hives by derived status, the "
        "telemetry they produced and the AI state of the hives. An empty cluster answers "
        "with zeros rather than being hidden."
    ),
)
def read_cluster_summary(
    cluster_id: uuid.UUID,
    _: User = Depends(READ_CLUSTER_VIEW),
    session: Session = Depends(db_session),
) -> dict:
    return ok(ClusterAnalyticsService(session).overview(cluster_id))


@router.get(
    "/{cluster_id}/hives",
    response_model=ApiResponse[list[HiveListItem]],
    summary="Hives belonging to a cluster's beekeepers",
    description=(
        "The same rows the beekeeper sees in My Hives, filtered by membership instead of by "
        "ownership: cluster, device count, primary device and latest reading."
    ),
)
def list_cluster_hives(
    cluster_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    status: HiveStatus | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    beekeeper_id: uuid.UUID | None = Query(
        default=None, description="Narrow the list to one member's hives."
    ),
    actor: User = Depends(READ_CLUSTER_VIEW),
    session: Session = Depends(db_session),
) -> dict:
    rows, total = ClusterAnalyticsService(session).list_hives(
        actor,
        cluster_id,
        page=pagination.page,
        page_size=pagination.page_size,
        status=status,
        search=search,
        beekeeper_id=beekeeper_id,
    )
    # ``rows`` are already HiveListItem payloads: the cluster list goes through
    # the same decorator as My Hives rather than through a second one.
    return paginated(
        rows, total_items=total, page=pagination.page, page_size=pagination.page_size
    )


@router.get(
    "/{cluster_id}/devices",
    response_model=ApiResponse[list[DeviceListItem]],
    summary="IoT devices on a cluster's hives",
    description=(
        "Devices reached through the hives they are paired with. Status is derived from the "
        "last packet, exactly as on the monitoring screens."
    ),
)
def list_cluster_devices(
    cluster_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    status: DeviceStatus | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    hive_id: uuid.UUID | None = Query(default=None),
    actor: User = Depends(READ_CLUSTER_VIEW),
    session: Session = Depends(db_session),
) -> dict:
    rows, total = ClusterAnalyticsService(session).list_devices(
        actor,
        cluster_id,
        page=pagination.page,
        page_size=pagination.page_size,
        status=status,
        search=search,
        hive_id=hive_id,
    )
    # Already DeviceListItem payloads, decorated by DeviceService.
    return paginated(
        rows, total_items=total, page=pagination.page, page_size=pagination.page_size
    )


@router.get(
    "/{cluster_id}/telemetry/latest",
    response_model=ApiResponse[ClusterLatestTelemetry],
    summary="Newest telemetry packet in a cluster",
    description=(
        "The most recent stored reading among the cluster's hives, printed with the "
        "device → hive → beekeeper path it travelled. `has_data: false` means nothing has "
        "been recorded yet — not that the answer is zero."
    ),
)
def read_cluster_latest_telemetry(
    cluster_id: uuid.UUID,
    _: User = Depends(READ_CLUSTER_VIEW),
    session: Session = Depends(db_session),
) -> dict:
    payload = ClusterAnalyticsService(session).latest_telemetry(cluster_id)
    reading = payload.get("reading")
    device = payload.get("device")
    hive = payload.get("hive")
    owner = payload.get("beekeeper")
    return ok(
        ClusterLatestTelemetry(
            has_data=payload["has_data"],
            hive_count=payload["hive_count"],
            hives_reporting=payload.get("hives_reporting", 0),
            timestamp=payload.get("timestamp"),
            hive_code=hive.hive_code if hive else None,
            device_id=device.device_id if device else None,
            device_status=str(device.status) if device else None,
            beekeeper_code=owner.beekeeper_code if owner else None,
            beekeeper_name=getattr(getattr(owner, "user", None), "full_name", None),
            reading=to_reading_snapshot(reading),
        )
    )


@router.get(
    "/{cluster_id}/ai",
    response_model=ApiResponse[ClusterAiState],
    summary="AI state of a cluster's hives",
    description=(
        "Aggregated from the stored analyses of this cluster's hives — the same rows the "
        "beekeeper sees, never a per-cluster copy. Hives that have never been analysed are "
        "returned with `analyzed: false` so they are visible rather than missing."
    ),
)
def read_cluster_ai_state(
    cluster_id: uuid.UUID,
    _: User = Depends(READ_CLUSTER_VIEW),
    session: Session = Depends(db_session),
) -> dict:
    payload = ClusterAnalyticsService(session).ai_state(cluster_id)
    return ok(
        ClusterAiState(
            summary=payload["summary"],
            hives=[ClusterAiHiveRow(**row) for row in payload["hives"]],
        )
    )


# --------------------------------------------------------------------------- #
# Phase 5 — harvest records in a cluster's view
# --------------------------------------------------------------------------- #
# These two endpoints exist so a KVIC officer sees a cluster's collections and
# batches on the *cluster screens they already use*, reading exactly the rows the
# beekeeper sees. They are not per-cluster copies: no collection is stored twice,
# and the payload is produced by the same service the beekeeper's own listing
# uses — only the scope differs.
#
# The officer check is not re-implemented here either. ``CollectionService`` owns
# the rule that an officer may read a cluster they could already open, so a
# cluster outside their scope returns an empty page rather than a leak.
@router.get(
    "/{cluster_id}/collections",
    response_model=ApiResponse[list[CollectionListItem]],
    summary="Harvests recorded in a cluster",
    description=(
        "The collections of the beekeepers in this cluster — the same records their "
        "beekeepers see, filtered to this cluster. Empty until a member records a harvest."
    ),
)
def list_cluster_collections(
    cluster_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    status: CollectionStatus | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    hive_id: uuid.UUID | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    actor: User = Depends(READ_CLUSTER_VIEW),
    session: Session = Depends(db_session),
) -> dict:
    items, total = CollectionService(session).list_collections(
        actor,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status,
        cluster_id=cluster_id,
        hive_id=hive_id,
        date_from=date_from,
        date_to=date_to,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)


@router.get(
    "/{cluster_id}/batches",
    response_model=ApiResponse[list[BatchListItem]],
    summary="Honey batches produced in a cluster",
    description=(
        "The batches produced by this cluster's beekeepers, reached through their harvests. "
        "Read-only: a batch is created by completing a collection and by nothing else."
    ),
)
def list_cluster_batches(
    cluster_id: uuid.UUID,
    pagination: PaginationParams = Depends(),
    status: BatchStatus | None = Query(default=None),
    search: str | None = Query(default=None, max_length=120),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    actor: User = Depends(READ_CLUSTER_VIEW),
    session: Session = Depends(db_session),
) -> dict:
    items, total = BatchService(session).list_batches(
        actor,
        page=pagination.page,
        page_size=pagination.page_size,
        search=search,
        status_filter=status,
        cluster_id=cluster_id,
        date_from=date_from,
        date_to=date_to,
    )
    return paginated(items, total_items=total, page=pagination.page, page_size=pagination.page_size)
