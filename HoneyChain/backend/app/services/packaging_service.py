"""Packaging: turning an approved batch into packages, with the quantities kept honest.

The rule this module exists to enforce
-------------------------------------
Packaging is the first point in the chain where honey is *divided*. Everything
before it moves the whole batch; here a part of it becomes forty jars. That makes
three questions answerable in exactly one way:

* **May this batch be packed at all?** Only a batch the laboratory approved.
  A rejected batch is refused, and so is one still under test. The check reads
  ``batch.status`` — the single column the batch lifecycle owns — so no client
  can talk its way past it.
* **How much may be packed?** The measured output of the batch's completed
  processing run, minus what completed packaging runs have already packed. The
  arithmetic is done from stored figures every time; nothing is cached, so the
  answer cannot drift from the records.
* **What actually came out?** The packages, one row each, created when the run
  completes and never deleted. A run may be cancelled before it completes, and a
  cancelled run consumes nothing.

The collection quantity is never touched. Neither is the processing output. What
was harvested, what was processed and what was packed are three recorded facts
that sit next to each other; this module adds the third and reads the other two.
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from app.models.enums import (
    DistributionStatus,
    PACKAGE_STATUS_TRANSITIONS,
    PACKAGING_STATUS_TRANSITIONS,
    AuditAction,
    BatchStatus,
    PackageStatus,
    PackagingStatus,
    PackagingType,
    UserRole,
)
from app.models.document_sequence import DocumentSequence
from app.models.honey_batch import HoneyBatch
from app.models.packaging import HoneyPackage, PackagingRun, PackagingUnit
from app.repositories.batch_repository import BatchRepository
from app.repositories.distribution_repository import DistributionRepository
from app.repositories.packaging_repository import (
    PackageRepository,
    PackagingRepository,
    PackagingUnitRepository,
    approved_quantity_for_batch,
)
from app.schemas.laboratory import TraceabilityNode
from app.schemas.packaging import (
    ApprovedBatchItem,
    PackageDetail,
    PackageListItem,
    PackagingBatchRef,
    PackagingDetail,
    PackagingListItem,
    PackagingPackageRef,
    PackagingQuantityBreakdown,
    PackagingSummary,
    PackagingUnitRead,
)
from app.services import batch_lifecycle
from app.schemas.common import display_choice
from app.services.audit_service import AuditService
from app.services.collection_service import CollectionService
from app.services.names import beekeeper_name, cluster_name, person_name

logger = logging.getLogger(__name__)


def display_packaging_type(row) -> str:
    """What to print for a container: its listed name, or the recorded description."""
    return display_choice(row.packaging_type, getattr(row, "packaging_type_other", None))

#: The roles that do packing work. An administrator is included because the
#: platform has to be operable without one of every role existing; nobody else is.
PACKAGING_ROLES = (UserRole.PACKAGING_UNIT, UserRole.ADMIN)
#: Roles allowed to read packaging records. KVIC reads through its cluster scope,
#: a beekeeper through their own batch — the repository filter does the work.
PACKAGING_READ_ROLES = (
    UserRole.PACKAGING_UNIT,
    UserRole.ADMIN,
    UserRole.KVIC_OFFICER,
    UserRole.BEEKEEPER,
    UserRole.DISTRIBUTOR,
    UserRole.RETAILER,
)


def build_packaging_code(sequence: str, *, when: datetime | None = None) -> str:
    """``HC-PACK-<YYYY>-<NNNNNN>``, e.g. ``HC-PACK-2026-000001``."""
    year = (when or datetime.now(tz=timezone.utc)).year
    return f"HC-PACK-{year}-{sequence}"


def build_package_code(sequence: str, *, when: datetime | None = None) -> str:
    """``HC-PKG-<YYYY>-<NNNNNN>`` — the stable identity of one physical package."""
    year = (when or datetime.now(tz=timezone.utc)).year
    return f"HC-PKG-{year}-{sequence}"


def build_packaging_unit_code(sequence: str) -> str:
    """``HC-PKUNIT-<NNNNNN>``."""
    return f"HC-PKUNIT-{sequence}"


def _label(value) -> str:
    """The plain-language label of an enum value, or the value itself."""
    return getattr(value, "label", None) or str(value)


def _enum_label(value) -> str:
    """A label for any enum that has one, the value otherwise — never a placeholder."""
    if value is None:
        return ""
    return getattr(value, "label", None) or str(getattr(value, "value", value))


def _enum_value(value) -> str | None:
    return None if value is None else str(getattr(value, "value", value))


class PackagingService:
    """Register packaging units, pack approved batches, keep the package register."""

    def __init__(self, session) -> None:  # noqa: ANN001 - Session from the dependency
        self.session = session
        self.units = PackagingUnitRepository(session)
        self.packaging = PackagingRepository(session)
        self.packages = PackageRepository(session)
        self.distributions = DistributionRepository(session)
        self.batches = BatchRepository(session)
        self.audit = AuditService(session)
        self.collections = CollectionService(session)

    # ------------------------------------------------------------------ #
    # Scope and permission
    # ------------------------------------------------------------------ #
    def _assert_can_work(self, user: UserRole | str) -> None:
        """Only a packaging unit (or an administrator) may pack."""
        if getattr(user, "role", None) not in PACKAGING_ROLES:
            raise ForbiddenError(
                "Only a packaging unit may record packaging work.",
                details={"action": "packaging_write", "role": str(getattr(user, "role", None))},
            )

    def _assert_can_read(self, user, batch: HoneyBatch) -> None:
        """Read scope for one batch: the same rules every other module uses."""
        self.collections.assert_record_scope(
            user, record=batch, resource="Packaging record", resource_id=batch.id
        )

    def _assert_can_read_package(self, user, package: HoneyPackage) -> None:
        """Who may open a package.

        Everyone reaches it through the batch scope they already have. A retailer
        is the exception, and only for the packages that were shipped to them: a
        shop reads what it received, and a package that never went there is not
        their record — it is missing, not forbidden.
        """
        if user.role == UserRole.RETAILER:
            mine = any(
                shipment.package_id == package.id
                for shipment in self.distributions.for_retailer(user.id)
            )
            if mine:
                return
            raise NotFoundError(
                f"Package {package.package_code} not found",
                details={"resource": "package"},
            )
        self._assert_can_read(user, package.batch)

    def _scope_filters(self, user) -> dict:
        """Repository filters bounding a packaging listing to what the caller may see."""
        if user.role == UserRole.BEEKEEPER:
            return {"beekeeper_id": self.collections.own_beekeeper(user).id}
        if user.role == UserRole.KVIC_OFFICER:
            return {"cluster_ids": self.collections.officer_cluster_ids(user)}
        return self.collections.workflow_scope_filters(user)

    def _assert_may_edit(self, user, run: PackagingRun, *, action: str) -> None:
        """A packaging run is worked by any packaging unit; nobody else at all."""
        self._assert_can_work(user)
        if not run.status.is_open:
            raise ConflictError(
                f"A {_label(run.status).lower()} packaging run cannot be changed.",
                details={"action": action, "packaging_code": run.packaging_code},
            )

    # ------------------------------------------------------------------ #
    # Packaging units
    # ------------------------------------------------------------------ #
    def create_unit(self, user, payload) -> PackagingUnitRead:
        """Register a packaging facility. Administrator-only, as with every registry."""
        code = build_packaging_unit_code(
            self._next_sequence("PACKAGING_UNIT", width=6)
        )
        unit = PackagingUnit(
            unit_code=code,
            name=payload.name.strip(),
            registration_identifier=payload.registration_identifier,
            location=payload.location,
            district=payload.district,
            state=payload.state,
            contact_email=payload.contact_email,
            contact_phone=payload.contact_phone,
            capacity_kg_per_day=payload.capacity_kg_per_day,
            notes=payload.notes,
        )
        self.session.add(unit)
        try:
            self.session.flush()
        except IntegrityError as exc:  # pragma: no cover - the code is issued by us
            raise ConflictError("A packaging unit with this code already exists") from exc
        self.audit.record(
            AuditAction.PACKAGING_UNIT_CREATED,
            actor=user,
            entity_type="packaging_unit",
            entity_id=unit.id,
            metadata={"unit_code": unit.unit_code, "name": unit.name},
        )
        self.session.commit()
        return self.to_unit_read(unit)

    def list_units(self, user, *, page=1, page_size=20, search=None, status=None) -> tuple[list[PackagingUnitRead], int]:
        rows, total = self.units.search(
            page=page, page_size=page_size, search=search, status=_enum_value(status)
        )
        return [self.to_unit_read(row) for row in rows], total

    def update_unit(self, user, unit_id: uuid.UUID, payload) -> PackagingUnitRead:
        unit = self.units.get(unit_id)
        if unit is None:
            raise NotFoundError(
                f"Packaging unit {unit_id} not found", details={"resource": "packaging_unit"}
            )
        for field in (
            "name",
            "registration_identifier",
            "location",
            "district",
            "state",
            "contact_email",
            "contact_phone",
            "capacity_kg_per_day",
            "status",
            "notes",
        ):
            value = getattr(payload, field, None)
            if value is not None:
                setattr(unit, field, value)
        self.session.flush()
        self.audit.record(
            AuditAction.PACKAGING_UNIT_UPDATED,
            actor=user,
            entity_type="packaging_unit",
            entity_id=unit.id,
            metadata={"unit_code": unit.unit_code, "status": str(unit.status)},
        )
        self.session.commit()
        return self.to_unit_read(unit)

    # ------------------------------------------------------------------ #
    # Approved batches waiting to be packed
    # ------------------------------------------------------------------ #
    def approved_batches(
        self,
        user,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        include_packed: bool = True,
    ) -> tuple[list[ApprovedBatchItem], int]:
        """Batches a packaging unit may take work from, built from the batch's own records.

        The route asks for the packaging permission before calling this, so the
        only callers here are people who pack: an administrator or a packaging
        unit. Read-only roles follow the same records through the batch timeline.

        Only batches the laboratory approved appear — plus any that are already
        ``PACKAGED`` and still have honey left to pack, because a batch can be
        packed over several runs. A rejected batch is not hidden by a frontend
        filter: it is never returned, because the query asks for the statuses that
        may be packed and a rejection is not one of them.
        """
        rows, total = self.batches.search(
            page=page,
            page_size=page_size,
            search=search,
            statuses=[BatchStatus.APPROVED, BatchStatus.PACKAGED],
            **self._scope_filters(user),
        )
        items: list[ApprovedBatchItem] = []
        for batch in rows:
            item = self.to_approved_item(batch)
            # A batch that has already been packed in full is not work waiting to
            # happen; one that is *partly* packed still has honey to pack, which is
            # why PACKAGED batches stay on this list while anything remains.
            if include_packed or item.remaining_quantity > 0:
                items.append(item)
        return items, total

    def batch_quantities(self, batch: HoneyBatch) -> PackagingQuantityBreakdown:
        """Approved, packaged and remaining quantity, computed from the stored records."""
        approved = approved_quantity_for_batch(self.session, batch.id)
        packaged = self.packaging.packaged_quantity_for_batch(batch.id)
        remaining = approved - packaged
        if remaining < 0:  # pragma: no cover - the service refuses to create this state
            remaining = Decimal("0")
        return PackagingQuantityBreakdown(
            approved_quantity=approved,
            packaged_quantity=packaged,
            remaining_quantity=remaining,
            unit=batch.unit,
        )

    # ------------------------------------------------------------------ #
    # Packaging runs
    # ------------------------------------------------------------------ #
    def create_packaging(self, user, payload) -> PackagingDetail:
        """Open a packing run against an approved batch.

        The batch is re-read and re-checked here: an id in a request body is a
        claim, and the claim is verified against the stored batch before a single
        row is written.
        """
        self._assert_can_work(user)
        batch = self._load_packable_batch(user, payload.batch_id)
        self._assert_no_open_run(batch)

        quantities = self.batch_quantities(batch)
        packaged_quantity = payload.packaged_quantity
        if packaged_quantity is not None and packaged_quantity > quantities.remaining_quantity:
            raise ValidationError(
                "The packaged quantity is more than the batch has left to pack.",
                details={
                    "approved_quantity": str(quantities.approved_quantity),
                    "already_packaged": str(quantities.packaged_quantity),
                    "remaining_quantity": str(quantities.remaining_quantity),
                    "requested": str(packaged_quantity),
                },
            )

        unit = self._resolve_unit(user, payload.packaging_unit_id)
        run = PackagingRun(
            packaging_code=self._next_code(),
            batch_id=batch.id,
            packaging_unit_id=unit.id if unit else None,
            packaged_by_id=user.id,
            status=PackagingStatus.PENDING,
            packaging_type=payload.packaging_type,
            packaging_type_other=payload.packaging_type_other,
            packaging_date=payload.packaging_date or date.today(),
            input_quantity=payload.input_quantity,
            packaged_quantity=packaged_quantity,
            package_size=payload.package_size,
            number_of_packages=payload.number_of_packages,
            unit=batch.unit,
            notes=payload.notes,
        )
        self.session.add(run)
        try:
            self.session.flush()
        except IntegrityError as exc:
            # The partial unique index is the last line of defence against two
            # rival runs for one batch; the friendly check above catches it first.
            raise ConflictError(
                "This batch already has a packaging run under way.",
                details={"batch_code": batch.batch_code},
            ) from exc

        self.audit.record(
            AuditAction.PACKAGING_CREATED,
            actor=user,
            entity_type="packaging",
            entity_id=run.id,
            metadata={
                "packaging_code": run.packaging_code,
                "batch_id": str(batch.id),
                "batch_code": batch.batch_code,
                "packaging_type": str(run.packaging_type),
                "unit": run.unit,
                "packaged_quantity": str(run.packaged_quantity),
                "number_of_packages": run.number_of_packages,
                "packaging_unit_code": unit.unit_code if unit else None,
            },
            description=f"Packaging {run.packaging_code} opened for batch {batch.batch_code}",
        )
        self.session.commit()
        return self.get_packaging(user, run.id)

    def list_packaging(
        self,
        user,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: PackagingStatus | None = None,
        statuses: list[PackagingStatus] | None = None,
        batch_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
    ) -> tuple[list[PackagingListItem], int]:
        rows, total = self.packaging.search(
            page=page,
            page_size=page_size,
            search=search,
            status=status_filter,
            statuses=statuses,
            batch_id=batch_id,
            cluster_id=cluster_id,
        )
        filtered = [row for row in rows if self._in_scope(user, row.batch)]
        # The caller goes into the row flags. Without them the builder treats every
        # row as the caller's own work, which would offer a beekeeper or a KVIC
        # officer buttons the server is going to refuse.
        return [self.to_list_item(row, user) for row in filtered], (
            total if len(filtered) == len(rows) else len(filtered)
        )

    def get_packaging(self, user, packaging_id: uuid.UUID) -> PackagingDetail:
        run = self._load(packaging_id)
        self._assert_can_read(user, run.batch)
        return self.to_detail(run, user=user)

    def update_packaging(self, user, packaging_id: uuid.UUID, payload) -> PackagingDetail:
        """Correct a run while it is open. A completed run is history and is never rewritten."""
        run = self._load(packaging_id)
        self._assert_may_edit(user, run, action="packaging_update")

        for field in (
            "packaging_type",
            "packaging_date",
            "input_quantity",
            "packaged_quantity",
            "package_size",
            "number_of_packages",
            "notes",
        ):
            value = getattr(payload, field, None)
            if value is not None:
                setattr(run, field, value)

        # The container and its description move together: changing the type to a
        # listed one drops a description that no longer applies, and choosing Other
        # requires one. Leaving the pair disagreeing would be exactly the
        # half-recorded "Other" this field exists to prevent.
        if "packaging_type" in payload.model_fields_set or "packaging_type_other" in payload.model_fields_set:
            run.packaging_type_other = (
                (payload.packaging_type_other or "").strip() or None
                if str(run.packaging_type) == PackagingType.OTHER.value
                else None
            )
            if str(run.packaging_type) == PackagingType.OTHER.value and not run.packaging_type_other:
                raise ValidationError(
                    "Describe the container: with the packaging type set to Other, the record "
                    "has to say what the container was.",
                    details={"packaging_code": run.packaging_code, "field": "packaging_type_other"},
                )

        if payload.packaging_unit_id is not None:
            unit = self._resolve_unit(user, payload.packaging_unit_id)
            run.packaging_unit_id = unit.id if unit else None

        self._assert_quantities_fit(run)
        self.session.flush()
        self.audit.record(
            AuditAction.PACKAGING_UPDATED,
            actor=user,
            entity_type="packaging",
            entity_id=run.id,
            metadata={
                "packaging_code": run.packaging_code,
                "packaged_quantity": str(run.packaged_quantity),
                "number_of_packages": run.number_of_packages,
            },
        )
        self.session.commit()
        return self.get_packaging(user, run.id)

    def start_packaging(self, user, packaging_id: uuid.UUID) -> PackagingDetail:
        run = self._load(packaging_id)
        self._assert_can_work(user)
        self._transition(run, PackagingStatus.IN_PROGRESS, action="packaging_start")
        run.start_time = run.start_time or datetime.now(tz=timezone.utc)
        self.session.flush()
        self.audit.record(
            AuditAction.PACKAGING_STARTED,
            actor=user,
            entity_type="packaging",
            entity_id=run.id,
            metadata={"packaging_code": run.packaging_code, "batch_code": run.batch.batch_code},
        )
        self.session.commit()
        return self.get_packaging(user, run.id)

    def complete_packaging(self, user, packaging_id: uuid.UUID, payload) -> PackagingDetail:
        """Finish the run: check the arithmetic, create the packages, move the batch.

        The order matters. Quantities are validated *before* any package row
        exists, packages are created inside the same transaction as the status
        change, and the batch only becomes ``PACKAGED`` once both have happened —
        so a failure at any point leaves no half-packed batch behind.
        """
        run = self._load(packaging_id)
        self._assert_may_edit(user, run, action="packaging_complete")

        for field in ("packaged_quantity", "input_quantity", "package_size", "number_of_packages", "notes"):
            value = getattr(payload, field, None)
            if value is not None:
                setattr(run, field, value)

        self._assert_completable(run)
        self._assert_quantities_fit(run)
        self._assert_count_matches(run)

        now = datetime.now(tz=timezone.utc)
        previous_status = str(run.batch.status)
        # Through the transition map, not by assignment: a run that was never
        # started is not a run that can finish, and the map is where that rule
        # lives for both this route and any future one.
        self._transition(run, PackagingStatus.COMPLETED, action="packaging_complete")
        run.completion_time = now

        packages = self._create_packages(run)
        self.session.flush()

        # The batch moves only because the packages now exist, and the lifecycle
        # map owns the move: ``APPROVED → PACKAGED`` is the only edge this can
        # take, plus the self-transition a *second* run on the same batch makes.
        if run.batch.status is not BatchStatus.PACKAGED:
            batch_lifecycle.advance(run.batch, BatchStatus.PACKAGED, action="packaging_complete")

        self.audit.record(
            AuditAction.PACKAGING_COMPLETED,
            actor=user,
            entity_type="packaging",
            entity_id=run.id,
            metadata={
                "packaging_code": run.packaging_code,
                "batch_id": str(run.batch_id),
                "batch_code": run.batch.batch_code,
                "packaged_quantity": str(run.packaged_quantity),
                "number_of_packages": run.number_of_packages,
                "unit": run.unit,
                "previous_batch_status": previous_status,
                "batch_status": str(run.batch.status),
                "package_codes": [package.package_code for package in packages],
            },
            description=(
                f"{run.number_of_packages} packages created for batch {run.batch.batch_code}"
            ),
        )
        for package in packages:
            self.audit.record(
                AuditAction.PACKAGE_CREATED,
                actor=user,
                entity_type="package",
                entity_id=package.id,
                metadata={
                    "package_code": package.package_code,
                    "batch_id": str(package.batch_id),
                    "batch_code": run.batch.batch_code,
                    "packaging_code": run.packaging_code,
                    "quantity": str(package.quantity),
                    "unit": package.unit,
                    "status": str(package.status),
                },
            )
        self.session.commit()
        return self.get_packaging(user, run.id)

    def cancel_packaging(self, user, packaging_id: uuid.UUID, payload) -> PackagingDetail:
        """Abandon a run that never completed. No packages exist, so nothing is consumed."""
        run = self._load(packaging_id)
        self._assert_may_edit(user, run, action="packaging_cancel")
        self._transition(run, PackagingStatus.CANCELLED, action="packaging_cancel")
        run.cancelled_at = datetime.now(tz=timezone.utc)
        if getattr(payload, "reason", None):
            run.notes = payload.reason
        self.session.flush()
        self.audit.record(
            AuditAction.PACKAGING_CANCELLED,
            actor=user,
            entity_type="packaging",
            entity_id=run.id,
            metadata={
                "packaging_code": run.packaging_code,
                "batch_code": run.batch.batch_code,
                "reason": getattr(payload, "reason", None),
            },
        )
        self.session.commit()
        return self.get_packaging(user, run.id)

    # ------------------------------------------------------------------ #
    # Packages
    # ------------------------------------------------------------------ #
    def list_packages(
        self,
        user,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status_filter: PackageStatus | None = None,
        statuses: list[PackageStatus] | None = None,
        batch_id: uuid.UUID | None = None,
        packaging_id: uuid.UUID | None = None,
        cluster_id: uuid.UUID | None = None,
    ) -> tuple[list[PackageListItem], int]:
        rows, total = self.packages.search(
            page=page,
            page_size=page_size,
            search=search,
            status=status_filter,
            statuses=statuses,
            batch_id=batch_id,
            packaging_id=packaging_id,
            cluster_id=cluster_id,
        )
        filtered = [row for row in rows if self._in_scope(user, row.batch)]
        return [self.to_package_item(row) for row in filtered], (
            total if len(filtered) == len(rows) else len(filtered)
        )

    def get_package(self, user, package_id: uuid.UUID) -> PackageDetail:
        package = self._load_package(package_id)
        self._assert_can_read_package(user, package)
        return self.to_package_detail(package, user=user)

    def release_package(self, user, package_id: uuid.UUID, payload=None) -> PackageDetail:
        """Release a freshly created package for distribution.

        Existence is not readiness: a package is only offered to a distributor
        once the packing unit has released it, which is a separate, audited act.
        """
        package = self._load_package(package_id)
        self._assert_can_work(user)
        self._transition_package(package, PackageStatus.READY_FOR_DISTRIBUTION, action="package_release")
        package.released_at = datetime.now(tz=timezone.utc)
        if payload is not None and getattr(payload, "notes", None):
            package.notes = payload.notes
        self.session.flush()
        self.audit.record(
            AuditAction.PACKAGE_STATUS_CHANGED,
            actor=user,
            entity_type="package",
            entity_id=package.id,
            metadata={
                "package_code": package.package_code,
                "batch_code": package.batch.batch_code,
                "status": str(package.status),
            },
        )
        self.session.commit()
        return self.to_package_detail(package, user=user)

    def release_packaging_packages(self, user, packaging_id: uuid.UUID) -> list[PackageListItem]:
        """Release every package a completed run produced, in one act."""
        run = self._load(packaging_id)
        self._assert_can_work(user)
        released: list[HoneyPackage] = []
        for package in self.packages.for_packaging(run.id):
            if package.status is PackageStatus.CREATED:
                self._transition_package(
                    package, PackageStatus.READY_FOR_DISTRIBUTION, action="package_release"
                )
                package.released_at = datetime.now(tz=timezone.utc)
                released.append(package)
        self.session.flush()
        if released:
            self.audit.record(
                AuditAction.PACKAGE_STATUS_CHANGED,
                actor=user,
                entity_type="packaging",
                entity_id=run.id,
                metadata={
                    "packaging_code": run.packaging_code,
                    "packages": [package.package_code for package in released],
                    "status": str(PackageStatus.READY_FOR_DISTRIBUTION),
                },
            )
        self.session.commit()
        return [self.to_package_item(package) for package in released]

    # ------------------------------------------------------------------ #
    # Dashboard
    # ------------------------------------------------------------------ #
    def summary(self, user) -> PackagingSummary:
        """Counters for the packaging dashboard, counted from the records."""
        counts = self.packaging.count_by_status()
        package_counts = self.packages.count_by_status()
        approved, _total = self.approved_batches(user, page=1, page_size=200)

        awaiting = sum(
            1 for row in approved if row.remaining_quantity > 0 and row.open_packaging_id is None
        )
        packaged_total = sum((row.packaged_quantity for row in approved), Decimal("0"))
        remaining_total = sum((row.remaining_quantity for row in approved), Decimal("0"))
        return PackagingSummary(
            total=sum(counts.values()),
            by_status=counts,
            approved_batches=len(approved),
            awaiting_packaging=awaiting,
            in_progress=counts.get(PackagingStatus.IN_PROGRESS.value, 0),
            completed=counts.get(PackagingStatus.COMPLETED.value, 0),
            packages_created=sum(package_counts.values()),
            packages_ready=package_counts.get(PackageStatus.READY_FOR_DISTRIBUTION.value, 0),
            packages_in_distribution=package_counts.get(PackageStatus.IN_DISTRIBUTION.value, 0),
            packages_delivered=package_counts.get(PackageStatus.DELIVERED.value, 0),
            quantity_packaged=packaged_total,
            quantity_remaining=remaining_total,
            unit=approved[0].unit if approved else None,
        )

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _load(self, packaging_id: uuid.UUID) -> PackagingRun:
        run = self.packaging.get_with_relations(packaging_id)
        if run is None:
            raise NotFoundError(
                f"Packaging record {packaging_id} not found", details={"resource": "packaging"}
            )
        return run

    def _load_package(self, package_id: uuid.UUID) -> HoneyPackage:
        package = self.packages.get_with_relations(package_id)
        if package is None:
            raise NotFoundError(
                f"Package {package_id} not found", details={"resource": "package"}
            )
        return package

    def _load_packable_batch(self, user, batch_id: uuid.UUID) -> HoneyBatch:
        """The batch, or a refusal that says exactly why it may not be packed."""
        batch = self.batches.get_with_relations(batch_id)
        if batch is None:
            raise NotFoundError(
                f"Honey batch {batch_id} not found", details={"resource": "batch"}
            )
        self._assert_can_read(user, batch)
        # PACKAGED is allowed as well as APPROVED, and only because a batch may be
        # packed in several runs: the first run moves it to PACKAGED, and a later
        # run packs what is left. Everything else is refused, and the message says
        # which refusal it is — a rejection is not the same fact as "not yet".
        if batch.status not in (BatchStatus.APPROVED, BatchStatus.PACKAGED):
            reason = {
                BatchStatus.REJECTED: "The batch was rejected by the laboratory.",
                BatchStatus.LAB_TESTING: "The laboratory has not decided this batch yet.",
                BatchStatus.COLLECTED: "The batch has not been processed yet.",
                BatchStatus.PROCESSING: "The batch is still being processed.",
            }.get(batch.status, "The batch is not at the packaging stage.")
            raise ConflictError(
                "Only a laboratory-approved batch may be packed.",
                details={
                    "batch_code": batch.batch_code,
                    "batch_status": str(batch.status),
                    "batch_status_label": batch_lifecycle.STATUS_LABEL.get(
                        batch.status, _label(batch.status)
                    ),
                    "reason": reason,
                },
            )
        return batch

    def _assert_no_open_run(self, batch: HoneyBatch) -> None:
        existing = self.packaging.open_for_batch(batch.id)
        if existing is not None:
            raise ConflictError(
                "This batch already has a packaging run under way.",
                details={
                    "batch_code": batch.batch_code,
                    "packaging_code": existing.packaging_code,
                    "packaging_id": str(existing.id),
                },
            )

    def _resolve_unit(self, user, unit_id: uuid.UUID | None) -> PackagingUnit | None:
        if unit_id is None:
            return None
        unit = self.units.get(unit_id)
        if unit is None:
            raise NotFoundError(
                f"Packaging unit {unit_id} not found", details={"resource": "packaging_unit"}
            )
        if not unit.is_active:
            raise ConflictError(
                f"Packaging unit {unit.unit_code} is {unit.status} and cannot take new work.",
                details={"unit_code": unit.unit_code, "status": str(unit.status)},
            )
        return unit

    def _in_scope(self, user, batch: HoneyBatch | None) -> bool:
        """Whether a batch falls inside the caller's read scope."""
        if batch is None:  # pragma: no cover - the foreign key makes this unreachable
            return False
        if user.role in (UserRole.ADMIN, UserRole.PACKAGING_UNIT):
            return True
        if user.role == UserRole.BEEKEEPER:
            try:
                return batch.beekeeper_id == self.collections.own_beekeeper(user).id
            except NotFoundError:
                return False
        if user.role == UserRole.KVIC_OFFICER:
            return getattr(batch, "cluster_id", None) in self.collections.officer_cluster_ids(user)
        # Distributors and retailers read packages through their own endpoints,
        # which are bounded by the shipments addressed to them.
        return False

    def _assert_quantities_fit(self, run: PackagingRun) -> None:
        """A run may never claim more honey than the batch has left, nor more than it drew."""
        if (
            run.packaged_quantity is not None
            and run.input_quantity is not None
            and run.packaged_quantity > run.input_quantity
        ):
            raise ValidationError(
                "The packaged quantity cannot exceed the quantity taken from the batch.",
                details={
                    "packaged_quantity": str(run.packaged_quantity),
                    "input_quantity": str(run.input_quantity),
                },
            )
        if run.packaged_quantity is None:
            return
        quantities = self.batch_quantities(run.batch)
        if run.packaged_quantity > quantities.remaining_quantity:
            raise ValidationError(
                "The packaged quantity is more than the batch has left to pack.",
                details={
                    "packaging_code": run.packaging_code,
                    "approved_quantity": str(quantities.approved_quantity),
                    "already_packaged": str(quantities.packaged_quantity),
                    "remaining_quantity": str(quantities.remaining_quantity),
                    "requested": str(run.packaged_quantity),
                },
            )

    def _assert_completable(self, run: PackagingRun) -> None:
        missing = [
            name
            for name, value in (
                ("packaged_quantity", run.packaged_quantity),
                ("package_size", run.package_size),
                ("number_of_packages", run.number_of_packages),
            )
            if value is None
        ]
        if missing:
            raise ValidationError(
                "A packaging run cannot complete without the measured quantity, the package size "
                "and the number of packages.",
                details={"packaging_code": run.packaging_code, "missing": missing},
            )

    def _assert_count_matches(self, run: PackagingRun) -> None:
        """The declared packages must add up to the honey that was actually packed.

        Forty packages of 1 kg and 30 kg of honey cannot both be true. The check
        is exact: the platform compares the numbers it was given rather than
        quietly adjusting one of them.
        """
        expected = (run.package_size or Decimal("0")) * Decimal(run.number_of_packages or 0)
        if expected != run.packaged_quantity:
            raise ValidationError(
                "The package size and count do not add up to the packaged quantity.",
                details={
                    "packaging_code": run.packaging_code,
                    "package_size": str(run.package_size),
                    "number_of_packages": run.number_of_packages,
                    "package_size_x_count": str(expected),
                    "packaged_quantity": str(run.packaged_quantity),
                    "unit": run.unit,
                },
            )

    def _create_packages(self, run: PackagingRun) -> list[HoneyPackage]:
        """Create one row per package, each with its own stable code."""
        count = int(run.number_of_packages or 0)
        per_package = (run.packaged_quantity or Decimal("0")) / Decimal(count)
        packages: list[HoneyPackage] = []
        for index in range(1, count + 1):
            package = HoneyPackage(
                package_code=self._next_package_code(),
                sequence_number=index,
                packaging_id=run.id,
                batch_id=run.batch_id,
                # The cluster travels with the package, so a cluster can list what
                # its beekeepers produced without walking back up the chain.
                cluster_id=getattr(run, "cluster_id", None),
                package_size=run.package_size or per_package,
                quantity=per_package,
                unit=run.unit,
                packaging_type=run.packaging_type,
                packaging_type_other=run.packaging_type_other,
                packaging_date=run.packaging_date,
                status=PackageStatus.CREATED,
            )
            self.session.add(package)
            packages.append(package)
        return packages

    def _transition(self, run: PackagingRun, target: PackagingStatus, *, action: str) -> None:
        if target not in PACKAGING_STATUS_TRANSITIONS.get(run.status, ()):
            raise ConflictError(
                f"A {_label(run.status).lower()} packaging run cannot move to {_label(target).lower()}.",
                details={
                    "action": action,
                    "packaging_code": run.packaging_code,
                    "status": str(run.status),
                    "requested": str(target),
                },
            )
        run.status = target

    def _transition_package(self, package: HoneyPackage, target: PackageStatus, *, action: str) -> None:
        if target not in PACKAGE_STATUS_TRANSITIONS.get(package.status, ()):
            raise ConflictError(
                f"A {_label(package.status).lower()} package cannot move to {_label(target).lower()}.",
                details={
                    "action": action,
                    "package_code": package.package_code,
                    "status": str(package.status),
                    "requested": str(target),
                },
            )
        package.status = target

    def _next_sequence(self, scope: str, *, width: int) -> str:
        return DocumentSequence.next_value(self.session, scope, width=width)

    def _next_code(self) -> str:
        scope = f"PACKAGING:{datetime.now(tz=timezone.utc).strftime('%Y')}"
        return build_packaging_code(self._next_sequence(scope, width=6))

    def _next_package_code(self) -> str:
        scope = f"PACKAGE:{datetime.now(tz=timezone.utc).strftime('%Y')}"
        return build_package_code(self._next_sequence(scope, width=6))

    # ------------------------------------------------------------------ #
    # Serialisation
    # ------------------------------------------------------------------ #
    def to_unit_read(self, unit: PackagingUnit) -> PackagingUnitRead:
        return PackagingUnitRead(
            id=unit.id,
            unit_code=unit.unit_code,
            name=unit.name,
            registration_identifier=unit.registration_identifier,
            location=unit.location,
            district=unit.district,
            state=unit.state,
            contact_email=unit.contact_email,
            contact_phone=unit.contact_phone,
            capacity_kg_per_day=unit.capacity_kg_per_day,
            status=unit.status,
            status_label=_label(unit.status),
            is_active=unit.is_active,
            is_demo=unit.is_demo,
            notes=unit.notes,
            created_at=unit.created_at,
            updated_at=unit.updated_at,
        )

    def to_approved_item(self, batch: HoneyBatch) -> ApprovedBatchItem:
        """One row of the packaging worklist, read from the batch and its records."""
        quantities = self.batch_quantities(batch)
        packaging_runs = list(getattr(batch, "packaging_records", []) or [])
        completed = [row for row in packaging_runs if row.status is PackagingStatus.COMPLETED]
        open_run = next((row for row in packaging_runs if row.status.is_open), None)
        latest = completed[-1] if completed else None
        processing = self._latest_completed_processing(batch)
        test = self._latest_decided_test(batch)
        return ApprovedBatchItem(
            batch_id=batch.id,
            batch_code=batch.batch_code,
            batch_status=str(batch.status),
            batch_status_label=batch_lifecycle.STATUS_LABEL.get(batch.status, _label(batch.status)),
            collection_id=batch.collection_id,
            collection_code=getattr(batch.collection, "collection_code", None),
            collection_date=batch.collection_date,
            collection_quantity=batch.quantity,
            unit=batch.unit,
            unit_label=_label(batch.unit),
            beekeeper_id=batch.beekeeper_id,
            beekeeper_name=beekeeper_name(getattr(batch, "beekeeper", None)),
            beekeeper_code=getattr(getattr(batch, "beekeeper", None), "beekeeper_code", None),
            cluster_id=getattr(batch, "cluster_id", None),
            cluster_name=cluster_name(getattr(batch, "cluster", None)),
            cluster_code=getattr(getattr(batch, "cluster", None), "cluster_code", None),
            processing_id=getattr(processing, "id", None),
            processing_code=getattr(processing, "processing_code", None),
            processing_output_quantity=getattr(processing, "output_quantity", None),
            laboratory_id=getattr(test, "laboratory_id", None),
            laboratory_test_code=getattr(test, "test_code", None),
            laboratory_result=_enum_value(getattr(test, "overall_result", None)),
            laboratory_result_label=_label(getattr(test, "overall_result", None))
            if test is not None
            else None,
            approved_quantity=quantities.approved_quantity,
            packaged_quantity=quantities.packaged_quantity,
            remaining_quantity=quantities.remaining_quantity,
            package_count=len(batch.packages or []) if hasattr(batch, "packages") else 0,
            packaging_status=_enum_value(getattr(latest, "status", None)),
            packaging_status_label=_label(latest.status) if latest is not None else None,
            open_packaging_id=getattr(open_run, "id", None),
            open_packaging_code=getattr(open_run, "packaging_code", None),
        )

    def to_list_item(self, run: PackagingRun, user=None) -> PackagingListItem:
        batch = run.batch
        may_work = user is None or getattr(user, "role", None) in PACKAGING_ROLES
        return PackagingListItem(
            id=run.id,
            packaging_code=run.packaging_code,
            batch_id=run.batch_id,
            batch_code=batch.batch_code,
            collection_code=getattr(batch.collection, "collection_code", None),
            beekeeper_id=batch.beekeeper_id,
            beekeeper_name=beekeeper_name(getattr(batch, "beekeeper", None)),
            beekeeper_code=getattr(getattr(batch, "beekeeper", None), "beekeeper_code", None),
            cluster_id=getattr(batch, "cluster_id", None),
            cluster_name=cluster_name(getattr(batch, "cluster", None)),
            cluster_code=getattr(getattr(batch, "cluster", None), "cluster_code", None),
            packaging_unit_id=run.packaging_unit_id,
            packaging_unit_code=getattr(run.unit_ref, "unit_code", None),
            packaging_unit_name=getattr(run.unit_ref, "name", None),
            packaged_by_id=run.packaged_by_id,
            packaged_by_name=person_name(run.packaged_by),
            status=run.status,
            status_label=_label(run.status),
            packaging_type=run.packaging_type,
            packaging_type_label=_label(run.packaging_type),
            packaging_type_other=run.packaging_type_other,
            packaging_type_display=display_packaging_type(run),
            packaging_date=run.packaging_date,
            input_quantity=run.input_quantity,
            packaged_quantity=run.packaged_quantity,
            package_size=run.package_size,
            number_of_packages=run.number_of_packages,
            unit=run.unit,
            unit_label=_label(run.unit),
            package_count=len(run.packages or []),
            start_time=run.start_time,
            completion_time=run.completion_time,
            cancelled_at=run.cancelled_at,
            notes=run.notes,
            created_at=run.created_at,
            updated_at=run.updated_at,
            can_start=may_work and run.status is PackagingStatus.PENDING,
            can_complete=may_work and run.status is PackagingStatus.IN_PROGRESS,
            can_cancel=may_work and run.status.is_open,
            can_edit=may_work and run.status.is_open,
        )

    def to_detail(self, run: PackagingRun, user=None) -> PackagingDetail:
        base = self.to_list_item(run, user=user)
        quantities = self.batch_quantities(run.batch)
        return PackagingDetail(
            **base.model_dump(),
            batch=self.batch_ref(run.batch),
            quantities=quantities,
            packages=[
                PackagingPackageRef(
                    id=package.id,
                    package_code=package.package_code,
                    sequence_number=package.sequence_number,
                    package_size=package.package_size,
                    quantity=package.quantity,
                    unit=package.unit,
                    status=package.status,
                    status_label=_label(package.status),
                )
                for package in sorted(run.packages or [], key=lambda row: row.sequence_number)
            ],
            traceability=self.traceability_for_batch(run.batch, packaging=run),
            next_step=self._next_step(run),
        )

    def to_package_item(self, package: HoneyPackage) -> PackageListItem:
        batch = package.batch
        shipped, remaining = self._package_shipment_totals(package)
        return PackageListItem(
            id=package.id,
            package_code=package.package_code,
            sequence_number=package.sequence_number,
            batch_id=package.batch_id,
            batch_code=batch.batch_code,
            collection_code=getattr(batch.collection, "collection_code", None),
            beekeeper_name=beekeeper_name(getattr(batch, "beekeeper", None)),
            cluster_name=cluster_name(getattr(batch, "cluster", None)),
            packaging_id=package.packaging_id,
            packaging_code=getattr(package.packaging, "packaging_code", ""),
            packaging_unit_name=getattr(getattr(package.packaging, "unit_ref", None), "name", None),
            package_size=package.package_size,
            quantity=package.quantity,
            unit=package.unit,
            unit_label=_label(package.unit),
            packaging_type=package.packaging_type,
            packaging_type_label=_label(package.packaging_type),
            packaging_type_other=package.packaging_type_other,
            packaging_type_display=display_packaging_type(package),
            packaging_date=package.packaging_date,
            status=package.status,
            status_label=_label(package.status),
            released_at=package.released_at,
            delivered_at=package.delivered_at,
            dispatched_quantity=shipped,
            remaining_quantity=remaining,
            shipment_count=len(self._shipments_for(package)),
            created_at=package.created_at,
            updated_at=package.updated_at,
            can_release=package.status is PackageStatus.CREATED,
        )

    def to_package_detail(self, package: HoneyPackage, user=None) -> PackageDetail:
        base = self.to_package_item(package)
        batch = package.batch
        return PackageDetail(
            **base.model_dump(),
            batch=self.batch_ref(batch),
            notes=package.notes,
            traceability=self.traceability_for_batch(batch, packaging=package.packaging, package=package),
        )

    @staticmethod
    def batch_ref(batch: HoneyBatch) -> PackagingBatchRef:
        return PackagingBatchRef(
            id=batch.id,
            batch_code=batch.batch_code,
            status=str(batch.status),
            status_label=batch_lifecycle.STATUS_LABEL.get(batch.status, _label(batch.status)),
            current_stage=str(batch.current_stage),
            current_stage_label=_label(batch.current_stage),
            collection_id=batch.collection_id,
            collection_code=getattr(batch.collection, "collection_code", None),
            collection_date=batch.collection_date,
            quantity=batch.quantity,
            unit=batch.unit,
            beekeeper_id=batch.beekeeper_id,
            beekeeper_name=beekeeper_name(getattr(batch, "beekeeper", None)),
            beekeeper_code=getattr(getattr(batch, "beekeeper", None), "beekeeper_code", None),
            cluster_id=getattr(batch, "cluster_id", None),
            cluster_name=cluster_name(getattr(batch, "cluster", None)),
            cluster_code=getattr(getattr(batch, "cluster", None), "cluster_code", None),
        )

    def traceability_for_batch(self, batch, *, packaging=None, package=None) -> list[TraceabilityNode]:
        """Package → packaging → batch → processing → collection → hives → beekeeper → cluster.

        Assembled from the records on every read: there is no stored copy of the
        chain to fall out of date when an upstream record changes.
        """
        nodes: list[TraceabilityNode] = []
        if package is not None:
            nodes.append(
                TraceabilityNode(
                    kind="PACKAGE",
                    label="Package",
                    identifier=package.package_code,
                    detail=f"{package.quantity} {_label(package.unit)} — {_label(package.status)}",
                    recorded_at=package.packaging_date,
                    href=f"/api/v1/packages/{package.id}",
                )
            )
        if packaging is not None:
            nodes.append(
                TraceabilityNode(
                    kind="PACKAGING",
                    label="Packaging run",
                    identifier=packaging.packaging_code,
                    detail=(
                        f"{_label(packaging.packaging_type)} — {packaging.number_of_packages or 0} × "
                        f"{packaging.package_size or 0} {_label(packaging.unit)}"
                    ),
                    recorded_at=packaging.completion_time or packaging.created_at,
                    href=f"/api/v1/packaging/{packaging.id}",
                )
            )
        nodes.append(
            TraceabilityNode(
                kind="BATCH",
                label="Honey batch",
                identifier=batch.batch_code,
                detail=f"{batch.quantity} {_label(batch.unit)} — {_label(batch.status)}",
                recorded_at=batch.created_at,
                href=f"/api/v1/batches/{batch.id}",
            )
        )
        processing = self._latest_completed_processing(batch)
        if processing is not None:
            nodes.append(
                TraceabilityNode(
                    kind="PROCESSING",
                    label="Processing run",
                    identifier=processing.processing_code,
                    detail=(
                        f"{_label(processing.processing_type)}: {processing.input_quantity} → "
                        f"{processing.output_quantity} {_label(processing.unit)}"
                    ),
                    recorded_at=processing.completion_time or processing.created_at,
                    href=f"/api/v1/processing/{processing.id}",
                )
            )
        collection = batch.collection
        if collection is not None:
            nodes.append(
                TraceabilityNode(
                    kind="COLLECTION",
                    label="Honey collection",
                    identifier=getattr(collection, "collection_code", str(batch.collection_id)),
                    detail=(
                        f"Harvest of {collection.total_quantity} {_label(collection.unit)} "
                        f"on {collection.collection_date}"
                    ),
                    recorded_at=collection.collection_date,
                    href=f"/api/v1/collections/{collection.id}",
                )
            )
            for source in getattr(collection, "sources", []) or []:
                hive = getattr(source, "hive", None)
                nodes.append(
                    TraceabilityNode(
                        kind="HIVE",
                        label="Source hive",
                        identifier=getattr(hive, "hive_code", str(getattr(source, "hive_id", "—"))),
                        detail=(
                            f"Contributed {source.quantity} "
                            f"{_label(getattr(collection, 'unit', None))}"
                        ),
                        recorded_at=collection.collection_date,
                        href=f"/api/v1/hives/{getattr(source, 'hive_id', '')}",
                    )
                )
        beekeeper = getattr(batch, "beekeeper", None)
        if beekeeper is not None:
            nodes.append(
                TraceabilityNode(
                    kind="BEEKEEPER",
                    label="Beekeeper",
                    identifier=getattr(beekeeper, "beekeeper_code", str(batch.beekeeper_id)),
                    detail=beekeeper_name(beekeeper),
                    recorded_at=None,
                    href=f"/api/v1/beekeepers/{beekeeper.id}",
                )
            )
        cluster = getattr(batch, "cluster", None)
        if cluster is not None:
            nodes.append(
                TraceabilityNode(
                    kind="CLUSTER",
                    label="KVIC cluster",
                    identifier=getattr(cluster, "cluster_code", str(batch.cluster_id)),
                    detail=cluster_name(cluster),
                    recorded_at=None,
                    href=f"/api/v1/clusters/{cluster.id}",
                )
            )
        return nodes

    # -- small helpers ---------------------------------------------------
    @staticmethod
    def _latest_completed_processing(batch: HoneyBatch):
        runs = [
            run
            for run in (getattr(batch, "processing_records", []) or [])
            if run.status.value == "COMPLETED"
        ]
        return runs[-1] if runs else None

    @staticmethod
    def _latest_decided_test(batch: HoneyBatch):
        tests = list(getattr(batch, "lab_tests", []) or [])
        decided = [
            test
            for test in tests
            if getattr(test.overall_result, "value", None) in ("PASS", "FAIL")
        ]
        ordered = sorted(decided, key=lambda test: (int(test.round_number or 0), test.created_at))
        return ordered[-1] if ordered else None

    def _package_shipment_totals(self, package: HoneyPackage) -> tuple[Decimal, Decimal]:
        """How much of this package shipments account for, and what is left."""
        shipments = self._shipments_for(package)
        moved = sum(
            (
                shipment.quantity
                for shipment in shipments
                if shipment.status is not DistributionStatus.CANCELLED
            ),
            Decimal("0"),
        )
        remaining = package.quantity - moved
        return moved, remaining if remaining > 0 else Decimal("0")

    def _shipments_for(self, package: HoneyPackage):
        return self.distributions.for_package(package.id)

    @staticmethod
    def _next_step(run: PackagingRun) -> str | None:
        if run.status is PackagingStatus.PENDING:
            return "Start the run when packing actually begins, then record what was filled."
        if run.status is PackagingStatus.IN_PROGRESS:
            return (
                "Record the packaged quantity, the package size and how many packages were filled, "
                "then complete the run to create them."
            )
        if run.status is PackagingStatus.COMPLETED:
            remaining = len([p for p in (run.packages or []) if p.status is PackageStatus.CREATED])
            if remaining:
                return f"{remaining} package(s) are still unreleased — release them for distribution."
            return "Every package is released; a distributor can raise shipments against them."
        return None
