"""Durable, idempotent Fabric traceability integration.

Workflow services call named ``queue_*`` methods *before their own database
commit*.  That writes the outbox row atomically with the operational transition.
They call ``submit_after_commit`` only after the operational commit succeeds.
If Fabric is unavailable, the operational fact remains committed and the row is
truthfully PENDING/FAILED for the retry worker or an administrator to submit.
"""

from __future__ import annotations

import hashlib
import json
import logging
import secrets
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from app.core.config import Settings, get_settings
from app.models.blockchain import BlockchainStatus, BlockchainTransaction, PackageQrCode
from app.repositories.blockchain_repository import BlockchainTransactionRepository, PackageQrCodeRepository
from app.services.blockchain_client import BlockchainClient, BlockchainClientError

logger = logging.getLogger("honeychain.blockchain")


class BlockchainEventType:
    COLLECTION_COMPLETED = "COLLECTION_COMPLETED"
    BATCH_CREATED = "BATCH_CREATED"
    PROCESSING_STARTED = "PROCESSING_STARTED"
    PROCESSING_COMPLETED = "PROCESSING_COMPLETED"
    LAB_TEST_STARTED = "LAB_TEST_STARTED"
    QUALITY_CHECKED = "QUALITY_CHECKED"
    QUALITY_FAILED = "QUALITY_FAILED"
    QUALITY_HOLD = "QUALITY_HOLD"
    PROCEEDED_WITH_RISK = "PROCEEDED_WITH_RISK"
    PACKAGING_STARTED = "PACKAGING_STARTED"
    PACKAGE_CREATED = "PACKAGE_CREATED"
    PACKAGED = "PACKAGED"
    DISTRIBUTION_CREATED = "DISTRIBUTION_CREATED"
    DISTRIBUTION_DISPATCHED = "DISTRIBUTION_DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RETAILER_RECEIVED = "RETAILER_RECEIVED"
    QR_GENERATED = "QR_GENERATED"
    CUSTOMER_QR_VERIFIED = "CUSTOMER_QR_VERIFIED"


# --------------------------------------------------------------------------- #
# Serialization and narrow payload helpers
# --------------------------------------------------------------------------- #
def _value(value: Any) -> Any:
    """Make an allow-listed payload canonical JSON without leaking ORM objects."""
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, list):
        return [_value(item) for item in value]
    if isinstance(value, tuple):
        return [_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _value(item) for key, item in value.items() if item is not None}
    return str(value)


def _payload_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(_value(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _actor_id(actor) -> str | None:
    return str(actor.id) if getattr(actor, "id", None) else None


def _location(cluster) -> str | None:
    if not cluster:
        return None
    return ", ".join(part for part in (getattr(cluster, "district", None), getattr(cluster, "state", None)) if part) or None


def _processing_type(run) -> str | None:
    kind = _value(getattr(run, "processing_type", None))
    return getattr(run, "processing_type_other", None) if kind == "OTHER" else kind


class BlockchainService:
    """Owns the local outbox, real Fabric client and traceability ledger reads."""

    def __init__(
        self,
        session,
        *,
        settings: Settings | None = None,
        client: BlockchainClient | None = None,
    ) -> None:  # noqa: ANN001
        self.session = session
        self.settings = settings or get_settings()
        self.events = BlockchainTransactionRepository(session)
        self.qr_codes = PackageQrCodeRepository(session)
        self._client_supplied = client is not None
        self.client = client or BlockchainClient(self.settings)
        # Existing test suites exercise hundreds of operational writes. They still
        # receive durable pending events, but no cloud call is made unless a test
        # injects a real/mock client explicitly.
        self._submission_enabled = self.settings.blockchain_configured and (
            not self.settings.is_testing or client is not None
        )

    # ------------------------------------------------------------------ #
    # Outbox core
    # ------------------------------------------------------------------ #
    def queue_event(
        self,
        *,
        event_id: str,
        tx_type: str,
        batch_code: str,
        payload: dict[str, Any],
        collection_id: uuid.UUID | None = None,
        processing_id: uuid.UUID | None = None,
        lab_test_id: uuid.UUID | None = None,
        packaging_id: uuid.UUID | None = None,
        package_id: uuid.UUID | None = None,
        distribution_id: uuid.UUID | None = None,
    ) -> BlockchainTransaction:
        """Persist one logical event if it does not already exist.

        Unique ``event_id`` provides the second line of defence under concurrent
        double submits.  A conflict is read back by callers after rollback in the
        normal request transaction, while the common/retry path simply reuses the
        existing row.
        """
        existing = self.events.by_event_id(event_id)
        if existing is not None:
            return existing
        clean = _value(payload)
        assert isinstance(clean, dict)
        clean["event_id"] = event_id
        integrity_hash = _payload_hash(clean)
        clean["integrity_hash"] = integrity_hash
        # Savepoint + explicit flush makes a unique-key race recoverable without
        # rolling back the enclosing workflow transaction (collection/lab/etc.).
        # The losing request reads the winning logical event and continues with
        # the existing business fact instead of attempting a second Fabric POST.
        from sqlalchemy.exc import IntegrityError

        try:
            with self.session.begin_nested():
                record = self.events.create(
                    event_id=event_id,
                    tx_type=tx_type,
                    batch_code=batch_code,
                    payload=clean,
                    payload_sha256=integrity_hash,
                    status=BlockchainStatus.PENDING,
                    collection_id=collection_id,
                    processing_id=processing_id,
                    lab_test_id=lab_test_id,
                    packaging_id=packaging_id,
                    package_id=package_id,
                    distribution_id=distribution_id,
                )
                self.session.flush()
        except IntegrityError:
            record = self.events.by_event_id(event_id)
            if record is None:  # pragma: no cover - an unrelated integrity error
                raise
            return record
        logger.info("Blockchain outbox event queued", extra={"event_id": event_id, "tx_type": tx_type, "batch": batch_code})
        return record

    def submit_after_commit(self, *event_ids: str) -> None:
        """Best-effort submit after the operational transaction committed.

        This method never lets Fabric availability roll back a completed harvest,
        test, package or shipment.  It persists the real error for retry.
        """
        for event_id in event_ids:
            try:
                self.submit(event_id)
            except Exception:  # pragma: no cover - submit itself saves failure
                logger.exception("Unexpected blockchain submission error", extra={"event_id": event_id})

    def submit(self, event_id: str) -> BlockchainTransaction | None:
        record = self.events.by_event_id(event_id)
        if record is None:
            return None
        if record.status == BlockchainStatus.CONFIRMED:
            return record
        if not self._submission_enabled:
            # Disabled is a real local condition, not a fabricated confirmation.
            record.status = BlockchainStatus.PENDING
            record.last_error = "Blockchain submission is disabled for this environment"
            self.session.commit()
            return record

        # A request may have reached Fabric just before a timeout.  Reconcile
        # first using our backend-owned event id in the payload before POSTing.
        try:
            for remote in self.client.get_transactions():
                payload = remote.get("payload") or {}
                if isinstance(payload, dict) and payload.get("event_id") == record.event_id:
                    self._confirm(record, str(remote["tx_id"]))
                    return record
        except BlockchainClientError as exc:
            logger.warning("Could not reconcile blockchain event before submit", extra={"event_id": event_id, "error": str(exc)[:180]})
            if record.attempt_count:
                # A previous POST may have reached Fabric before the connection
                # failed. Re-posting blindly while GET is unavailable would turn
                # one logical event into two immutable ledger rows. Keep this
                # durable event FAILED and let the next successful GET reconcile
                # it (or prove it absent) before another POST is attempted.
                record.status = BlockchainStatus.FAILED
                record.last_error = (
                    "Fabric reconciliation is unavailable after a prior submission; "
                    "the event was not re-posted to prevent a duplicate: " + str(exc)
                )[:2000]
                self.session.commit()
                return record

        record.status = BlockchainStatus.SUBMITTED
        record.submitted_at = datetime.now(timezone.utc)
        record.attempt_count += 1
        self.session.commit()
        try:
            response = self.client.create_transaction(
                tx_type=record.tx_type,
                batch_id=record.batch_code,
                payload=record.payload,
            )
            self._confirm(record, str(response["tx_id"]))
        except BlockchainClientError as exc:
            record.status = BlockchainStatus.FAILED
            record.last_error = str(exc)[:2000]
            self.session.commit()
            logger.warning(
                "Blockchain transaction remains retryable",
                extra={"event_id": record.event_id, "tx_type": record.tx_type, "error": record.last_error},
            )
        return record

    def _confirm(self, record: BlockchainTransaction, tx_id: str) -> None:
        # A tx id can only belong to one local event. If Fabric somehow returns an
        # existing other reference we keep the row retryable rather than lying.
        conflict = self.events.by_tx_id(tx_id)
        if conflict is not None and conflict.event_id != record.event_id:
            record.status = BlockchainStatus.FAILED
            record.last_error = "Blockchain service returned a tx_id already linked to a different event"
            self.session.commit()
            return
        record.tx_id = tx_id
        record.status = BlockchainStatus.CONFIRMED
        record.last_error = None
        record.confirmed_at = datetime.now(timezone.utc)
        self.session.commit()
        logger.info("Blockchain transaction confirmed", extra={"event_id": record.event_id, "tx_id": tx_id, "tx_type": record.tx_type})

    def retry_pending(self, *, limit: int = 100) -> list[BlockchainTransaction]:
        for record in self.events.retryable(limit=limit):
            self.submit(record.event_id)
        return self.events.retryable(limit=limit)

    # ------------------------------------------------------------------ #
    # Named workflow events — payloads are narrow and use only real records
    # ------------------------------------------------------------------ #
    def queue_collection_completed(self, collection, batch, actor) -> BlockchainTransaction:
        return self.queue_event(
            event_id=f"COL-{collection.collection_code}-COMPLETED",
            tx_type=BlockchainEventType.COLLECTION_COMPLETED,
            batch_code=batch.batch_code,
            collection_id=collection.id,
            payload={
                "collection_id": collection.collection_code,
                "batch_id": batch.batch_code,
                "cluster_id": getattr(getattr(collection, "cluster", None), "cluster_code", None),
                "beekeeper_id": getattr(getattr(collection, "beekeeper", None), "beekeeper_code", None),
                "hive_ids": [source.hive_code for source in collection.sources],
                "quantity_kg": collection.total_quantity if _value(collection.unit) == "KG" else None,
                "quantity": collection.total_quantity,
                "unit": collection.unit,
                "status": "COLLECTED",
                "actor_id": _actor_id(actor),
            },
        )

    def queue_batch_created(self, collection, batch, actor) -> BlockchainTransaction:
        return self.queue_event(
            event_id=f"BATCH-{batch.batch_code}-CREATED",
            tx_type=BlockchainEventType.BATCH_CREATED,
            batch_code=batch.batch_code,
            collection_id=collection.id,
            payload={
                "batch_id": batch.batch_code,
                "cluster_id": getattr(getattr(batch, "cluster", None), "cluster_code", None),
                "beekeeper_id": getattr(getattr(batch, "beekeeper", None), "beekeeper_code", None),
                "collection_id": collection.collection_code,
                "source_hives": [source.hive_code for source in collection.sources],
                # Honey type is not modelled anywhere yet; it is deliberately not invented.
                "quantity_kg": batch.quantity if _value(batch.unit) == "KG" else None,
                "quantity": batch.quantity,
                "unit": batch.unit,
                "collection_date": batch.collection_date,
                "location": _location(getattr(batch, "cluster", None)),
                "actor_id": _actor_id(actor),
            },
        )

    def queue_processing_started(self, run, batch, actor) -> BlockchainTransaction:
        return self.queue_event(
            event_id=f"PROC-{run.processing_code}-STARTED",
            tx_type=BlockchainEventType.PROCESSING_STARTED,
            batch_code=batch.batch_code,
            processing_id=run.id,
            payload={
                "processing_id": run.processing_code,
                "processor_id": _actor_id(actor),
                "processing_type": _processing_type(run),
                "status": "IN_PROGRESS",
                "started_at": run.start_time,
            },
        )

    def queue_processing_completed(self, run, batch, actor) -> BlockchainTransaction:
        return self.queue_event(
            event_id=f"PROC-{run.processing_code}-COMPLETED",
            tx_type=BlockchainEventType.PROCESSING_COMPLETED,
            batch_code=batch.batch_code,
            processing_id=run.id,
            payload={
                "processing_id": run.processing_code,
                "processor_id": _actor_id(actor),
                "processing_type": _processing_type(run),
                "input_quantity_kg": run.input_quantity if _value(run.unit) == "KG" else None,
                "output_quantity_kg": run.output_quantity if _value(run.unit) == "KG" else None,
                "input_quantity": run.input_quantity,
                "output_quantity": run.output_quantity,
                "unit": run.unit,
                "status": "COMPLETED",
                "completed_at": run.completion_time,
            },
        )

    def queue_lab_started(self, test, batch, actor) -> BlockchainTransaction:
        return self.queue_event(
            event_id=f"LAB-{test.test_code}-STARTED",
            tx_type=BlockchainEventType.LAB_TEST_STARTED,
            batch_code=batch.batch_code,
            processing_id=test.processing_id,
            lab_test_id=test.id,
            payload={
                "lab_test_id": test.test_code,
                "sample_id": test.sample_code,
                "laboratory_id": getattr(getattr(test, "laboratory", None), "laboratory_code", None),
                "tested_by": _actor_id(actor),
                "status": "STARTED",
                "test_date": test.test_date,
            },
        )

    def queue_quality_result(self, test, batch, actor, results: list | None = None) -> BlockchainTransaction:
        result = _value(test.overall_result)
        tx_type = {
            "PASS": BlockchainEventType.QUALITY_CHECKED,
            "FAIL": BlockchainEventType.QUALITY_FAILED,
            "INCONCLUSIVE": BlockchainEventType.QUALITY_HOLD,
        }.get(result)
        if tx_type is None:
            raise ValueError(f"No blockchain event exists for laboratory result {result!r}")
        suffix = {BlockchainEventType.QUALITY_CHECKED: "QUALITY-CHECKED", BlockchainEventType.QUALITY_FAILED: "QUALITY-FAILED", BlockchainEventType.QUALITY_HOLD: "QUALITY-HOLD"}[tx_type]
        summary: dict[str, str] = {}
        for row in (results or [])[:5]:
            # Summary/reference only — full laboratory measurements stay in DB.
            key = str(getattr(row, "parameter_code", "measurement")).lower()
            summary[key] = f"{_value(getattr(row, 'value', None))} {_value(getattr(row, 'unit', None))}".strip()
        payload: dict[str, Any] = {
            "lab_test_id": test.test_code,
            "tested_by": _actor_id(actor),
            "result": result,
            "status": "PASSED" if result == "PASS" else ("REJECTED" if result == "FAIL" else "HOLD"),
            "measurement_summary": summary or None,
        }
        if result == "INCONCLUSIVE":
            payload["reason"] = test.result_summary or "Quality review required"
        return self.queue_event(
            event_id=f"LAB-{test.test_code}-{suffix}",
            tx_type=tx_type,
            batch_code=batch.batch_code,
            processing_id=test.processing_id,
            lab_test_id=test.id,
            payload=payload,
        )

    def queue_proceeded_with_risk(self, test, batch, actor, previous_result: str, reason: str) -> BlockchainTransaction:
        return self.queue_event(
            event_id=f"LAB-{test.test_code}-PROCEEDED-WITH-RISK",
            tx_type=BlockchainEventType.PROCEEDED_WITH_RISK,
            batch_code=batch.batch_code,
            processing_id=test.processing_id,
            lab_test_id=test.id,
            payload={
                "lab_test_id": test.test_code,
                "previous_result": previous_result,
                "override_status": "APPROVED_WITH_RISK",
                "approved_by": _actor_id(actor),
                "reason": reason,
            },
        )

    def queue_packaging_started(self, run, batch, actor) -> BlockchainTransaction:
        return self.queue_event(
            event_id=f"PKG-{run.packaging_code}-STARTED",
            tx_type=BlockchainEventType.PACKAGING_STARTED,
            batch_code=batch.batch_code,
            packaging_id=run.id,
            payload={
                "packaging_id": run.packaging_code,
                "packaging_unit_id": getattr(getattr(run, "unit_ref", None), "unit_code", None),
                "started_by": _actor_id(actor),
                "status": "IN_PROGRESS",
                "started_at": run.start_time,
            },
        )

    def queue_package_created(self, package, run, batch, actor) -> BlockchainTransaction:
        return self.queue_event(
            event_id=f"PACKAGE-{package.package_code}-CREATED",
            tx_type=BlockchainEventType.PACKAGE_CREATED,
            batch_code=batch.batch_code,
            packaging_id=run.id,
            package_id=package.id,
            payload={
                "package_id": package.package_code,
                "packaging_id": run.packaging_code,
                "package_size": package.package_size,
                "unit": package.unit,
                "status": "CREATED",
                "created_by": _actor_id(actor),
            },
        )

    def queue_packaged(self, run, batch, actor) -> BlockchainTransaction:
        return self.queue_event(
            event_id=f"PKG-{run.packaging_code}-COMPLETED",
            tx_type=BlockchainEventType.PACKAGED,
            batch_code=batch.batch_code,
            packaging_id=run.id,
            payload={
                "packaging_id": run.packaging_code,
                "packaging_unit_id": getattr(getattr(run, "unit_ref", None), "unit_code", None),
                "package_count": run.number_of_packages,
                "package_size": run.package_size,
                "unit": run.unit,
                "total_packaged_quantity_kg": run.packaged_quantity if _value(run.unit) == "KG" else None,
                "total_packaged_quantity": run.packaged_quantity,
                "status": "PACKAGED",
                "completed_by": _actor_id(actor),
            },
        )

    def queue_distribution(self, tx_type: str, suffix: str, shipment, actor) -> BlockchainTransaction:
        return self.queue_event(
            event_id=f"DIST-{shipment.distribution_code}-{suffix}",
            tx_type=tx_type,
            batch_code=shipment.batch.batch_code,
            distribution_id=shipment.id,
            package_id=shipment.package_id,
            payload={
                "distribution_id": shipment.distribution_code,
                "package_id": shipment.package.package_code,
                "distributor_id": str(shipment.distributor_id),
                "retailer_id": str(shipment.retailer_id) if shipment.retailer_id else None,
                "destination": shipment.destination,
                "package_count": 1,
                "quantity": shipment.quantity,
                "unit": shipment.unit,
                "status": "RECEIVED" if tx_type == BlockchainEventType.RETAILER_RECEIVED else _value(shipment.status),
                "actor_id": _actor_id(actor),
            },
        )

    # ------------------------------------------------------------------ #
    # QR resolver and public traceability
    # ------------------------------------------------------------------ #
    def get_or_create_qr(self, package, actor) -> tuple[PackageQrCode, bool, BlockchainTransaction | None]:
        existing = self.qr_codes.for_package(package.id)
        if existing is not None:
            return existing, False, self.events.by_event_id(f"QR-{existing.qr_code}-GENERATED")
        qr = self.qr_codes.create(
            qr_code=f"QR-{package.package_code}",
            public_token=secrets.token_urlsafe(24),
            package_id=package.id,
            generated_by_id=getattr(actor, "id", None),
            status="ACTIVE",
        )
        event = self.queue_event(
            event_id=f"QR-{qr.qr_code}-GENERATED",
            tx_type=BlockchainEventType.QR_GENERATED,
            batch_code=package.batch.batch_code,
            package_id=package.id,
            packaging_id=package.packaging_id,
            payload={"package_id": package.package_code, "qr_id": qr.qr_code, "status": "ACTIVE"},
        )
        return qr, True, event

    # ------------------------------------------------------------------ #
    # Ledger reads, all resolved on the backend
    # ------------------------------------------------------------------ #
    def ledger_transactions(
        self,
        *,
        batch_codes: list[str] | None = None,
        search: str | None = None,
        tx_type: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Read Fabric once, then merge it with relevant local sync state.

        ``batch_codes=None`` is the administrator's raw ledger: legacy Fabric
        records remain visible even when they have no HoneyChain match.  A list is
        used for KVIC/customer scope and removes unrelated records server-side.
        """
        local = self.events.search(batch_codes=batch_codes, search=search, tx_type=tx_type, status=status)
        local_by_tx = {item.tx_id: item for item in local if item.tx_id}
        rows: list[dict[str, Any]] = []
        remote_error: str | None = None
        can_read_remote = self.settings.blockchain_configured and (
            not self.settings.is_testing or self._client_supplied
        )
        if can_read_remote:
            try:
                for remote in self.client.get_transactions():
                    if batch_codes is not None and remote.get("batch_id") not in batch_codes:
                        continue
                    payload = remote.get("payload") or {}
                    text = " ".join(
                        str(value) for value in (remote.get("tx_id"), remote.get("tx_type"), remote.get("batch_id"))
                    )
                    if search and search.strip().lower() not in text.lower():
                        continue
                    if tx_type and remote.get("tx_type") != tx_type:
                        continue
                    linked = local_by_tx.get(remote.get("tx_id"))
                    # A Fabric record is confirmed by its own existence. Status
                    # filters therefore include it only under CONFIRMED, even if
                    # a stale local retry row has not yet been reconciled.
                    if status and status != BlockchainStatus.CONFIRMED:
                        continue
                    rows.append(self.serialize_remote(remote, linked))
            except BlockchainClientError as exc:
                remote_error = str(exc)
        remote_ids = {row.get("tx_id") for row in rows}
        for item in local:
            if item.tx_id not in remote_ids:
                rows.append(self.serialize_event(item))
        rows.sort(key=lambda row: str(row.get("timestamp") or ""), reverse=True)
        return rows, remote_error

    def batch_transactions(self, batch_code: str) -> list[dict[str, Any]]:
        """Relevant real-ledger and local-sync records for one known batch."""
        rows, _error = self.ledger_transactions(batch_codes=[batch_code])
        return rows

    def public_traceability(self, public_token: str) -> dict[str, Any] | None:
        """Resolve one QR token into a deliberately customer-safe traceability view."""
        qr = self.qr_codes.by_token(public_token)
        if qr is None or qr.status != "ACTIVE":
            return None
        package = qr.package
        batch = package.batch
        collection = batch.collection
        source_rows = list(collection.sources or [])
        processing_rows = list(batch.processing_records or [])
        completed_processing = [row for row in processing_rows if _value(getattr(row, "status", None)) == "COMPLETED"]
        processing = max(completed_processing, key=lambda row: row.created_at) if completed_processing else None
        tests = list(batch.lab_tests or [])
        lab = max(tests, key=lambda row: row.created_at) if tests else None
        shipments = [row for row in getattr(package, "distributions", [])] if hasattr(package, "distributions") else []
        # Distribution has no back-populated relationship, so query through the
        # existing repository only when it is needed by a real QR scan.
        if not shipments:
            from app.repositories.distribution_repository import DistributionRepository
            shipments = DistributionRepository(self.session).for_package(package.id)

        measurement_summary: list[dict[str, Any]] = []
        if lab is not None:
            for result in list(getattr(lab, "results", []) or [])[:5]:
                measurement_summary.append({
                    "name": result.parameter_name,
                    "value": _value(result.value),
                    "unit": _value(result.unit),
                    "status": _value(result.status),
                })
        ledger = self.batch_transactions(batch.batch_code)
        customer_ledger = [
            {
                "tx_id": entry.get("tx_id"),
                "type": entry.get("tx_type"),
                "timestamp": entry.get("timestamp"),
                "status": entry.get("blockchain_status"),
            }
            for entry in ledger
        ]
        return {
            "product": {
                # Honey type is not currently an operational field and therefore
                # must remain absent rather than being guessed from a package.
                "batch_id": batch.batch_code,
                "package_id": package.package_code,
                "package_size": _value(package.package_size),
                "unit": _value(package.unit),
                "packaging_type": _value(package.packaging_type),
            },
            "source": {
                "cluster": getattr(getattr(batch, "cluster", None), "cluster_name", None),
                "cluster_id": getattr(getattr(batch, "cluster", None), "cluster_code", None),
                "beekeeper_id": getattr(getattr(batch, "beekeeper", None), "beekeeper_code", None),
                "hives": [row.hive_code for row in source_rows],
                "collection_date": _value(collection.collection_date),
                "actual_collected_quantity": _value(collection.total_quantity),
                "unit": _value(collection.unit),
            },
            "processing": None if processing is None else {
                "type": _processing_type(processing),
                "facility": getattr(getattr(processing, "unit_ref", None), "name", None),
                "completed_at": _value(processing.completion_time),
                "output_quantity": _value(processing.output_quantity),
                "unit": _value(processing.unit),
            },
            "laboratory": None if lab is None else {
                "status": _value(lab.status),
                "result": _value(lab.overall_result),
                "summary": lab.result_summary,
                "measurements": measurement_summary,
            },
            "packaging": {
                "packaging_id": getattr(getattr(package, "packaging", None), "packaging_code", None),
                "packaging_unit": getattr(getattr(getattr(package, "packaging", None), "unit_ref", None), "name", None),
                "package_size": _value(package.package_size),
                "unit": _value(package.unit),
                "package_identity": package.package_code,
                "packaged_at": _value(getattr(getattr(package, "packaging", None), "completion_time", None)),
            },
            "distribution": [
                {
                    "status": _value(shipment.status),
                    "dispatched_at": _value(shipment.dispatched_at),
                    "in_transit_at": _value(shipment.in_transit_at),
                    "delivered_at": _value(shipment.delivered_at),
                    "retailer_received_at": _value(shipment.received_at),
                    "retailer": getattr(getattr(shipment, "retailer", None), "name", None),
                }
                for shipment in shipments
            ],
            "blockchain": {
                "transactions": customer_ledger,
                # No submitted event is not the same thing as a synchronised
                # ledger. Avoid displaying a fabricated confirmation for an
                # incomplete/outage-affected batch.
                "synchronized": bool(customer_ledger)
                and all(entry.get("status") == BlockchainStatus.CONFIRMED for entry in customer_ledger),
            }
        }

    def health(self) -> dict[str, Any]:
        """Actual synchronization health; no synthetic service status."""
        info = self.events.health()
        if not self.settings.blockchain_configured:
            return {"service": "disabled", "connected": False, **info}
        if self.settings.is_testing:
            return {"service": "not_checked_in_test", "connected": None, **info}
        try:
            self.client.get_transactions()
            return {"service": "connected", "connected": True, **info}
        except BlockchainClientError as exc:
            return {"service": "unavailable", "connected": False, "last_error": str(exc), **info}

    def serialize_event(self, item: BlockchainTransaction) -> dict[str, Any]:
        return {
            "event_id": item.event_id,
            "tx_id": item.tx_id,
            "tx_type": item.tx_type,
            "batch_id": item.batch_code,
            "payload": item.payload,
            "timestamp": item.confirmed_at or item.submitted_at or item.created_at,
            "blockchain_status": item.status,
            "attempt_count": item.attempt_count,
            "last_error": item.last_error,
            "linked_record": self._linked_record(item),
            "source": "HONEYCHAIN_OUTBOX",
        }

    def serialize_remote(self, remote: dict[str, Any], linked: BlockchainTransaction | None = None) -> dict[str, Any]:
        base = {
            "event_id": linked.event_id if linked else (remote.get("payload") or {}).get("event_id"),
            "tx_id": remote.get("tx_id"),
            "tx_type": remote.get("tx_type"),
            "batch_id": remote.get("batch_id"),
            "payload": remote.get("payload") or {},
            "timestamp": remote.get("timestamp"),
            "blockchain_status": linked.status if linked else BlockchainStatus.CONFIRMED,
            "attempt_count": linked.attempt_count if linked else None,
            "last_error": linked.last_error if linked else None,
            "linked_record": self._linked_record(linked) if linked else None,
            "source": "FABRIC_LEDGER",
        }
        return base

    @staticmethod
    def _linked_record(item: BlockchainTransaction | None) -> dict[str, str] | None:
        if item is None:
            return None
        for label, value in (
            ("collection_id", item.collection_id),
            ("processing_id", item.processing_id),
            ("lab_test_id", item.lab_test_id),
            ("packaging_id", item.packaging_id),
            ("package_id", item.package_id),
            ("distribution_id", item.distribution_id),
        ):
            if value:
                return {"type": label.removesuffix("_id"), "id": str(value)}
        return {"type": "batch", "id": item.batch_code}


__all__ = ["BlockchainEventType", "BlockchainService"]
