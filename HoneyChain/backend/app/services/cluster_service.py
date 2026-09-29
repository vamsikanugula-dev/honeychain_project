"""KVIC cluster business logic, including code generation and membership."""

from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import DuplicateResourceError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.models.document_sequence import DocumentSequence, district_code
from app.models.kvic_cluster import KvicCluster
from app.models.user import User
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.hive_repository import HiveRepository
from app.repositories.cluster_repository import ClusterRepository
from app.schemas.cluster import ClusterCreate, ClusterUpdate
from app.services.audit_service import AuditService

logger = get_logger("service")

SEQUENCE_WIDTH = 3


def beekeeper_previous_id(cluster) -> uuid.UUID | None:
    """The cluster a beekeeper came from, or ``None`` when they had none.

    Passed to the hive move so that only the hives still following the beekeeper
    are touched: a hive placed in another cluster on purpose stays where it was
    put.
    """
    return cluster.id if cluster is not None else None


class ClusterService:
    """Create, read and maintain KVIC clusters and their membership."""

    def __init__(self, session: Session) -> None:
        self.session = session
        self.clusters = ClusterRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        # Hives follow their owner's membership, so this service needs to write
        # their cluster pointer as well as the beekeeper's.
        self.hives = HiveRepository(session)
        self.audit = AuditService(session)

    # ------------------------------------------------------------------ #
    # Codes
    # ------------------------------------------------------------------ #
    @staticmethod
    def build_cluster_code(district: str | None, sequence: str) -> str:
        return f"KVIC-{district_code(district)}-{sequence}"

    def generate_cluster_code(self, district: str | None) -> str:
        """Reserve the next cluster code for a district, e.g. ``KVIC-GNT-001``."""
        prefix = f"KVIC-{district_code(district)}"
        for attempt in range(5):
            sequence = DocumentSequence.next_value(
                self.session, f"CLUSTER:{prefix}", width=SEQUENCE_WIDTH + attempt
            )
            candidate = f"{prefix}-{sequence}"
            if not self.clusters.code_exists(candidate):
                return candidate
            logger.warning("Cluster code collision, retrying", extra={"candidate": candidate})
        raise ValidationError("Could not allocate a unique cluster code. Please retry.")

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def get(self, cluster_id: uuid.UUID) -> KvicCluster:
        cluster = self.clusters.get(cluster_id)
        if cluster is None:
            raise NotFoundError("KVIC cluster not found")
        return cluster

    def list_clusters(self, **filters) -> tuple[list[KvicCluster], int]:
        return self.clusters.search(**filters)

    def member_counts(self) -> dict[str, int]:
        """Member counts per cluster id (single aggregate query)."""
        return self.beekeepers.count_by_cluster()

    def list_members(self, cluster_id: uuid.UUID, *, page: int = 1, page_size: int = 20):
        # Confirms the cluster exists, so a bad id yields 404 rather than [].
        self.get(cluster_id)
        return self.beekeepers.list_by_cluster(cluster_id, page=page, page_size=page_size)

    def filter_options(self) -> dict[str, list[str]]:
        return {"districts": self.clusters.distinct_districts()}

    # ------------------------------------------------------------------ #
    # Writes
    # ------------------------------------------------------------------ #
    def create_cluster(self, payload: ClusterCreate, *, actor: User) -> KvicCluster:
        """Create a cluster, generating the code when one was not supplied."""
        cluster_code = payload.cluster_code or self.generate_cluster_code(payload.district)

        if self.clusters.code_exists(cluster_code):
            raise DuplicateResourceError(
                f"Cluster code {cluster_code} is already in use",
                details={"field": "cluster_code"},
            )

        cluster = self.clusters.create(
            cluster_code=cluster_code,
            cluster_name=payload.cluster_name,
            district=payload.district,
            state=payload.state,
            description=payload.description,
            coordinator_name=payload.coordinator_name,
            coordinator_phone=payload.coordinator_phone,
            is_active=True,
        )

        self.audit.cluster_created(cluster, actor=actor)
        self.clusters.commit()

        logger.info(
            "Cluster created",
            extra={"cluster_code": cluster.cluster_code, "district": cluster.district},
        )
        return cluster

    def update_cluster(
        self, cluster_id: uuid.UUID, payload: ClusterUpdate, *, actor: User
    ) -> KvicCluster:
        cluster = self.get(cluster_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return cluster

        updated = self.clusters.update(cluster, **changes)
        self.audit.cluster_updated(updated, actor=actor, changed_fields=sorted(changes))
        self.clusters.commit()
        return updated

    def set_status(
        self, cluster_id: uuid.UUID, *, is_active: bool, reason: str | None, actor: User
    ) -> KvicCluster:
        """Activate or deactivate a cluster.

        Deactivating does not unassign members — their beekeeper records remain
        historically accurate (they *were* in that cluster) and the UI marks the
        cluster as inactive. Reassigning is a deliberate, audited action.
        """
        cluster = self.get(cluster_id)

        if cluster.is_active == is_active:
            raise ValidationError(
                f"This cluster is already {'active' if is_active else 'inactive'}",
                details={"field": "is_active"},
            )

        updated = self.clusters.update(cluster, is_active=is_active)
        self.audit.cluster_status_changed(updated, actor=actor, is_active=is_active)
        if reason:
            self.audit.record(
                "CLUSTER_STATUS_CHANGED",
                actor=actor,
                entity_type="kvic_cluster",
                entity_id=cluster.id,
                metadata={"reason": reason},
                description=f"Reason: {reason}",
            )
        self.clusters.commit()
        return updated

    def assign_beekeeper(
        self, cluster_id: uuid.UUID, beekeeper_id: uuid.UUID, *, actor: User
    ) -> tuple[KvicCluster, object]:
        """Add a beekeeper to a cluster (``POST /clusters/{id}/beekeepers``).

        Membership is the *only* way a beekeeper becomes visible to a cluster, so
        this is a privileged action (``CLUSTER_MANAGE``) and it is audited twice
        over: once for the beekeeper, once as a relationship summary naming the
        hives that followed them.
        """
        cluster = self.get(cluster_id)
        if not cluster.is_active:
            raise ValidationError(
                "This cluster is inactive and cannot accept new members",
                details={"field": "cluster_id"},
            )

        beekeeper = self.beekeepers.get(beekeeper_id)
        if beekeeper is None:
            raise NotFoundError("Beekeeper not found")

        if beekeeper.kvic_cluster_id == cluster.id:
            raise ValidationError(
                "This beekeeper is already a member of the cluster",
                details={"field": "beekeeper_id"},
            )

        previous = self.clusters.get(beekeeper.kvic_cluster_id) if beekeeper.kvic_cluster_id else None
        updated = self.beekeepers.assign_cluster(beekeeper, cluster.id)
        moved = self.hives.set_cluster_for_beekeeper(
            beekeeper.id, cluster.id, previous_cluster_id=beekeeper_previous_id(previous)
        )
        self.audit.cluster_member_assigned(updated, actor=actor, cluster=cluster)
        self.audit.cluster_relationship_updated(
            updated, actor=actor, previous_cluster=previous, cluster=cluster, hives_followed=moved
        )
        self.clusters.commit()
        return cluster, updated

    def remove_beekeeper(
        self, cluster_id: uuid.UUID, beekeeper_id: uuid.UUID, *, actor: User
    ) -> tuple[KvicCluster, object]:
        """Clear a beekeeper's membership, detaching their hives from the view.

        Nothing is deleted: the hives keep their readings, analyses and audit
        trail, and appear in the administrative worklist as hives without a
        cluster until they are placed again.
        """
        cluster = self.get(cluster_id)
        beekeeper = self.beekeepers.get(beekeeper_id)
        if beekeeper is None:
            raise NotFoundError("Beekeeper not found")

        if beekeeper.kvic_cluster_id != cluster.id:
            raise ValidationError(
                "This beekeeper is not a member of the cluster",
                details={"field": "beekeeper_id"},
            )

        updated = self.beekeepers.assign_cluster(beekeeper, None)
        detached = self.hives.set_cluster_for_beekeeper(
            beekeeper.id, None, previous_cluster_id=cluster.id
        )
        self.audit.cluster_member_assigned(updated, actor=actor, cluster=None)
        self.audit.cluster_relationship_updated(
            updated,
            actor=actor,
            previous_cluster=cluster,
            cluster=None,
            hives_followed=[],
            hives_detached=detached,
        )
        self.clusters.commit()
        return cluster, updated

    def summary(self) -> dict:
        """Database-backed cluster counts (no estimates)."""
        all_clusters, total = self.list_clusters(page=1, page_size=1)
        active = self.clusters.count(is_active=True)
        inactive = self.clusters.count(is_active=False)
        member_counts = self.member_counts()
        return {
            "total": total,
            "active": active,
            "inactive": inactive,
            "members_assigned": sum(member_counts.values()),
            "unassigned_beekeepers": self.beekeepers.count()
            - sum(member_counts.values()),
        }
