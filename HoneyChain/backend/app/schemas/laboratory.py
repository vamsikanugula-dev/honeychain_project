"""Request and response models for laboratories, parameters, tests and results.

The shape of these models is the phase's safety property. A request may name a
batch, choose a laboratory, state a sample quantity and record measured values.
It may **not** state an overall result, a parameter status, a test code or a
sample code: those are computed or issued by the platform. ``extra="forbid"``
turns an attempt into a 422 instead of a field that is quietly dropped.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    AssignmentStatus,
    CollectionUnit,
    FacilityStatus,
    LabMeasureUnit,
    LabParameterStatus,
    LabResult,
    LabTestStatus,
)

from app.schemas.processing import EligibleProcessor

MAX_SAMPLE_QUANTITY = Decimal("1000")
#: A measured value is bounded only to catch a typo; the units differ per
#: parameter, so no scientific limit is implied.
MAX_MEASURED_VALUE = Decimal("1000000")
MIN_MEASURED_VALUE = Decimal("-1000000")


# --------------------------------------------------------------------------- #
# Laboratories
# --------------------------------------------------------------------------- #
class LaboratoryCreate(BaseModel):
    """``POST /api/v1/laboratories``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=2, max_length=160)
    registration_identifier: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=200)
    district: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=20)
    accredited: bool | None = Field(
        default=None,
        description=(
            "As stated by the facility. The platform does not verify accreditation and "
            "never claims it on the facility's behalf."
        ),
    )
    notes: str | None = Field(default=None, max_length=2000)


class LaboratoryUpdate(BaseModel):
    """``PATCH /api/v1/laboratories/{id}``."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=160)
    registration_identifier: str | None = Field(default=None, max_length=80)
    location: str | None = Field(default=None, max_length=200)
    district: str | None = Field(default=None, max_length=80)
    state: str | None = Field(default=None, max_length=80)
    contact_email: str | None = Field(default=None, max_length=255)
    contact_phone: str | None = Field(default=None, max_length=20)
    accredited: bool | None = None
    status: FacilityStatus | None = None
    notes: str | None = Field(default=None, max_length=2000)


class LaboratoryRead(BaseModel):
    id: uuid.UUID
    laboratory_code: str
    name: str
    registration_identifier: str | None = None
    location: str | None = None
    district: str | None = None
    state: str | None = None
    contact_email: str | None = None
    contact_phone: str | None = None
    accredited: bool | None = Field(
        default=None,
        description="NULL when the facility did not state it. Recorded, never verified.",
    )
    status: FacilityStatus
    status_label: str
    is_demo: bool = False
    notes: str | None = None
    test_count: int = 0
    created_at: datetime
    updated_at: datetime


# --------------------------------------------------------------------------- #
# Parameter catalogue and configuration
# --------------------------------------------------------------------------- #
class LabParameterRead(BaseModel):
    """One measurement slot, with whatever range is configured for it.

    ``is_configured`` false means exactly what it says: results for this parameter
    are recorded and reported as ``NOT_EVALUATED`` until a range is entered.
    """

    id: uuid.UUID
    code: str
    name: str
    unit: LabMeasureUnit
    unit_label: str
    description: str | None = None
    is_required: bool = False
    is_active: bool = True
    display_order: int = 100
    reference_min: Decimal | None = None
    reference_max: Decimal | None = None
    reference_source: str | None = Field(
        default=None,
        description="Where the configured range came from, as entered by an administrator.",
    )
    reference_updated_at: datetime | None = None
    is_configured: bool = False
    configured_by: str | None = None


class LabParameterUpdate(BaseModel):
    """``PATCH /api/v1/lab-parameters/{code}`` — configuration, not measurement.

    Configuring a range requires saying where it came from: the platform quotes
    that source to readers and vouches for nothing itself. Clearing both bounds
    returns the parameter to "recorded, not evaluated".
    """

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=2, max_length=80)
    description: str | None = Field(default=None, max_length=400)
    is_required: bool | None = None
    is_active: bool | None = None
    display_order: int | None = Field(default=None, ge=0, le=1000)
    reference_min: Decimal | None = None
    reference_max: Decimal | None = None
    reference_source: str | None = Field(default=None, max_length=300)

    @model_validator(mode="after")
    def _range_is_ordered_and_sourced(self) -> "LabParameterUpdate":
        if (
            self.reference_min is not None
            and self.reference_max is not None
            and self.reference_min > self.reference_max
        ):
            raise ValueError("The lower bound of a reference range cannot exceed the upper bound")
        setting_range = self.reference_min is not None or self.reference_max is not None
        if setting_range and not (self.reference_source or "").strip():
            raise ValueError(
                "A reference range must state where it came from (reference_source): the "
                "platform records the source and does not vouch for the limit itself."
            )
        return self


# --------------------------------------------------------------------------- #
# Laboratory tests
# --------------------------------------------------------------------------- #
class LabTestCreate(BaseModel):
    """``POST /api/v1/lab-tests`` — open a test and record its sample."""

    model_config = ConfigDict(extra="forbid")

    batch_id: uuid.UUID
    laboratory_id: uuid.UUID
    sample_quantity: Decimal = Field(gt=0, le=MAX_SAMPLE_QUANTITY)
    sample_unit: CollectionUnit = CollectionUnit.GRAM
    sample_collected_at: datetime | None = None
    sample_notes: str | None = Field(default=None, max_length=500)
    test_date: date | None = None
    remarks: str | None = Field(default=None, max_length=2000)
    retest_reason: str | None = Field(
        default=None,
        max_length=500,
        description=(
            "Required when the batch has already been decided (APPROVED or REJECTED) and "
            "this test is a retest. A retest returns the batch to LAB_TESTING."
        ),
    )

    @field_validator("test_date")
    @classmethod
    def _not_in_the_future(cls, value: date | None) -> date | None:
        if value is not None and value > date.today():
            raise ValueError("A test date cannot be in the future")
        return value


class LabTestUpdate(BaseModel):
    """``PATCH /api/v1/lab-tests/{id}`` — sample details and remarks, while open."""

    model_config = ConfigDict(extra="forbid")

    sample_quantity: Decimal | None = Field(default=None, gt=0, le=MAX_SAMPLE_QUANTITY)
    sample_unit: CollectionUnit | None = None
    sample_collected_at: datetime | None = None
    sample_notes: str | None = Field(default=None, max_length=500)
    test_date: date | None = None
    remarks: str | None = Field(default=None, max_length=2000)


class LabResultCreate(BaseModel):
    """``POST /api/v1/lab-tests/{id}/results`` — one measured parameter.

    ``status`` is absent on purpose: whether a measurement is acceptable is
    computed from the configuration, never asserted by the caller.
    """

    model_config = ConfigDict(extra="forbid")

    parameter_code: str = Field(min_length=2, max_length=40)
    value: Decimal = Field(ge=MIN_MEASURED_VALUE, le=MAX_MEASURED_VALUE)
    unit: LabMeasureUnit | None = Field(
        default=None,
        description="Defaults to the catalogue unit for this parameter; must match it if given.",
    )
    parameter_name: str | None = Field(
        default=None,
        max_length=120,
        description="Required for OTHER: the name of the measurement being recorded.",
    )
    method: str | None = Field(default=None, max_length=120)
    remarks: str | None = Field(default=None, max_length=500)
    measured_at: datetime | None = None


class LabResultUpdate(BaseModel):
    """``PATCH /api/v1/lab-tests/{id}/results/{result_id}`` — a correction while open."""

    model_config = ConfigDict(extra="forbid")

    value: Decimal | None = Field(default=None, ge=MIN_MEASURED_VALUE, le=MAX_MEASURED_VALUE)
    unit: LabMeasureUnit | None = None
    parameter_name: str | None = Field(default=None, max_length=120)
    method: str | None = Field(default=None, max_length=120)
    remarks: str | None = Field(default=None, max_length=500)
    measured_at: datetime | None = None
    correction_reason: str | None = Field(
        default=None,
        max_length=500,
        description="Recorded in the audit entry when an already-recorded value is changed.",
    )


class LabResultRead(BaseModel):
    id: uuid.UUID
    parameter_code: str
    parameter_name: str
    value: Decimal
    unit: LabMeasureUnit
    unit_label: str
    status: LabParameterStatus
    status_label: str
    evaluated: bool = Field(
        default=False,
        description="False when no reference range is configured, so nothing was compared.",
    )
    reference_min: Decimal | None = None
    reference_max: Decimal | None = None
    reference_source: str | None = None
    method: str | None = None
    remarks: str | None = None
    measured_at: datetime | None = None
    recorded_by_id: uuid.UUID | None = None
    recorded_by_name: str | None = None
    created_at: datetime
    updated_at: datetime


class LabTestComplete(BaseModel):
    """``POST /api/v1/lab-tests/{id}/complete`` — evaluate and decide.

    Carries no result: the outcome is computed from what was recorded. ``remarks``
    is the technician's own note, kept beside the derived summary rather than
    replacing it.
    """

    model_config = ConfigDict(extra="forbid")

    remarks: str | None = Field(default=None, max_length=2000)


class LabTestOverride(BaseModel):
    """``POST /api/v1/lab-tests/{id}/override`` — an authorised, audited exception.

    Only an administrator may use this, only with a reason, and the test is marked
    as overridden for every reader afterwards. It exists so that a real-world
    decision that the configured rules cannot express has somewhere honest to
    live, instead of someone editing a measurement to get the answer they want.
    """

    model_config = ConfigDict(extra="forbid")

    overall_result: LabResult = Field(description="PASS, FAIL or INCONCLUSIVE.")
    reason: str = Field(min_length=10, max_length=500)

    @field_validator("overall_result")
    @classmethod
    def _must_be_a_result(cls, value: LabResult) -> LabResult:
        if value is LabResult.PENDING:
            raise ValueError("An override must state PASS, FAIL or INCONCLUSIVE")
        return value


#: A person laboratory work may be allocated to. The shape is shared with
#: processing rather than duplicated: one description of "someone work can be
#: given to", so a dropdown cannot drift from the other one.
EligibleTechnician = EligibleProcessor


class LabTestAssign(BaseModel):
    """Allocate an open test to a named laboratory technician."""

    model_config = ConfigDict(extra="forbid")

    technician_id: uuid.UUID
    test_id: uuid.UUID | None = Field(
        default=None,
        description=(
            "Optional existing test to allocate. Omit it and a test is opened for "
            "the batch, which is what an administrator allocating from the "
            "laboratory queue does."
        ),
    )
    remarks: str | None = Field(default=None, max_length=500)


class LabTestBatchAssign(BaseModel):
    """Allocate a batch's laboratory work — opening the test if needed."""

    model_config = ConfigDict(extra="forbid")

    technician_id: uuid.UUID
    remarks: str | None = Field(default=None, max_length=500)


class LabTestBatchRef(BaseModel):
    id: uuid.UUID
    batch_code: str
    status: str
    status_label: str
    quantity: Decimal
    unit: str
    unit_label: str
    collection_id: uuid.UUID
    collection_code: str | None = None
    collection_date: date
    beekeeper_id: uuid.UUID | None = None
    beekeeper_code: str | None = None
    beekeeper_name: str | None = None
    cluster_id: uuid.UUID | None = None
    cluster_code: str | None = None
    cluster_name: str | None = None


class LabTestProcessingRef(BaseModel):
    """The run that produced the honey being tested."""

    id: uuid.UUID
    processing_code: str
    status: str
    status_label: str
    processing_type: str
    processing_type_label: str
    input_quantity: Decimal | None = None
    output_quantity: Decimal | None = None
    loss_quantity: Decimal | None = None
    unit: str
    unit_label: str
    processing_date: date
    completion_time: datetime | None = None
    operator_name: str | None = None
    processing_unit_name: str | None = None


class TraceabilityNode(BaseModel):
    """One step of the sample's chain back to the apiary."""

    kind: str
    label: str
    identifier: str
    detail: str | None = None
    recorded_at: datetime | None = None
    href: str | None = Field(
        default=None,
        description="Relative API path for the record, so a client can follow the chain.",
    )


class LabTestListItem(BaseModel):
    id: uuid.UUID
    test_code: str
    sample_code: str
    status: LabTestStatus
    status_label: str
    overall_result: LabResult
    overall_result_label: str
    result_summary: str | None = None
    is_override: bool = False
    round_number: int = 1
    retest_of_id: uuid.UUID | None = None
    batch_id: uuid.UUID
    batch_code: str
    collection_code: str | None = None
    processing_id: uuid.UUID
    processing_code: str
    laboratory_id: uuid.UUID
    laboratory_code: str | None = None
    laboratory_name: str | None = None
    technician_id: uuid.UUID | None = None
    technician_name: str | None = None
    #: Who is responsible for the test, and how that came about. Null while the
    #: sample sits unallocated — it stays visible on the pending list either way.
    assigned_technician_id: uuid.UUID | None = None
    assigned_technician_name: str | None = None
    assigned_by_id: uuid.UUID | None = None
    assigned_by_name: str | None = None
    assigned_at: datetime | None = None
    accepted_at: datetime | None = None
    assignment_status: AssignmentStatus = AssignmentStatus.UNASSIGNED
    assignment_status_label: str = "Unassigned"
    sample_quantity: Decimal
    sample_unit: CollectionUnit
    sample_unit_label: str
    test_date: date
    completed_at: datetime | None = None
    cluster_id: uuid.UUID | None = None
    cluster_code: str | None = None
    beekeeper_code: str | None = None
    created_at: datetime
    parameter_count: int = 0
    passed_count: int = 0
    failed_count: int = 0
    unevaluated_count: int = 0
    can_record_results: bool = False
    can_complete: bool = False
    can_override: bool = False
    can_assign: bool = False
    can_accept: bool = False
    can_work: bool = Field(
        default=False,
        description="True when this test is this caller's own assigned work.",
    )


class LabTestDetail(LabTestListItem):
    model_config = ConfigDict(extra="forbid")

    batch: LabTestBatchRef
    processing: LabTestProcessingRef
    results: list[LabResultRead] = Field(default_factory=list)
    required_parameters: list[str] = Field(
        default_factory=list, description="Parameters the platform's policy requires for a decision."
    )
    missing_required_parameters: list[str] = Field(default_factory=list)
    evaluation_notes: list[str] = Field(
        default_factory=list, description="Every reason behind the current result, in words."
    )
    sample_collected_at: datetime | None = None
    sample_notes: str | None = None
    remarks: str | None = None
    override_reason: str | None = None
    decided_by_id: uuid.UUID | None = None
    decided_by_name: str | None = None
    traceability: list[TraceabilityNode] = Field(default_factory=list)
    updated_at: datetime
    next_step: str | None = None


class LabTestSummary(BaseModel):
    total: int = 0
    by_status: dict[str, int] = Field(default_factory=dict)
    by_result: dict[str, int] = Field(default_factory=dict)
    pending: int = 0
    in_progress: int = 0
    completed: int = 0
    passed: int = 0
    failed: int = 0
    inconclusive: int = 0
    overridden: int = 0
    sample_totals: dict[str, float] = Field(default_factory=dict)
    #: Batches waiting at LAB_TESTING in the caller's scope — the laboratory worklist.
    awaiting_testing: int = 0
    #: Parameters with no configured reference range. Not an error: it is the
    #: reason a test can be inconclusive, so it is reported rather than hidden.
    unconfigured_parameters: int = 0
    #: The queue counters the laboratory dashboard shows.
    unassigned: int = 0
    assigned: int = 0
    accepted: int = 0
    #: Tests allocated to the caller and not yet taken on.
    mine: int = 0
    mine_accepted: int = 0
    #: Samples that have an identity (sample code) recorded against them.
    samples_recorded: int = 0


__all__ = [
    "LabTestAssign",
    "LabTestBatchAssign",
    "LabParameterRead",
    "LabParameterUpdate",
    "LabResultCreate",
    "LabResultRead",
    "LabResultUpdate",
    "LabTestBatchRef",
    "LabTestComplete",
    "LabTestCreate",
    "LabTestDetail",
    "LabTestListItem",
    "LabTestOverride",
    "LabTestProcessingRef",
    "LabTestSummary",
    "LabTestUpdate",
    "LaboratoryCreate",
    "LaboratoryRead",
    "LaboratoryUpdate",
    "TraceabilityNode",
]
