"""Platform enumerations.

Phase 2 adds the beekeeper verification lifecycle and tightens the public
registration policy: only ``CONSUMER`` and ``BEEKEEPER`` may be self-selected.
Every other role is provisioned by an administrator (see
``docs/api.md`` → Registration policy).
"""

from __future__ import annotations

from enum import StrEnum


class UserRole(StrEnum):
    """Roles recognised by the platform's single authentication system."""

    ADMIN = "ADMIN"
    BEEKEEPER = "BEEKEEPER"
    COLLECTION_CENTER = "COLLECTION_CENTER"
    PROCESSOR = "PROCESSOR"
    LAB_TECHNICIAN = "LAB_TECHNICIAN"
    PACKAGING_UNIT = "PACKAGING_UNIT"
    DISTRIBUTOR = "DISTRIBUTOR"
    RETAILER = "RETAILER"
    CONSUMER = "CONSUMER"
    KVIC_OFFICER = "KVIC_OFFICER"

    @property
    def label(self) -> str:
        """Human-readable name, used by the API, the UI and the documentation."""
        return _ROLE_LABELS[self]

    @classmethod
    def values(cls) -> list[str]:
        return [role.value for role in cls]

    @classmethod
    def self_registrable(cls) -> list["UserRole"]:
        """Roles a visitor may choose on the public registration form.

        Deliberately limited to the two roles that carry no platform
        privileges. The remaining eight roles — including supply-chain
        participants such as processors and retailers — are created by an
        administrator or KVIC officer once the organisation has been verified.
        This is enforced by the API, not merely hidden in the UI.
        """
        return [cls.CONSUMER, cls.BEEKEEPER]

    @classmethod
    def admin_provisioned(cls) -> list["UserRole"]:
        """Roles that only an administrator may grant.

        Every role except the two self-registrable ones. An administrator
        provisions them through ``POST /api/v1/admin/users`` — the same single
        authentication system every other account uses, with the role stored in
        the database and enforced by ``ROLE_PERMISSIONS``.
        """
        return [role for role in cls if role not in cls.self_registrable()]

    @classmethod
    def assignable_by_admin(cls) -> list["UserRole"]:
        """Roles an administrator may assign when creating or editing an account.

        All ten, including ``ADMIN`` itself: promoting a colleague is how a
        second administrator exists at all. What is *not* possible is a user
        assigning a role to themselves — that needs
        ``Permission.ADMIN_ROLE_ASSIGN``, which only an administrator holds, and
        the endpoints that change a role refuse the caller's own account.
        """
        return list(ADMINISTRATION_ROLE_ORDER)

    @classmethod
    def administration_order(cls) -> tuple["UserRole", ...]:
        """The role list as the administration screen and ``/roles`` present it."""
        return ADMINISTRATION_ROLE_ORDER

    @classmethod
    def verification_authorities(cls) -> list["UserRole"]:
        """Roles allowed to change a beekeeper's verification status."""
        return [cls.ADMIN, cls.KVIC_OFFICER]


#: The order the administration screen lists roles in, and the order the
#: ``/roles`` catalogue returns them in. One order, declared once: the
#: administrator's own role first (it is the one that creates the others), then
#: the operational roles a platform stands up, then the two public ones.
ADMINISTRATION_ROLE_ORDER: tuple[UserRole, ...] = (
    UserRole.ADMIN,
    UserRole.BEEKEEPER,
    UserRole.CONSUMER,
    UserRole.KVIC_OFFICER,
    UserRole.COLLECTION_CENTER,
    UserRole.PROCESSOR,
    UserRole.LAB_TECHNICIAN,
    UserRole.PACKAGING_UNIT,
    UserRole.DISTRIBUTOR,
    UserRole.RETAILER,
)

#: Display name per role. Written out rather than derived from the key, because
#: deriving it produced ``Kvic Officer`` and ``Collection Center`` — names no
#: officer or collection centre uses — and an acronym cannot be recovered from a
#: key that has already been split into words.
_ROLE_LABELS: dict[UserRole, str] = {
    UserRole.ADMIN: "Administrator",
    UserRole.BEEKEEPER: "Beekeeper",
    UserRole.CONSUMER: "Consumer",
    UserRole.KVIC_OFFICER: "KVIC officer",
    UserRole.COLLECTION_CENTER: "Collection centre",
    UserRole.PROCESSOR: "Processor",
    UserRole.LAB_TECHNICIAN: "Lab technician",
    UserRole.PACKAGING_UNIT: "Packaging unit",
    UserRole.DISTRIBUTOR: "Distributor",
    UserRole.RETAILER: "Retailer",
}


class VerificationStatus(StrEnum):
    """Lifecycle of a beekeeper's registration review.

    ``PENDING`` is the state of every new registration: the platform never
    marks a beekeeper as government-verified on its own.
    """

    PENDING = "PENDING"
    UNDER_REVIEW = "UNDER_REVIEW"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def description(self) -> str:
        return {
            "PENDING": "Registration received and awaiting review.",
            "UNDER_REVIEW": "An officer is reviewing the submitted details.",
            "VERIFIED": "Details confirmed by a KVIC officer or administrator.",
            "REJECTED": "Registration was reviewed and not approved.",
            "SUSPENDED": "Verification withdrawn pending resolution of an issue.",
        }[self.value]

    @classmethod
    def allowed_transitions(cls, current: "VerificationStatus") -> list["VerificationStatus"]:
        """States reachable from ``current``.

        Encodes the review workflow so an invalid jump (for example
        ``PENDING → SUSPENDED``) is rejected rather than silently accepted.
        """
        workflow: dict[VerificationStatus, list[VerificationStatus]] = {
            cls.PENDING: [cls.UNDER_REVIEW, cls.VERIFIED, cls.REJECTED],
            cls.UNDER_REVIEW: [cls.VERIFIED, cls.REJECTED, cls.PENDING],
            cls.VERIFIED: [cls.SUSPENDED, cls.UNDER_REVIEW],
            cls.REJECTED: [cls.UNDER_REVIEW, cls.PENDING],
            cls.SUSPENDED: [cls.VERIFIED, cls.UNDER_REVIEW],
        }
        return workflow.get(current, [])

    def can_transition_to(self, target: "VerificationStatus") -> bool:
        return target in self.allowed_transitions(self)


class TokenType(StrEnum):
    """JWT ``type`` claim — prevents an access token being used as a refresh
    token (or vice versa)."""

    ACCESS = "access"
    REFRESH = "refresh"


class AccountStatus(StrEnum):
    """Derived account state surfaced to the frontend."""

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class AuditAction(StrEnum):
    """Events recorded in ``audit_logs``.

    The vocabulary is deliberately event-shaped (past tense, entity prefixed) so
    later phases can append their own actions — ``HIVE_REGISTERED``,
    ``BATCH_ANCHORED`` — without colliding with existing names.
    """

    # Identity
    USER_REGISTERED = "USER_REGISTERED"
    USER_LOGIN = "USER_LOGIN"
    USER_LOGOUT = "USER_LOGOUT"
    USER_LOGIN_FAILED = "USER_LOGIN_FAILED"
    PROFILE_UPDATED = "PROFILE_UPDATED"
    USER_ACTIVATED = "USER_ACTIVATED"
    USER_DEACTIVATED = "USER_DEACTIVATED"
    #: An administrator created an account for an operational role
    #: (``POST /api/v1/admin/users``). Distinct from USER_REGISTERED, which is a
    #: person signing themselves up on the public form.
    USER_PROVISIONED = "USER_PROVISIONED"
    #: An administrator changed an account's role. The metadata carries the
    #: previous and the new role, because "which role is this account now" is
    #: not answerable from the new value alone once history matters.
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED"

    # Beekeeping
    BEEKEEPER_CREATED = "BEEKEEPER_CREATED"
    BEEKEEPER_UPDATED = "BEEKEEPER_UPDATED"
    BEEKEEPER_VERIFIED = "BEEKEEPER_VERIFIED"
    BEEKEEPER_REJECTED = "BEEKEEPER_REJECTED"
    BEEKEEPER_SUSPENDED = "BEEKEEPER_SUSPENDED"
    BEEKEEPER_VERIFICATION_UPDATED = "BEEKEEPER_VERIFICATION_UPDATED"

    # Hives & IoT (Phase 3)
    HIVE_CREATED = "HIVE_CREATED"
    HIVE_UPDATED = "HIVE_UPDATED"
    HIVE_STATUS_CHANGED = "HIVE_STATUS_CHANGED"
    #: A hive taken out of the registry — softly (status REMOVED) or, when it
    #: is genuinely empty, by deleting the row.
    HIVE_REMOVED = "HIVE_REMOVED"
    DEVICE_REGISTERED = "DEVICE_REGISTERED"
    DEVICE_UPDATED = "DEVICE_UPDATED"
    DEVICE_STATUS_CHANGED = "DEVICE_STATUS_CHANGED"
    #: Recorded at most once per ``TELEMETRY_AUDIT_INTERVAL_SECONDS`` per device
    #: rather than once per packet — the readings themselves are the record.
    TELEMETRY_RECEIVED = "TELEMETRY_RECEIVED"

    # AI engine (Phase 4). An analysis is a recorded event: it is composed of
    # stored telemetry, produced a stored result and may have raised alerts, so
    # the trail has to show when it ran and on what model version.
    AI_ANALYSIS_RUN = "AI_ANALYSIS_RUN"
    AI_ALERT_CREATED = "AI_ALERT_CREATED"
    AI_ALERT_ACKNOWLEDGED = "AI_ALERT_ACKNOWLEDGED"

    # Clusters and organisational relationships (Phase 4.1). A beekeeper belongs
    # to a cluster, a hive inherits that cluster, and every change of those links
    # is an event: it decides who can see the hive.
    CLUSTER_CREATED = "CLUSTER_CREATED"
    CLUSTER_UPDATED = "CLUSTER_UPDATED"
    CLUSTER_STATUS_CHANGED = "CLUSTER_STATUS_CHANGED"
    #: Recorded when a beekeeper's cluster link is set, changed or cleared.
    BEEKEEPER_ASSIGNED_TO_CLUSTER = "BEEKEEPER_ASSIGNED_TO_CLUSTER"
    BEEKEEPER_REMOVED_FROM_CLUSTER = "BEEKEEPER_REMOVED_FROM_CLUSTER"
    #: Recorded when one hive's cluster link is set, changed or cleared.
    HIVE_ASSOCIATED_WITH_CLUSTER = "HIVE_ASSOCIATED_WITH_CLUSTER"
    #: The summary event of a membership change: which cluster the beekeeper came
    #: from and went to, and how many of their hives followed.
    CLUSTER_RELATIONSHIP_UPDATED = "CLUSTER_RELATIONSHIP_UPDATED"

    #: Historical aliases, kept so audit rows written before Phase 4.1 stay
    #: filterable by the name they were recorded under. Nothing writes these.
    CLUSTER_MEMBER_ASSIGNED = "CLUSTER_MEMBER_ASSIGNED"
    CLUSTER_MEMBER_REMOVED = "CLUSTER_MEMBER_REMOVED"

    # Collections and honey batches (Phase 5). A collection is a real harvest
    # event, and the batch it produces is the unit the supply chain will move —
    # so both the event and the record it creates are audited separately.
    COLLECTION_CREATED = "COLLECTION_CREATED"
    COLLECTION_UPDATED = "COLLECTION_UPDATED"
    COLLECTION_COMPLETED = "COLLECTION_COMPLETED"
    COLLECTION_CANCELLED = "COLLECTION_CANCELLED"
    BATCH_CREATED = "BATCH_CREATED"
    BATCH_STATUS_CHANGED = "BATCH_STATUS_CHANGED"

    # Processing and laboratory quality (Phase 6). The two records are separate
    # events with separate actors, so they are audited separately: a processing
    # run is an operation, a laboratory test is a measurement, and the batch
    # decision that follows from the measurement is a third thing again.
    PROCESSING_UNIT_CREATED = "PROCESSING_UNIT_CREATED"
    PROCESSING_UNIT_UPDATED = "PROCESSING_UNIT_UPDATED"
    PROCESSING_CREATED = "PROCESSING_CREATED"
    PROCESSING_STARTED = "PROCESSING_STARTED"
    PROCESSING_UPDATED = "PROCESSING_UPDATED"
    PROCESSING_COMPLETED = "PROCESSING_COMPLETED"
    PROCESSING_CANCELLED = "PROCESSING_CANCELLED"
    #: A run was allocated to a named processor, or reassigned to another.
    PROCESSING_ASSIGNED = "PROCESSING_ASSIGNED"
    #: The named processor took the run on (UNASSIGNED/ASSIGNED → ACCEPTED).
    PROCESSING_ACCEPTED = "PROCESSING_ACCEPTED"
    #: The batch left processing for the laboratory. Recorded as its own event
    #: as well as the generic BATCH_STATUS_CHANGED, because "did the completed
    #: run actually put the batch in the laboratory queue" is the single most
    #: important thing to be able to check after the fact.
    BATCH_MOVED_TO_LAB_TESTING = "BATCH_MOVED_TO_LAB_TESTING"
    LABORATORY_CREATED = "LABORATORY_CREATED"
    LABORATORY_UPDATED = "LABORATORY_UPDATED"
    LAB_PARAMETER_CONFIGURED = "LAB_PARAMETER_CONFIGURED"
    LAB_TEST_CREATED = "LAB_TEST_CREATED"
    LAB_SAMPLE_RECORDED = "LAB_SAMPLE_RECORDED"
    LAB_RESULT_RECORDED = "LAB_RESULT_RECORDED"
    LAB_RESULT_UPDATED = "LAB_RESULT_UPDATED"
    LAB_RESULT_REMOVED = "LAB_RESULT_REMOVED"
    LAB_TEST_COMPLETED = "LAB_TEST_COMPLETED"
    #: A test was allocated to a named technician, or reassigned to another.
    LAB_TEST_ASSIGNED = "LAB_TEST_ASSIGNED"
    #: The named technician took the test on.
    LAB_TEST_ACCEPTED = "LAB_TEST_ACCEPTED"
    LAB_TEST_OVERRIDDEN = "LAB_TEST_OVERRIDDEN"
    BATCH_APPROVED = "BATCH_APPROVED"
    BATCH_REJECTED = "BATCH_REJECTED"

    # Packaging, distribution and retail receipt (Phase 7). The pattern from
    # Phase 6 continues: the record and the batch move it causes are separate
    # events, so "who packed this batch" and "when did the batch become packaged"
    # can each be answered from the log alone.
    PACKAGING_UNIT_CREATED = "PACKAGING_UNIT_CREATED"
    PACKAGING_UNIT_UPDATED = "PACKAGING_UNIT_UPDATED"
    #: A value that was already wrong (or missing) was filled in from the records
    #: the platform already holds. Used by corrective migrations and scripts, so a
    #: backfilled relationship is never an unexplained number in the database.
    DATA_CORRECTION = "DATA_CORRECTION"
    PACKAGING_CREATED = "PACKAGING_CREATED"
    PACKAGING_STARTED = "PACKAGING_STARTED"
    PACKAGING_UPDATED = "PACKAGING_UPDATED"
    PACKAGING_COMPLETED = "PACKAGING_COMPLETED"
    PACKAGING_CANCELLED = "PACKAGING_CANCELLED"
    #: One package row was created by a completed packaging run.
    PACKAGE_CREATED = "PACKAGE_CREATED"
    #: A package moved between states (ready for dispatch, in distribution, …).
    PACKAGE_STATUS_CHANGED = "PACKAGE_STATUS_CHANGED"
    #: The batch left packaging for distribution.
    BATCH_MOVED_TO_DISTRIBUTION = "BATCH_MOVED_TO_DISTRIBUTION"
    #: Every package of the batch has been delivered.
    BATCH_DISTRIBUTION_COMPLETED = "BATCH_DISTRIBUTION_COMPLETED"
    DISTRIBUTION_CREATED = "DISTRIBUTION_CREATED"
    DISTRIBUTION_UPDATED = "DISTRIBUTION_UPDATED"
    SHIPMENT_DISPATCHED = "SHIPMENT_DISPATCHED"
    SHIPMENT_IN_TRANSIT = "SHIPMENT_IN_TRANSIT"
    SHIPMENT_DELIVERED = "SHIPMENT_DELIVERED"
    DISTRIBUTION_CANCELLED = "DISTRIBUTION_CANCELLED"
    #: The retailer confirmed receipt of an inbound shipment.
    PACKAGE_RECEIVED = "PACKAGE_RECEIVED"


#: Landing route for each role after a successful login.
ROLE_HOME_ROUTES: dict[UserRole, str] = {
    UserRole.ADMIN: "/admin",
    UserRole.BEEKEEPER: "/beekeeper",
    UserRole.COLLECTION_CENTER: "/collection-center",
    UserRole.PROCESSOR: "/processor",
    UserRole.LAB_TECHNICIAN: "/laboratory",
    UserRole.PACKAGING_UNIT: "/packaging",
    UserRole.DISTRIBUTOR: "/distributor",
    UserRole.RETAILER: "/retailer",
    UserRole.CONSUMER: "/consumer",
    UserRole.KVIC_OFFICER: "/kvic",
}


# --------------------------------------------------------------------------- #
# Phase 3 — hive & IoT vocabularies
# --------------------------------------------------------------------------- #
class HiveStatus(StrEnum):
    """Lifecycle of a registered hive.

    ``REMOVED`` exists so a hive can be taken out of service without deleting
    the readings and devices attached to it.
    """

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    MAINTENANCE = "MAINTENANCE"
    REMOVED = "REMOVED"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


class QueenStatus(StrEnum):
    """Queen state as observed by the beekeeper (never inferred in this phase)."""

    UNKNOWN = "UNKNOWN"
    PRESENT = "PRESENT"
    ABSENT = "ABSENT"
    UNDER_OBSERVATION = "UNDER_OBSERVATION"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


class ColonyStrength(StrEnum):
    """The beekeeper's own assessment of colony strength."""

    UNKNOWN = "UNKNOWN"
    WEAK = "WEAK"
    MODERATE = "MODERATE"
    STRONG = "STRONG"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


class DeviceType(StrEnum):
    """Kind of IoT hardware attached to a hive."""

    ESP32 = "ESP32"
    ESP32_GATEWAY = "ESP32_GATEWAY"
    LORA_NODE = "LORA_NODE"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @classmethod
    def values(cls) -> list[str]:
        return [kind.value for kind in cls]


class ConnectionType(StrEnum):
    """How a device reaches the platform."""

    WIFI = "WIFI"
    LORA = "LORA"
    MQTT = "MQTT"
    LORA_MQTT = "LORA_MQTT"
    CELLULAR = "CELLULAR"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").replace("MQTT", "MQTT").title()

    @classmethod
    def values(cls) -> list[str]:
        return [kind.value for kind in cls]


class DeviceStatus(StrEnum):
    """Device health as reported to the dashboard.

    ``ONLINE``/``OFFLINE`` are derived from ``last_seen`` against the configured
    threshold. ``MAINTENANCE`` is a deliberate operator state and is never
    overwritten by the derived value. ``WARNING`` flags a device that is
    reachable but degraded (currently: a low battery).
    """

    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    WARNING = "WARNING"
    MAINTENANCE = "MAINTENANCE"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]

    @classmethod
    def operator_settable(cls) -> list["DeviceStatus"]:
        """Statuses an operator may set by hand; the rest are derived."""
        return [cls.MAINTENANCE, cls.ONLINE, cls.OFFLINE, cls.WARNING]


class SensorType(StrEnum):
    """Sensors an ESP32 hive node can carry."""

    TEMPERATURE = "TEMPERATURE"
    HUMIDITY = "HUMIDITY"
    WEIGHT = "WEIGHT"
    VIBRATION = "VIBRATION"
    ACOUSTIC = "ACOUSTIC"
    BATTERY = "BATTERY"

    @property
    def label(self) -> str:
        return {
            "TEMPERATURE": "Temperature",
            "HUMIDITY": "Humidity",
            "WEIGHT": "Hive weight",
            "VIBRATION": "Vibration",
            "ACOUSTIC": "Acoustic activity",
            "BATTERY": "Battery",
        }[self.value]

    @property
    def reading_field(self) -> str:
        """Column on ``sensor_readings`` that this sensor writes to."""
        return {
            "TEMPERATURE": "temperature",
            "HUMIDITY": "humidity",
            "WEIGHT": "weight",
            "VIBRATION": "vibration",
            "ACOUSTIC": "acoustic_level",
            "BATTERY": "battery_level",
        }[self.value]

    @property
    def unit(self) -> str:
        """Display unit, matching the sensor's configured default."""
        return {
            "TEMPERATURE": "°C",
            "HUMIDITY": "%",
            "WEIGHT": "kg",
            "VIBRATION": "g",
            "ACOUSTIC": "dB",
            "BATTERY": "%",
        }[self.value]

    @classmethod
    def for_reading_field(cls, field: str) -> "SensorType | None":
        """Reverse lookup: which sensor writes to a given reading column."""
        return next((sensor for sensor in cls if sensor.reading_field == field), None)

    @classmethod
    def values(cls) -> list[str]:
        return [sensor.value for sensor in cls]


class TelemetrySource(StrEnum):
    """Where a reading came from. Never rewritten, never inferred."""

    REAL_DEVICE = "REAL_DEVICE"
    SIMULATOR = "SIMULATOR"
    MANUAL = "MANUAL"

    @property
    def label(self) -> str:
        return {
            "REAL_DEVICE": "Real device",
            "SIMULATOR": "Simulator",
            "MANUAL": "Manual entry",
        }[self.value]

    @classmethod
    def values(cls) -> list[str]:
        return [source.value for source in cls]


# --------------------------------------------------------------------------- #
# Phase 4 — AI engine vocabularies
#
# These describe an *assessment*, never a diagnosis. ``INSUFFICIENT_DATA`` and
# ``UNKNOWN`` exist so the model has somewhere honest to land when the telemetry
# does not support an answer.
# --------------------------------------------------------------------------- #
class AiHealthStatus(StrEnum):
    """Colony health band produced by the baseline scorer.

    A monitoring indicator computed from sensor patterns — not a veterinary or
    scientific determination about a colony.
    """

    HEALTHY = "HEALTHY"
    ATTENTION = "ATTENTION"
    AT_RISK = "AT_RISK"
    CRITICAL = "CRITICAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"

    @property
    def label(self) -> str:
        return {
            "HEALTHY": "Healthy",
            "ATTENTION": "Needs attention",
            "AT_RISK": "At risk",
            "CRITICAL": "Critical",
            "INSUFFICIENT_DATA": "Insufficient data",
        }[self.value]

    @property
    def description(self) -> str:
        return {
            "HEALTHY": "Sensor patterns are within the reference bands for the recorded period.",
            "ATTENTION": "Some patterns have moved away from the reference bands.",
            "AT_RISK": "Several patterns are outside the reference bands.",
            "CRITICAL": "Multiple strong deviations were detected in the recorded period.",
            "INSUFFICIENT_DATA": "Not enough telemetry to assess the colony.",
        }[self.value]

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


class AiRiskLevel(StrEnum):
    """Risk bands shared by the disease and swarming assessments."""

    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    UNKNOWN = "UNKNOWN"

    @property
    def label(self) -> str:
        return {
            "LOW": "Low",
            "MODERATE": "Moderate",
            "HIGH": "High",
            "UNKNOWN": "Not assessed",
        }[self.value]

    @classmethod
    def values(cls) -> list[str]:
        return [level.value for level in cls]


class AiTrend(StrEnum):
    """Direction of a series over the analysis window."""

    RISING = "RISING"
    STABLE = "STABLE"
    FALLING = "FALLING"
    UNKNOWN = "UNKNOWN"

    @property
    def label(self) -> str:
        return {
            "RISING": "Positive",
            "STABLE": "Stable",
            "FALLING": "Negative",
            "UNKNOWN": "Unknown",
        }[self.value]

    @classmethod
    def values(cls) -> list[str]:
        return [trend.value for trend in cls]


class AiDataQuality(StrEnum):
    """How much the analysis can be trusted, given what was recorded."""

    GOOD = "GOOD"
    LIMITED = "LIMITED"
    INSUFFICIENT = "INSUFFICIENT"

    @property
    def label(self) -> str:
        return {
            "GOOD": "Good",
            "LIMITED": "Limited",
            "INSUFFICIENT": "Insufficient",
        }[self.value]

    @classmethod
    def values(cls) -> list[str]:
        return [quality.value for quality in cls]


class AiAnalysisSource(StrEnum):
    """Which telemetry sources an analysis was computed from.

    Derived from the ``source`` column of the readings actually used, so an
    analysis over simulator packets can never be presented as hardware-derived.
    """

    REAL_DEVICE = "REAL_DEVICE"
    SIMULATOR = "SIMULATOR"
    MIXED = "MIXED"
    MANUAL = "MANUAL"
    NO_DATA = "NO_DATA"

    @property
    def label(self) -> str:
        return {
            "REAL_DEVICE": "Real device telemetry",
            "SIMULATOR": "Simulator telemetry",
            "MIXED": "Mixed telemetry sources",
            "MANUAL": "Manually entered readings",
            "NO_DATA": "No telemetry",
        }[self.value]

    @property
    def is_hardware(self) -> bool:
        return self is AiAnalysisSource.REAL_DEVICE

    @classmethod
    def values(cls) -> list[str]:
        return [source.value for source in cls]


class AiAlertType(StrEnum):
    """Signals the AI engine may raise, once per cooldown window."""

    HEALTH_CRITICAL = "HEALTH_CRITICAL"
    HEALTH_AT_RISK = "HEALTH_AT_RISK"
    DISEASE_RISK_HIGH = "DISEASE_RISK_HIGH"
    SWARMING_RISK_HIGH = "SWARMING_RISK_HIGH"
    TEMPERATURE_ANOMALY = "TEMPERATURE_ANOMALY"
    HUMIDITY_ANOMALY = "HUMIDITY_ANOMALY"
    WEIGHT_TREND_ANOMALY = "WEIGHT_TREND_ANOMALY"
    ACTIVITY_ANOMALY = "ACTIVITY_ANOMALY"
    DATA_STALE = "DATA_STALE"

    @property
    def label(self) -> str:
        return {
            "HEALTH_CRITICAL": "Colony health critical",
            "HEALTH_AT_RISK": "Colony health at risk",
            "DISEASE_RISK_HIGH": "Elevated disease risk",
            "SWARMING_RISK_HIGH": "Elevated swarming risk",
            "TEMPERATURE_ANOMALY": "Temperature anomaly",
            "HUMIDITY_ANOMALY": "Humidity anomaly",
            "WEIGHT_TREND_ANOMALY": "Weight trend anomaly",
            "ACTIVITY_ANOMALY": "Activity anomaly",
            "DATA_STALE": "Telemetry is stale",
        }[self.value]

    @classmethod
    def values(cls) -> list[str]:
        return [alert.value for alert in cls]


class AiAlertSeverity(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

    @property
    def label(self) -> str:
        return self.value.title()

    @classmethod
    def values(cls) -> list[str]:
        return [severity.value for severity in cls]


class AiAlertStatus(StrEnum):
    """Read state of an alert. There is no notification system yet, so this is
    the acknowledgement the beekeeper records in the app."""

    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"

    @property
    def label(self) -> str:
        return self.value.title()

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


class CollectionStatus(StrEnum):
    """Lifecycle of a honey collection event (Phase 5).

    Four states, each one meaning something a beekeeper actually does:

    * ``PLANNED``     — the harvest is scheduled; nothing has been taken yet;
    * ``IN_PROGRESS`` — the beekeeper has started and is recording quantities;
    * ``COMPLETED``   — the harvest is finished; a honey batch now exists;
    * ``CANCELLED``   — the event did not happen, and can never produce a batch.

    Only ``COMPLETED`` and ``CANCELLED`` are terminal: a completed collection
    cannot be edited or cancelled, and a cancelled one cannot be completed.
    """

    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def is_open(self) -> bool:
        """True while the collection may still be edited or completed."""
        return self in (CollectionStatus.PLANNED, CollectionStatus.IN_PROGRESS)

    @property
    def is_terminal(self) -> bool:
        return not self.is_open

    @classmethod
    def open_statuses(cls) -> list["CollectionStatus"]:
        return [status for status in cls if status.is_open]

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


class CollectionUnit(StrEnum):
    """Mass units a collection may be recorded in.

    Both are mass, so a total is always a sum of like quantities and never a
    converted guess. Nothing converts between them: a figure the beekeeper
    weighed in grams is stored in grams and reported in grams.
    """

    KG = "KG"
    GRAM = "GRAM"

    @property
    def label(self) -> str:
        return "kg" if self is CollectionUnit.KG else "g"

    @classmethod
    def values(cls) -> list[str]:
        return [unit.value for unit in cls]


class BatchStatus(StrEnum):
    """State of a honey batch.

    Phase 5 could produce only ``COLLECTED``: a batch is created by completing a
    collection and nothing else. Phase 6 adds the two states the processing and
    laboratory modules actually perform — and only those. ``PACKAGED``,
    ``DISTRIBUTION`` and ``COMPLETED`` remain reserved: no endpoint in this build
    can set them, so a batch cannot be described as packaged or distributed
    before the modules that do that work exist.

    The permitted moves are declared once, in
    :data:`BATCH_STATUS_TRANSITIONS`, and every writer goes through
    ``BatchLifecycle``. Nothing else in the codebase assigns ``batch.status``.
    """

    COLLECTED = "COLLECTED"
    PROCESSING = "PROCESSING"
    LAB_TESTING = "LAB_TESTING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    # -- Reserved for later phases (never written in Phases 5–6) ------------
    PACKAGED = "PACKAGED"
    DISTRIBUTION = "DISTRIBUTION"
    COMPLETED = "COMPLETED"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def is_reachable_in_collection_phase(self) -> bool:
        """Whether the *collection* phase is allowed to set the status."""
        return self is BatchStatus.COLLECTED

    @property
    def is_reachable_in_quality_phase(self) -> bool:
        """Whether the processing/laboratory phase may set the status."""
        return self in (
            BatchStatus.COLLECTED,
            BatchStatus.PROCESSING,
            BatchStatus.LAB_TESTING,
            BatchStatus.APPROVED,
            BatchStatus.REJECTED,
        )

    @property
    def is_reachable_in_supply_phase(self) -> bool:
        """Whether the packaging/distribution phase may hold the status."""
        return self in (
            BatchStatus.PACKAGED,
            BatchStatus.DISTRIBUTION,
            BatchStatus.COMPLETED,
        )

    @property
    def has_quality_decision(self) -> bool:
        """True once the laboratory has decided the batch's fate."""
        return self in (BatchStatus.APPROVED, BatchStatus.REJECTED)

    @classmethod
    def collection_phase_statuses(cls) -> list["BatchStatus"]:
        return [status for status in cls if status.is_reachable_in_collection_phase]

    @classmethod
    def quality_phase_statuses(cls) -> list["BatchStatus"]:
        """The statuses the processing/laboratory phase is allowed to hold."""
        return [status for status in cls if status.is_reachable_in_quality_phase]

    @classmethod
    def supply_phase_statuses(cls) -> list["BatchStatus"]:
        """The statuses the packaging/distribution phase is allowed to hold."""
        return [status for status in cls if status.is_reachable_in_supply_phase]

    @classmethod
    def reserved_statuses(cls) -> list["BatchStatus"]:
        """Statuses no shipped module can reach: the vocabulary future phases use."""
        return [
            status
            for status in cls
            if status not in cls.collection_phase_statuses()
            and status not in cls.quality_phase_statuses()
        ]

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


#: The batch lifecycle, declared once. Every transition in the platform is
#: checked against this map — a caller can never move a batch from ``COLLECTED``
#: straight to ``APPROVED``, and no future module can either, unless the map is
#: deliberately extended and a migration ships with it.
BATCH_STATUS_TRANSITIONS: dict[BatchStatus, tuple[BatchStatus, ...]] = {
    BatchStatus.COLLECTED: (BatchStatus.PROCESSING,),
    BatchStatus.PROCESSING: (BatchStatus.LAB_TESTING, BatchStatus.COLLECTED),
    BatchStatus.LAB_TESTING: (BatchStatus.APPROVED, BatchStatus.REJECTED, BatchStatus.LAB_TESTING),
    # An approved batch may be packaged. A rejected one may not: it can only go
    # back to the laboratory (a retest is the way a rejection is ever revisited).
    BatchStatus.APPROVED: (BatchStatus.LAB_TESTING, BatchStatus.PACKAGED),
    BatchStatus.REJECTED: (BatchStatus.LAB_TESTING,),
    # Phase 7 opens the downstream half of the chain. A batch reaches PACKAGED
    # only when a packaging run completes against it, DISTRIBUTION only when a
    # shipment of its packages is actually dispatched with a carrier, and
    # COMPLETED only when every dispatched package has been received. The
    # self-transitions are deliberate: a batch stays PACKAGED while further runs
    # pack the remainder, and stays DISTRIBUTION while further shipments of the
    # same batch are in flight.
    BatchStatus.PACKAGED: (BatchStatus.DISTRIBUTION, BatchStatus.PACKAGED),
    BatchStatus.DISTRIBUTION: (BatchStatus.COMPLETED, BatchStatus.DISTRIBUTION),
    BatchStatus.COMPLETED: (),
}


class AssignmentStatus(StrEnum):
    """Whether work has been allocated to a named person, and accepted by them.

    Used by both operational hand-offs — a batch waiting to be processed and a
    batch waiting to be tested — because the question is the same in both cases:
    *has somebody been made responsible for this, and have they taken it on?*

    ``UNASSIGNED`` — nobody is responsible yet. The work is still in the shared
                     queue and every eligible operator can pick it up; nothing
                     disappears just because it has not been allocated.
    ``ASSIGNED``   — an administrator (or the module's own staff) named the
                     operator. It stays in that operator's *assigned* queue and,
                     until they accept it, in the shared queue as well.
    ``ACCEPTED``   — the operator has taken it on. From here it is their work:
                     it appears under "assigned to me" and nowhere else.

    The assignment lives on the operational record (the processing run, the
    laboratory test), never on the batch — a batch is one row that several roles
    read, and giving it an "assigned to" field would make the shared record
    carry one role's queue.
    """

    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    ACCEPTED = "ACCEPTED"

    @property
    def label(self) -> str:
        return {
            AssignmentStatus.UNASSIGNED: "Unassigned",
            AssignmentStatus.ASSIGNED: "Assigned",
            AssignmentStatus.ACCEPTED: "Accepted",
        }[self]

    @property
    def is_allocated(self) -> bool:
        """True once a named operator is responsible for the work."""
        return self is not AssignmentStatus.UNASSIGNED


class ProcessingStatus(StrEnum):
    """Where a processing run stands.

    ``PENDING``    — the run is planned; the honey has not been touched yet and
                     the batch is still ``COLLECTED``.
    ``IN_PROGRESS``— processing has started; the batch is ``PROCESSING`` and the
                     quantities may still be corrected as they are measured.
    ``COMPLETED``  — finished: the input, the output and the loss are recorded and
                     frozen, and the batch moves to ``LAB_TESTING``.
    ``CANCELLED``  — the run did not happen. The batch returns to ``COLLECTED``,
                     because nothing was done to the honey.
    """

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def is_open(self) -> bool:
        """True while the record may still be corrected."""
        return self in (ProcessingStatus.PENDING, ProcessingStatus.IN_PROGRESS)

    @classmethod
    def open_statuses(cls) -> list["ProcessingStatus"]:
        return [status for status in cls if status.is_open]

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


class ProcessingType(StrEnum):
    """What a processing run did to the honey.

    These are operation names, not quality claims: recording that honey was
    filtered says a filter was used, not that the result is compliant with
    anything. ``OTHER`` exists so an operation outside this list can be recorded
    honestly instead of being forced into a category that misdescribes it.
    """

    FILTERING = "FILTERING"
    DECRYSTALLIZATION = "DECRYSTALLIZATION"
    PASTEURIZATION = "PASTEURIZATION"
    BLENDING = "BLENDING"
    MOISTURE_REDUCTION = "MOISTURE_REDUCTION"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @classmethod
    def values(cls) -> list[str]:
        return [kind.value for kind in cls]


class FacilityStatus(StrEnum):
    """Whether a processing unit or laboratory is currently operating.

    A retired facility stays readable — the records it produced must keep
    resolving — but it cannot be selected for new work.
    """

    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"

    @property
    def label(self) -> str:
        return self.value.title()

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


class LabTestStatus(StrEnum):
    """Where a laboratory test stands."""

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def is_open(self) -> bool:
        return self is not LabTestStatus.COMPLETED

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]

    @classmethod
    def open_statuses(cls) -> list["LabTestStatus"]:
        """The statuses a test can still be worked on in."""
        return [status for status in cls if status.is_open]


class LabResult(StrEnum):
    """The overall outcome of a laboratory test.

    ``INCONCLUSIVE`` is a real outcome, not a failure and not a pass: it means the
    evidence needed to decide is not there (a required measurement is missing, or
    a parameter has no configured reference range to compare against). A batch is
    never approved or rejected on an inconclusive test.
    """

    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    INCONCLUSIVE = "INCONCLUSIVE"

    @property
    def label(self) -> str:
        return self.value.title()

    @property
    def is_decision(self) -> bool:
        """True when the result decides the batch's fate."""
        return self in (LabResult.PASS, LabResult.FAIL)

    @classmethod
    def values(cls) -> list[str]:
        return [result.value for result in cls]


class LabParameterStatus(StrEnum):
    """A single measurement compared against its configured reference range."""

    PASS = "PASS"
    FAIL = "FAIL"
    NOT_EVALUATED = "NOT_EVALUATED"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def is_configured(self) -> bool:
        """False when no reference range exists, so no judgement was made."""
        return self is not LabParameterStatus.NOT_EVALUATED

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


class LabMeasureUnit(StrEnum):
    """The unit a laboratory measurement is reported in.

    Stored as text and never converted: if an instrument reports HMF in mg/kg,
    the value is kept in mg/kg and shown that way. Converting between units would
    require assumptions about the instrument that this platform was never given.
    """

    PERCENT = "%"
    MG_PER_KG = "mg/kg"
    MS_PER_CM = "mS/cm"
    DN = "DN"
    MM_PFUND = "mm Pfund"
    MEQ_PER_KG = "meq/kg"
    G_PER_100G = "g/100g"
    PH_SCALE = "pH"
    UNITLESS = "unitless"

    @property
    def label(self) -> str:
        return self.value

    @classmethod
    def values(cls) -> list[str]:
        return [unit.value for unit in cls]


class LabParameterCode(StrEnum):
    """The measurement slots a honey quality test can record.

    A *slot*, not a claim: the code names what was measured and in which unit.
    Whether a value is acceptable is decided by the reference range configured
    for that slot (see ``lab_parameters``), never by a threshold compiled into
    this file — the platform ships with no ranges and says so.
    """

    MOISTURE = "MOISTURE"
    PH = "PH"
    ELECTRICAL_CONDUCTIVITY = "ELECTRICAL_CONDUCTIVITY"
    HMF = "HMF"
    DIASTASE_ACTIVITY = "DIASTASE_ACTIVITY"
    SUCROSE = "SUCROSE"
    REDUCING_SUGARS = "REDUCING_SUGARS"
    COLOR = "COLOR"
    PURITY = "PURITY"
    FREE_ACIDITY = "FREE_ACIDITY"
    WATER_INSOLUBLE_SOLIDS = "WATER_INSOLUBLE_SOLIDS"
    ASH = "ASH"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @classmethod
    def values(cls) -> list[str]:
        return [code.value for code in cls]


class BatchStage(StrEnum):
    """The traceability timeline a batch travels along.

    ``COLLECTION`` is where every batch starts in this phase. The later stages
    are listed so the timeline renders the whole journey honestly — as *not
    started* — instead of implying stages that do not exist yet.
    """

    COLLECTION = "COLLECTION"
    PROCESSING = "PROCESSING"
    LABORATORY = "LABORATORY"
    PACKAGING = "PACKAGING"
    DISTRIBUTION = "DISTRIBUTION"
    COMPLETED = "COMPLETED"

    @property
    def label(self) -> str:
        return self.value.title()

    @classmethod
    def ordered(cls) -> list["BatchStage"]:
        return [
            cls.COLLECTION,
            cls.PROCESSING,
            cls.LABORATORY,
            cls.PACKAGING,
            cls.DISTRIBUTION,
            cls.COMPLETED,
        ]

    def reached(self, current: "BatchStage") -> bool:
        """Whether this stage has been reached, given where the batch stands."""
        try:
            return self.ordered().index(current) >= self.ordered().index(self)
        except ValueError:  # pragma: no cover - defensive
            return self is BatchStage.COLLECTION

    @classmethod
    def values(cls) -> list[str]:
        return [stage.value for stage in cls]


# --------------------------------------------------------------------------- #
# Phase 7 — packaging, packages and distribution
# --------------------------------------------------------------------------- #
class PackagingStatus(StrEnum):
    """Where a packaging run stands.

    The wording matches the processing vocabulary on purpose: a packaging run is
    an *operation* performed on an approved batch, and it has the same four
    states a processing run has. What differs is the validation — a run may only
    start against a laboratory-approved batch, and may only complete when the
    packages it claims were actually created.
    """

    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def is_open(self) -> bool:
        """True while the run may still be started or completed."""
        return self in (PackagingStatus.PENDING, PackagingStatus.IN_PROGRESS)

    @classmethod
    def open_statuses(cls) -> list["PackagingStatus"]:
        return [status for status in cls if status.is_open]

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


#: Permitted packaging transitions, declared once.
PACKAGING_STATUS_TRANSITIONS: dict[PackagingStatus, tuple[PackagingStatus, ...]] = {
    PackagingStatus.PENDING: (PackagingStatus.IN_PROGRESS, PackagingStatus.CANCELLED),
    PackagingStatus.IN_PROGRESS: (PackagingStatus.COMPLETED, PackagingStatus.CANCELLED),
    PackagingStatus.COMPLETED: (),
    PackagingStatus.CANCELLED: (),
}


class PackagingType(StrEnum):
    """The container a batch was packed into. A description, not a claim."""

    JAR = "JAR"
    BOTTLE = "BOTTLE"
    POUCH = "POUCH"
    TIN = "TIN"
    BULK_CONTAINER = "BULK_CONTAINER"
    OTHER = "OTHER"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @classmethod
    def values(cls) -> list[str]:
        return [value.value for value in cls]


class PackageStatus(StrEnum):
    """The journey of a single physical package.

    ``CREATED`` is set the moment a packaging run completes and the package rows
    exist. Nothing is implied about readiness by mere existence: a package is
    ``READY_FOR_DISTRIBUTION`` when the packing unit has released it, and only
    then can a shipment be raised against it.
    """

    CREATED = "CREATED"
    READY_FOR_DISTRIBUTION = "READY_FOR_DISTRIBUTION"
    IN_DISTRIBUTION = "IN_DISTRIBUTION"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def is_open(self) -> bool:
        return self in (
            PackageStatus.CREATED,
            PackageStatus.READY_FOR_DISTRIBUTION,
            PackageStatus.IN_DISTRIBUTION,
        )

    @classmethod
    def transitions(cls) -> dict["PackageStatus", tuple["PackageStatus", ...]]:
        return PACKAGE_STATUS_TRANSITIONS

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


PACKAGE_STATUS_TRANSITIONS: dict[PackageStatus, tuple[PackageStatus, ...]] = {
    PackageStatus.CREATED: (PackageStatus.READY_FOR_DISTRIBUTION, PackageStatus.CANCELLED),
    PackageStatus.READY_FOR_DISTRIBUTION: (
        PackageStatus.IN_DISTRIBUTION,
        PackageStatus.CANCELLED,
    ),
    PackageStatus.IN_DISTRIBUTION: (PackageStatus.DELIVERED, PackageStatus.IN_DISTRIBUTION),
    PackageStatus.DELIVERED: (),
    PackageStatus.CANCELLED: (),
}


class DistributionStatus(StrEnum):
    """Where a shipment of packages stands.

    The record is created as ``READY_FOR_DISPATCH`` — the packages are named, the
    destination is known and nothing has left the building. ``DISPATCHED`` means
    it has left, ``IN_TRANSIT`` that it is moving, ``DELIVERED`` that the retailer
    has it. ``DELIVERED`` is deliberately unreachable without dispatch: a
    delivery that no dispatch preceded would be a claim about a journey that
    never started.
    """

    READY_FOR_DISPATCH = "READY_FOR_DISPATCH"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"

    @property
    def label(self) -> str:
        return self.value.replace("_", " ").title()

    @property
    def is_open(self) -> bool:
        return self in (
            DistributionStatus.READY_FOR_DISPATCH,
            DistributionStatus.DISPATCHED,
            DistributionStatus.IN_TRANSIT,
        )

    @classmethod
    def values(cls) -> list[str]:
        return [status.value for status in cls]


DISTRIBUTION_STATUS_TRANSITIONS: dict[DistributionStatus, tuple[DistributionStatus, ...]] = {
    DistributionStatus.READY_FOR_DISPATCH: (
        DistributionStatus.DISPATCHED,
        DistributionStatus.CANCELLED,
    ),
    DistributionStatus.DISPATCHED: (
        DistributionStatus.IN_TRANSIT,
        DistributionStatus.DELIVERED,
        DistributionStatus.CANCELLED,
    ),
    DistributionStatus.IN_TRANSIT: (
        DistributionStatus.DELIVERED,
        DistributionStatus.IN_TRANSIT,
    ),
    DistributionStatus.DELIVERED: (),
    DistributionStatus.CANCELLED: (),
}
