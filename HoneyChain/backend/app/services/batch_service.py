"""Honey batch reads — and nothing else.

Phase 6 changed what a batch *reports* without giving the batch a writer. The
timeline is now assembled from the processing runs and laboratory tests that exist
against the batch, and the detail carries a processing summary and a laboratory
summary — each read from the run or the test that produced it. There is still no
``create``, ``update`` or ``set_status`` in this file: a batch moves because
processing or the laboratory moved it, through
:mod:`app.services.batch_lifecycle`.

A batch is created by completing a collection and by nothing else. There is no
``create`` here, no ``update`` and no ``set_status``: the absence *is* the
enforcement of requirement 13. A caller cannot post a batch, cannot rename one,
cannot move one to ``PACKAGED`` and cannot attach it to a different harvest,
because no code path exists to do any of those things.

What this service does is assemble the record: the batch, the collection it came
from, the hives that contributed (through the collection's contribution rows, not
a second copy) and the AI context beside the actual harvest. The scope rules are
delegated to :class:`~app.services.collection_service.CollectionService`, so a
beekeeper sees their own batches and a cluster officer sees the batches of the
beekeepers in the clusters they oversee — the same single rows, never a copy.
"""

from __future__ import annotations

import logging
from decimal import Decimal
import uuid
from datetime import date

from fastapi import status

from app.core.exceptions import AppError, NotFoundError
from app.models.enums import (
    BatchStage,
    BatchStatus,
    CollectionStatus,
    LabParameterStatus,
    LabResult,
    LabTestStatus,
    ProcessingStatus,
    UserRole,
)
from app.models.honey_batch import HoneyBatch
from app.models.user import User
from app.repositories.batch_repository import BatchRepository
from app.repositories.distribution_repository import DistributionRepository
from app.repositories.packaging_repository import (
    PackageRepository,
    PackagingRepository,
    approved_quantity_for_batch,
)
from app.repositories.beekeeper_repository import BeekeeperRepository
from app.repositories.hive_repository import HiveRepository
from app.schemas.batch import (
    BatchDetail,
    BatchDistributionRef,
    BatchPackagingRef,
    BatchHiveRef,
    BatchLabResultRef,
    BatchLabTestRef,
    BatchListItem,
    BatchProcessingRef,
    BatchSummary,
    BatchTraceStage,
)
from app.services import batch_lifecycle
from app.services.packaging_service import display_packaging_type
from app.services.names import person_name
from app.services.collection_service import CollectionService

logger = logging.getLogger(__name__)

#: Nothing is "reserved" any more: Phase 7 builds the packaging and distribution
#: stages, so every stop on the timeline is reported from rows that exist. The
#: constant stays as an empty tuple so a reader can see the question was asked —
#: and answered — rather than the code having forgotten it.
_LATER_STAGES: tuple[BatchStage, ...] = ()


def _enum_value(value) -> str | None:
    return None if value is None else str(getattr(value, "value", value))


def _label(hive) -> str:
    """A hive's status, spelled out. Kept for hive rows specifically."""
    status = getattr(hive, "status", None)
    return getattr(status, "label", None) or _enum_value(status) or "Unknown"


def _enum_label(value) -> str:
    """The plain-language label of any enum value that carries one.

    Distinct from :func:`_label` above, which reads a *hive's* status: passing a
    unit or a processing status through that one silently yields "Unknown",
    which is how a timeline ends up saying "12.9 Unknown" about a measurement in
    kilograms. The fallback here is the value itself, never a placeholder.
    """
    if value is None:
        return "—"
    return getattr(value, "label", None) or _enum_value(value) or "—"


#: The order the stages happen in. Used to say "processing is complete" only
#: because the batch has moved past it — the lifecycle moves a batch precisely
#: when a stage finishes, so this is a reading of records, not an assumption.
_BATCH_STATUS_ORDER: dict[str, int] = {
    "COLLECTED": 0,
    "PROCESSING": 1,
    "LAB_TESTING": 2,
    "APPROVED": 3,
    "REJECTED": 3,
    "PACKAGED": 4,
    "DISTRIBUTION": 5,
    "COMPLETED": 6,
}


class BatchService:
    """Read-only view of the batches that completed collections produced."""

    def __init__(self, session) -> None:  # noqa: ANN001 - Session from the dependency
        self.session = session
        self.batches = BatchRepository(session)
        self.beekeepers = BeekeeperRepository(session)
        self.hives = HiveRepository(session)
        # Scope and serialisation of the collection side live in one place, so a
        # batch is never described differently from the collection it came from.
        self.collections = CollectionService(session)
        # The downstream modules: a batch row reports how far its own packaging
        # runs and shipments have got, read from their tables rather than guessed
        # from the batch's status.
        self.packaging = PackagingRepository(session)
        self.packages = PackageRepository(session)
        self.distributions = DistributionRepository(session)

    # ------------------------------------------------------------------ #
    # Scope
    # ------------------------------------------------------------------ #
    def _scope_filters(self, user: User) -> dict:
        """Scope for a batch listing.

        A beekeeper and a cluster officer keep the Phase-5 scope exactly as it was.
        The operational roles — processor, laboratory technician — are not confined
        to an apiary: they act on whichever batch reaches their stage, so their read
        scope is the workflow. The rows are the same rows for everyone; only the
        filter changes.
        """
        return self.collections.workflow_scope_filters(user)

    def _assert_can_read(self, user: User, batch: HoneyBatch) -> None:
        if user.role == UserRole.BEEKEEPER:
            owner = self.collections.own_beekeeper(user)
            if batch.beekeeper_id != owner.id:
                raise NotFoundError(f"Batch {batch.id} not found", details={"resource": "batch"})
            return
        if user.role == UserRole.KVIC_OFFICER:
            cluster_ids = self.collections.officer_cluster_ids(user)
            if batch.cluster_id is None or batch.cluster_id not in cluster_ids:
                raise NotFoundError(
                    f"Batch {batch.id} not found",
                    details={"resource": "batch", "reason": "outside your clusters"},
                )
            return
        if user.role == UserRole.ADMIN or self.collections.is_workflow_role(user):
            return
        raise AppError("Not permitted", status_code=status.HTTP_403_FORBIDDEN, code="FORBIDDEN")

    # ------------------------------------------------------------------ #
    # Reads
    # ------------------------------------------------------------------ #
    def list_batches(
        self,
        user: User,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: BatchStatus | None = None,
        cluster_id: uuid.UUID | None = None,
        beekeeper_id: uuid.UUID | None = None,
        hive_id: uuid.UUID | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> tuple[list[BatchListItem], int]:
        scope = self._scope_filters(user)

        if beekeeper_id is not None and user.role == UserRole.ADMIN:
            scope["beekeeper_id"] = beekeeper_id
        if cluster_id is not None:
            if user.role == UserRole.KVIC_OFFICER:
                if cluster_id not in self.collections.officer_cluster_ids(user):
                    return [], 0
            scope["cluster_id"] = cluster_id

        rows, total = self.batches.search(
            page=page,
            page_size=page_size,
            search=search,
            status=status_filter,
            hive_id=hive_id,
            date_from=date_from,
            date_to=date_to,
            **scope,
        )
        # One pass of aggregates for the page, then one item per row — so the
        # downstream columns cost three queries per page, not three per batch.
        metrics = self._downstream_metrics([row.id for row in rows])
        return [self.to_list_item(row, metrics.get(row.id)) for row in rows], total

    def get_batch(self, user: User, batch_id: uuid.UUID) -> BatchDetail:
        batch = self.batches.get_with_relations(batch_id)
        if batch is None:
            raise NotFoundError(f"Batch {batch_id} not found", details={"resource": "batch"})
        self._assert_can_read(user, batch)
        return self.to_detail(batch)

    def get_by_collection(self, user: User, collection_id: uuid.UUID) -> BatchDetail:
        """The batch a collection produced, reached through the collection.

        Useful exactly once per harvest, and 404 for an open or cancelled
        collection — a batch exists only after completion.
        """
        collection = self.collections.get_collection(user, collection_id)
        batch = self.batches.get_by_collection(collection.id)
        if batch is None:
            raise NotFoundError(
                f"Collection {collection.collection_code} has no batch",
                details={
                    "resource": "batch",
                    "collection_code": collection.collection_code,
                    "status": collection.status.value,
                },
            )
        return self.get_batch(user, batch.id)

    def source_hives(self, user: User, batch_id: uuid.UUID) -> list[BatchHiveRef]:
        """The hive records behind a batch, reached through its collection.

        Read from the hive registry rather than copied onto the batch, so a batch
        can never claim a hive that the registry does not have. The status shown is
        the hive's *current* status and the payload says so — a hive that has since
        been retired still traces here, because its honey is still in the batch.
        """
        detail = self.get_batch(user, batch_id)
        refs: list[BatchHiveRef] = []
        for source in detail.sources:
            hive = self.hives.get(source.hive_id)
            refs.append(
                BatchHiveRef(
                    hive_id=source.hive_id,
                    hive_code=source.hive_code,
                    status=_enum_value(getattr(hive, "status", None)) or "UNKNOWN",
                    status_label=_label(hive),
                    colony_strength=_enum_value(getattr(hive, "colony_strength", None)),
                    village=source.village if hive is None else hive.village,
                    district=source.district if hive is None else hive.district,
                    beekeeper_code=source.beekeeper_code,
                    note="Current registry state of the hive, not a harvest-time snapshot.",
                )
            )
        return refs

    def summary(self, user: User) -> BatchSummary:
        scope = self._scope_filters(user)
        counts = self.batches.count_by_status(**scope)
        totals = self.batches.totals(**scope)
        # Open harvests that have no batch yet — the worklist a beekeeper sees as
        # "complete this harvest to create its batch". Counted, not estimated.
        _rows, awaiting = self.collections.collections.search(
            page=1,
            page_size=1,
            has_batch=False,
            statuses=list(CollectionStatus.open_statuses()),
            **scope,
        )
        return BatchSummary(
            total=sum(counts.values()),
            by_status=counts,
            collected=counts.get(BatchStatus.COLLECTED.value, 0),
            batched_totals={unit: float(value) for unit, value in totals.items()},
            awaiting_collection_completion=awaiting,
        )

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #
    #: Plain-language labels for the downstream columns a cluster table shows. The
    #: values come from the stages' own records; these are only the words.
    _DOWNSTREAM_LABELS = {
        "NOT_STARTED": "Not started",
        "PENDING": "Pending",
        "IN_PROGRESS": "In progress",
        "AWAITING_TEST": "Awaiting a sample",
        "COMPLETED": "Completed",
        "PARTIAL": "Partly packed",
        "APPROVED": "Approved",
        "REJECTED": "Rejected",
        "READY_FOR_DISPATCH": "Ready for dispatch",
        "DISPATCHED": "Dispatched",
        "IN_TRANSIT": "In transit",
        "DELIVERED": "Delivered",
        "CANCELLED": "Cancelled",
    }

    def _downstream_metrics(self, batch_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
        """How far each batch has travelled, from the stage records, in three queries.

        Deliberately batched: a page of twenty batches costs three grouped queries
        rather than sixty, and every value still comes from the table that owns it.
        """
        if not batch_ids:
            return {}
        packed = self.packaging.packaged_quantity_by_batch(batch_ids)
        packages = self.packages.counts_by_batch(batch_ids)
        shipments = self.distributions.summary_by_batch(batch_ids)
        return {
            batch_id: {
                "packaged_quantity": packed.get(batch_id, Decimal("0")),
                "package_count": packages.get(batch_id, 0),
                "shipment_count": (shipments.get(batch_id) or {}).get("shipments", 0),
                "delivered_count": (shipments.get(batch_id) or {}).get("delivered", 0),
                "latest_shipment_status": (shipments.get(batch_id) or {}).get("latest_status"),
            }
            for batch_id in batch_ids
        }

    def _downstream_statuses(
        self, batch: HoneyBatch, metrics: dict | None = None
    ) -> dict[str, str]:
        """The four stage statuses of one batch, read from where they really live.

        The batch's own status is the spine — the lifecycle only moves it when a
        stage actually happened — and the packaging figures refine it, because a
        batch can be packed in several runs and "partly packed" is not the same
        fact as "packed".
        """
        status = batch.status
        rank = _BATCH_STATUS_ORDER
        position = rank.get(str(status), 0)

        processing = "NOT_STARTED"
        if position >= rank["LAB_TESTING"]:
            processing = "COMPLETED"
        elif str(status) == BatchStatus.PROCESSING.value:
            processing = "IN_PROGRESS"
        elif str(status) == BatchStatus.COLLECTED.value:
            processing = "PENDING"

        laboratory = "NOT_STARTED"
        if str(status) in (BatchStatus.LAB_TESTING.value, BatchStatus.APPROVED.value,
                           BatchStatus.REJECTED.value):
            laboratory = "AWAITING_TEST"
        if position >= rank["LAB_TESTING"]:
            laboratory = "IN_PROGRESS"
        if str(status) == BatchStatus.APPROVED.value:
            laboratory = "APPROVED"
        elif str(status) == BatchStatus.REJECTED.value:
            laboratory = "REJECTED"
        elif position > rank["APPROVED"]:
            laboratory = "APPROVED"

        packaging_status = "NOT_STARTED"
        if position >= rank["PACKAGED"]:
            packaging_status = "COMPLETED"
        if metrics is not None:
            packed = Decimal(metrics.get("packaged_quantity") or 0)
            approved = approved_quantity_for_batch(self.session, batch.id)
            if packed > 0:
                packaging_status = "PARTIAL" if approved and packed < approved else "COMPLETED"

        distribution = "NOT_STARTED"
        if metrics is not None and metrics.get("shipment_count"):
            distribution = metrics.get("latest_shipment_status") or "READY_FOR_DISPATCH"
        elif str(status) == BatchStatus.DISTRIBUTION.value:
            distribution = "DISPATCHED"
        elif str(status) == BatchStatus.COMPLETED.value:
            distribution = "DELIVERED"

        values = {
            "processing_status": processing,
            "laboratory_status": laboratory,
            "packaging_status": packaging_status,
            "distribution_status": distribution,
        }
        labelled: dict[str, str] = {}
        for key, value in values.items():
            labelled[key] = value
            labelled[f"{key}_label"] = self._DOWNSTREAM_LABELS.get(
                value, value.replace("_", " ").title()
            )
        return labelled

    def to_list_item(self, batch: HoneyBatch, metrics: dict | None = None) -> BatchListItem:
        collection = batch.collection
        sources = self.collections.sources_of(collection) if collection is not None else []
        beekeeper = getattr(batch, "__dict__", {}).get("beekeeper") or self.beekeepers.get(
            batch.beekeeper_id
        )
        return BatchListItem(
            id=batch.id,
            batch_code=batch.batch_code,
            status=batch.status,
            status_label=batch.status.label,
            current_stage=batch.current_stage,
            current_stage_label=batch.current_stage.label,
            collection_id=batch.collection_id,
            collection_code=getattr(collection, "collection_code", None) or "",
            collection_date=batch.collection_date,
            quantity=batch.quantity,
            unit=batch.unit,
            unit_label=batch.unit.label,
            source_hive_count=batch.source_hive_count or len(sources),
            source_hive_codes=[row.hive_code for row in sources],
            beekeeper_id=batch.beekeeper_id,
            beekeeper_code=getattr(beekeeper, "beekeeper_code", None),
            beekeeper_name=self.collections.user_name(getattr(beekeeper, "user", None)),
            cluster_id=batch.cluster_id,
            cluster_code=getattr(batch.cluster, "cluster_code", None),
            cluster_name=getattr(batch.cluster, "cluster_name", None),
            ai_predicted_yield_kg=batch.ai_predicted_yield_kg,
            ai_prediction_hive_count=batch.ai_prediction_hive_count or 0,
            packaged_quantity=(metrics or {}).get("packaged_quantity", Decimal("0")),
            package_count=(metrics or {}).get("package_count", 0),
            **self._downstream_statuses(batch, metrics),
            created_at=batch.created_at,
        )

    def to_detail(self, batch: HoneyBatch) -> BatchDetail:
        base = self.to_list_item(batch)
        collection = batch.collection
        if collection is None:  # pragma: no cover - the foreign key makes this unreachable
            raise NotFoundError(
                f"The collection behind batch {batch.batch_code} was not found",
                details={"resource": "collection"},
            )
        processing_count, processing = self.processing_summary_for(batch)
        test_count, laboratory = self.laboratory_summary_for(batch)
        packaging_ref = self.packaging_summary_for(batch)
        distribution_ref = self.distribution_summary_for(batch)
        allowed_next = [
            str(status) for status in batch_lifecycle.allowed_transitions(batch.status)
        ]
        return BatchDetail(
            **base.model_dump(),
            collection=self.collections.collection_ref_for_batch(batch),
            sources=self.collections.source_hives_for_batch(batch),
            ai_context=self.collections.snapshot_for_batch(batch),
            timeline=self.timeline(batch),
            prediction_difference_kg=batch.prediction_difference_kg,
            processing_count=processing_count,
            processing=processing,
            test_count=test_count,
            laboratory=laboratory,
            allowed_next_statuses=allowed_next,
            updated_at=batch.updated_at,
            editable_fields=[],
            packaging=packaging_ref,
            distribution=distribution_ref,
            # The stages the batch can actually move to next. They are read from
            # the transition table, so this list and the enforcement can never
            # disagree.
            next_possible_stages=[
                batch_lifecycle.STATUS_LABEL[status]
                for status in batch_lifecycle.allowed_transitions(batch.status)
            ],
        )

    def packaging_summary_for(self, batch: HoneyBatch):
        """What packaging has recorded for this batch, counted rather than copied.

        ``approved_quantity`` is the measured output of the batch's completed
        processing run — the honey that exists and passed the laboratory. Nothing
        is converted and no figure is assumed: the numbers are the ones the
        processing and packaging records already store.
        """
        runs = sorted(
            list(getattr(batch, "packaging_records", []) or []),
            key=lambda row: (row.created_at, str(row.id)),
        )
        completed = [row for row in runs if str(row.status) == "COMPLETED"]
        open_run = next((row for row in runs if getattr(row.status, "is_open", False)), None)
        latest = completed[-1] if completed else None
        packages = [
            package
            for package in (getattr(batch, "packages", []) or [])
            if latest is not None and package.packaging_id == latest.id
        ]
        approved = Decimal("0")
        completed_runs = [
            run
            for run in (getattr(batch, "processing_records", []) or [])
            if str(run.status) == "COMPLETED" and run.output_quantity is not None
        ]
        if completed_runs:
            approved = completed_runs[-1].output_quantity
        packaged_total = sum(
            (run.packaged_quantity or Decimal("0") for run in completed), Decimal("0")
        )
        remaining = approved - packaged_total
        reference = latest or open_run
        # The unit of the work in hand: the run's own when there is one, otherwise
        # the batch's — honey is measured in the unit it was harvested in.
        run_unit = getattr(reference, "unit", None) or batch.unit
        return BatchPackagingRef(
            run_count=len(runs),
            completed_count=len(completed),
            open_run_id=getattr(open_run, "id", None),
            open_run_code=getattr(open_run, "packaging_code", None),
            latest_run_id=getattr(latest, "id", None),
            latest_run_code=getattr(latest, "packaging_code", None),
            latest_status=str(latest.status) if latest is not None else None,
            latest_status_label=(
                str(latest.status).replace("_", " ").title() if latest is not None else None
            ),
            packaging_type=str(latest.packaging_type) if latest is not None else None,
            packaging_type_label=(
                str(latest.packaging_type).replace("_", " ").title() if latest is not None else None
            ),
            packaging_type_other=getattr(latest, "packaging_type_other", None),
            packaging_type_display=(
                display_packaging_type(latest) if latest is not None else None
            ),
            packaging_date=getattr(latest, "packaging_date", None),
            packaged_quantity=getattr(latest, "packaged_quantity", None),
            package_count=len(packages) or (getattr(latest, "number_of_packages", 0) or 0),
            approved_quantity=approved,
            packaged_total=packaged_total,
            remaining_quantity=remaining if remaining > 0 else Decimal("0"),
            unit=run_unit,
            unit_label=_enum_label(run_unit),
            packaged_by_name=person_name(getattr(latest, "packaged_by", None)),
            packaging_unit_name=getattr(getattr(latest, "unit_ref", None), "name", None),
        )

    def distribution_summary_for(self, batch: HoneyBatch):
        """Where this batch's packages have got to, from the shipment records."""
        shipments = sorted(
            list(getattr(batch, "distributions", []) or []),
            key=lambda row: (row.created_at, str(row.id)),
        )
        live = [row for row in shipments if str(row.status) != "CANCELLED"]
        delivered = [row for row in live if str(row.status) == "DELIVERED"]
        open_rows = [row for row in live if str(row.status) != "DELIVERED"]
        latest = (live or shipments)[-1] if (live or shipments) else None
        quantity = sum((row.quantity for row in live), Decimal("0"))
        return BatchDistributionRef(
            shipment_count=len(shipments),
            delivered_count=len(delivered),
            open_count=len(open_rows),
            latest_id=getattr(latest, "id", None),
            latest_code=getattr(latest, "distribution_code", None),
            latest_status=str(latest.status) if latest is not None else None,
            latest_status_label=(
                str(latest.status).replace("_", " ").title() if latest is not None else None
            ),
            destination=getattr(latest, "destination", None),
            retailer_name=person_name(getattr(latest, "retailer", None)),
            carrier=getattr(latest, "carrier", None),
            dispatched_at=getattr(latest, "dispatched_at", None),
            delivered_at=getattr(latest, "delivered_at", None),
            received_by_name=person_name(getattr(latest, "received_by", None)),
            quantity_dispatched=quantity,
            unit=getattr(latest, "unit", None),
            unit_label=(str(getattr(latest, "unit")).title() if latest is not None else None),
        )

    def timeline(self, batch: HoneyBatch) -> list[BatchTraceStage]:
        """The traceability timeline, written from the records rather than from the status.

        Every stop is derived from rows that exist: the collection is complete
        because the batch exists at all; processing is complete because a completed
        run exists against the batch; the laboratory stage is current while the
        batch is ``LAB_TESTING`` and complete once a test has decided it — with the
        outcome shown as its own field, so a rejected batch never reads as a
        completed success. Packaging is reported from the packaging runs, the
        distribution stage from the shipments, and the closing stage from whether
        every package of the batch has actually been received.

        Nothing here is written down twice: the timeline is a *reading* of the
        batch's records, so a beekeeper watching their own honey, a KVIC officer
        watching their cluster and a packaging unit working the batch all see the
        same stops because they are reading the same rows.
        """
        runs = list(getattr(batch, "processing_records", []) or [])
        completed_runs = [run for run in runs if run.status is ProcessingStatus.COMPLETED]
        open_run = next(
            (
                run
                for run in runs
                if run.status in (ProcessingStatus.PENDING, ProcessingStatus.IN_PROGRESS)
            ),
            None,
        )
        latest_run = completed_runs[-1] if completed_runs else open_run

        tests = list(getattr(batch, "lab_tests", []) or [])
        decided_tests = [
            test
            for test in tests
            if test.overall_result in (LabResult.PASS, LabResult.FAIL)
        ]
        open_test = next(
            (
                test
                for test in tests
                if test.status in (LabTestStatus.PENDING, LabTestStatus.IN_PROGRESS)
            ),
            None,
        )
        ordered_tests = sorted(
            tests, key=lambda test: (int(test.round_number or 0), test.created_at, str(test.id))
        )
        decided_ordered = [
            test for test in ordered_tests if test.overall_result in (LabResult.PASS, LabResult.FAIL)
        ]
        latest_test = (
            decided_ordered[-1]
            if decided_ordered
            else next(
                (
                    test
                    for test in reversed(ordered_tests)
                    if test.status in (LabTestStatus.PENDING, LabTestStatus.IN_PROGRESS)
                ),
                None,
            )
        )

        collection_code = getattr(batch.collection, "collection_code", None)
        stages: list[BatchTraceStage] = []

        for stage in BatchStage.ordered():
            if stage is BatchStage.COLLECTION:
                stages.append(
                    BatchTraceStage(
                        stage=stage,
                        label=stage.label,
                        state="completed",
                        reached=True,
                        is_current=batch.status is BatchStatus.COLLECTED,
                        detail=(
                            f"Harvest {collection_code} recorded from "
                            f"{batch.source_hive_count} hive(s)"
                        ),
                        recorded_at=batch.collection_date,
                        module_available=True,
                    )
                )
                continue

            if stage is BatchStage.PROCESSING:
                stages.append(self._processing_stage(batch, completed_runs, latest_run))
                continue

            if stage is BatchStage.LABORATORY:
                stages.append(self._laboratory_stage(batch, decided_tests, latest_test))
                continue

            # Packaging and distribution are reported from their own records, and
            # the closing stage follows from them: a batch is complete when every
            # package of it has been received.
            if stage is BatchStage.PACKAGING:
                stages.append(self._packaging_stage(batch))
                continue

            if stage is BatchStage.DISTRIBUTION:
                stages.append(self._distribution_stage(batch))
                continue

            stages.append(self._completed_stage(batch))
        return stages

    def _packaging_stage(self, batch: HoneyBatch) -> BatchTraceStage:
        stage = BatchStage.PACKAGING
        runs = sorted(
            list(getattr(batch, "packaging_records", []) or []),
            key=lambda row: (row.created_at, str(row.id)),
        )
        completed = [row for row in runs if str(row.status) == "COMPLETED"]
        open_run = next((row for row in runs if getattr(row.status, "is_open", False)), None)
        latest = completed[-1] if completed else None

        if latest is None:
            if open_run is not None:
                return BatchTraceStage(
                    stage=stage,
                    label=stage.label,
                    state="current",
                    reached=True,
                    is_current=batch.status is BatchStatus.APPROVED,
                    detail=(
                        f"Packing {open_run.packaging_code} is "
                        f"{str(open_run.status).replace('_', ' ').lower()}"
                    ),
                    recorded_at=open_run.start_time or open_run.created_at,
                    module_available=True,
                )
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="not_started",
                reached=False,
                is_current=False,
                detail=(
                    "Waiting for the packaging unit"
                    if batch.status is BatchStatus.APPROVED
                    else None
                ),
                recorded_at=None,
                module_available=True,
            )

        packages = [
            package
            for package in (getattr(batch, "packages", []) or [])
            if package.packaging_id == latest.id
        ]
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state="current" if batch.status is BatchStatus.PACKAGED else "completed",
            reached=True,
            is_current=batch.status is BatchStatus.PACKAGED,
            detail=(
                f"{latest.packaging_code}: {latest.number_of_packages or len(packages)} package(s) "
                f"of {latest.package_size} {getattr(latest.unit, 'value', latest.unit)}"
            ),
            recorded_at=latest.completion_time or latest.created_at,
            module_available=True,
        )

    def _distribution_stage(self, batch: HoneyBatch) -> BatchTraceStage:
        stage = BatchStage.DISTRIBUTION
        shipments = sorted(
            list(getattr(batch, "distributions", []) or []),
            key=lambda row: (row.created_at, str(row.id)),
        )
        live = [row for row in shipments if str(row.status) != "CANCELLED"]
        if not live:
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="current" if batch.status is BatchStatus.PACKAGED else "not_started",
                reached=batch.status in (BatchStatus.PACKAGED,),
                is_current=batch.status is BatchStatus.PACKAGED,
                detail=(
                    "Packages are ready; no shipment has been raised yet"
                    if batch.status is BatchStatus.PACKAGED
                    else None
                ),
                recorded_at=None,
                module_available=True,
            )

        delivered = [row for row in live if str(row.status) == "DELIVERED"]
        latest = (delivered or live)[-1]
        if len(delivered) == len(live):
            state, is_current = "completed", batch.status is BatchStatus.DISTRIBUTION
        else:
            state, is_current = "current", True
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state=state,
            reached=True,
            is_current=is_current,
            detail=(
                f"{len(delivered)}/{len(live)} shipment(s) delivered — "
                f"latest {latest.distribution_code} to {latest.destination}"
            ),
            recorded_at=latest.delivered_at or latest.dispatched_at or latest.created_at,
            module_available=True,
        )

    def _completed_stage(self, batch: HoneyBatch) -> BatchTraceStage:
        """The end of the journey: every package packed, shipped and received."""
        stage = BatchStage.COMPLETED
        done = batch.status is BatchStatus.COMPLETED
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state="completed" if done else "not_started",
            reached=done,
            is_current=done,
            detail=(
                "Every package of this batch has been delivered and received"
                if done
                else None
            ),
            recorded_at=batch.updated_at if done else None,
            module_available=True,
        )

    def _processing_stage(self, batch, completed_runs, latest_run) -> BatchTraceStage:
        stage = BatchStage.PROCESSING
        if completed_runs:
            run = completed_runs[-1]
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="completed",
                reached=True,
                is_current=False,
                detail=(
                    f"Processing {run.processing_code}: {run.input_quantity} → "
                    f"{run.output_quantity} {_enum_label(run.unit)}"
                    + (
                        f" ({run.loss_quantity} {_enum_label(run.unit)} less than the input)"
                        if run.loss_quantity is not None
                        else ""
                    )
                ),
                recorded_at=run.completion_time or run.updated_at,
                module_available=True,
                note=(
                    None
                    if len(completed_runs) == 1
                    else f"{len(completed_runs)} completed runs recorded on this batch."
                ),
            )
        if latest_run is not None:
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="current",
                reached=True,
                is_current=True,
                detail=(
                    f"Run {latest_run.processing_code} is {_enum_label(latest_run.status)}"
                    + (
                        " — no quantities recorded yet."
                        if latest_run.input_quantity is None and latest_run.output_quantity is None
                        else ""
                    )
                ),
                recorded_at=latest_run.start_time or latest_run.created_at,
                module_available=True,
                note="The batch becomes ready for the laboratory when this run is completed.",
            )
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state="not_started",
            reached=False,
            is_current=False,
            detail=None,
            recorded_at=None,
            module_available=True,
            note="No processing has been recorded on this batch yet.",
        )

    def _laboratory_stage(self, batch, decided_tests, latest_test) -> BatchTraceStage:
        stage = BatchStage.LABORATORY
        if batch.status in (BatchStatus.APPROVED, BatchStatus.REJECTED) and decided_tests:
            test = decided_tests[-1]  # the latest decided round, as ordered by the caller
            decision = str(batch.status)
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="completed",
                reached=True,
                is_current=False,
                outcome=decision,
                detail=(
                    f"Test {test.test_code} ({test.sample_code}): "
                    f"{test.overall_result}"
                    + (
                        f" — {test.result_summary}"
                        if test.result_summary
                        else ""
                    )
                    + (" [outcome set by hand]" if test.is_override else "")
                ),
                recorded_at=test.completed_at or test.updated_at,
                module_available=True,
                note=(
                    "A retest may be opened against this batch; the records of both "
                    "tests are kept."
                ),
            )
        if latest_test is not None:
            test = latest_test
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="current",
                reached=True,
                is_current=True,
                detail=(
                    f"Test {test.test_code} ({test.sample_code}) is {_enum_label(test.status)}"
                    + (
                        f" — {len(list(getattr(test, 'results', []) or []))} parameter(s) recorded"
                        if getattr(test, "results", None)
                        else " — no measurements recorded yet"
                    )
                ),
                recorded_at=test.sample_collected_at or test.created_at,
                module_available=True,
                note=(
                    "The batch's outcome is decided when the test is completed."
                ),
            )
        # A batch can also sit at LAB_TESTING with no test opened yet.
        has_completed_run = any(
            run.status is ProcessingStatus.COMPLETED
            for run in list(getattr(batch, "processing_records", []) or [])
        )
        if has_completed_run:
            return BatchTraceStage(
                stage=stage,
                label=stage.label,
                state="current",
                reached=True,
                is_current=True,
                detail="Awaiting laboratory testing — no test opened yet.",
                recorded_at=None,
                module_available=True,
                note="A laboratory technician opens a test against the completed processing run.",
            )
        return BatchTraceStage(
            stage=stage,
            label=stage.label,
            state="not_started",
            reached=False,
            is_current=False,
            detail=None,
            recorded_at=None,
            module_available=True,
            note="No laboratory test has been recorded on this batch yet.",
        )

    # ------------------------------------------------------------------ #
    # Phase-6 summaries on the batch detail
    # ------------------------------------------------------------------ #
    def processing_summary_for(self, batch: HoneyBatch) -> tuple[int, BatchProcessingRef | None]:
        """The latest run on the batch, read from the run itself."""
        runs = list(getattr(batch, "processing_records", []) or [])
        if not runs:
            return 0, None
        latest = sorted(runs, key=lambda run: (run.created_at, str(run.id)))[-1]
        unit = getattr(latest, "unit_ref", None)
        loss_percent = None
        if latest.input_quantity not in (None, 0) and latest.output_quantity is not None:
            loss_percent = round(
                float(latest.loss_quantity or 0) / float(latest.input_quantity) * 100, 2
            )
        return len(runs), BatchProcessingRef(
            id=latest.id,
            processing_code=latest.processing_code,
            status=str(latest.status),
            status_label=_label(latest.status),
            processing_type=str(latest.processing_type),
            processing_type_label=_label(latest.processing_type),
            input_quantity=latest.input_quantity,
            output_quantity=latest.output_quantity,
            loss_quantity=latest.loss_quantity,
            loss_percent=loss_percent,
            unit=str(latest.unit),
            unit_label=_label(latest.unit),
            processing_date=latest.processing_date,
            start_time=latest.start_time,
            completion_time=latest.completion_time,
            operator_name=getattr(getattr(latest, "operator", None), "full_name", None),
            processing_unit_name=getattr(unit, "name", None),
            notes=latest.notes,
        )

    def laboratory_summary_for(self, batch: HoneyBatch) -> tuple[int, BatchLabTestRef | None]:
        """The latest test on the batch, with its recorded values — nothing summarised away."""
        tests = list(getattr(batch, "lab_tests", []) or [])
        if not tests:
            return 0, None
        # The newest round, with the id as the last resort — a row cannot be
        # reported as "the latest test" on the strength of a tied timestamp.
        latest = sorted(
            tests, key=lambda test: (int(test.round_number or 0), test.created_at, str(test.id))
        )[-1]
        results = list(getattr(latest, "results", []) or [])
        return len(tests), BatchLabTestRef(
            id=latest.id,
            test_code=latest.test_code,
            sample_code=latest.sample_code,
            status=str(latest.status),
            status_label=_label(latest.status),
            overall_result=str(latest.overall_result),
            overall_result_label=_label(latest.overall_result),
            result_summary=latest.result_summary,
            is_override=bool(latest.is_override),
            round_number=int(latest.round_number or 1),
            test_date=latest.test_date,
            completed_at=latest.completed_at,
            laboratory_name=getattr(getattr(latest, "laboratory", None), "name", None),
            technician_name=getattr(getattr(latest, "technician", None), "full_name", None),
            parameter_count=len(results),
            passed_count=sum(1 for row in results if row.status is LabParameterStatus.PASS),
            failed_count=sum(1 for row in results if row.status is LabParameterStatus.FAIL),
            unevaluated_count=sum(
                1 for row in results if row.status is LabParameterStatus.NOT_EVALUATED
            ),
            results=[
                BatchLabResultRef(
                    parameter_code=row.parameter_code,
                    parameter_name=row.parameter_name,
                    value=row.value,
                    unit=str(row.unit),
                    unit_label=_label(row.unit),
                    status=str(row.status),
                    status_label=_label(row.status),
                    evaluated=row.status is not LabParameterStatus.NOT_EVALUATED,
                    reference_min=row.reference_min,
                    reference_max=row.reference_max,
                    reference_source=row.reference_source,
                )
                for row in results
            ],
        )


__all__ = ["BatchService"]
