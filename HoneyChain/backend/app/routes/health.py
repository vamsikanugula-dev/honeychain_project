"""Health and readiness endpoints.

``GET /api/v1/health``          liveness — used by the frontend status indicator
``GET /api/v1/health/db``       readiness — verifies PostgreSQL connectivity
``GET /api/v1/health/detailed`` component-by-component report
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import db_session
from app.core.config import Settings, get_settings
from app.core.database import check_database_connection
from app.core.logging import get_logger
from app.schemas.common import (
    ApiResponse,
    HealthDetailResponse,
    HealthResponse,
    ok,
)
from app.schemas.iot import MqttHealth

router = APIRouter(tags=["Health"])
logger = get_logger("service")


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="Service liveness",
    description="Cheap liveness probe. Does not touch the database.",
)
def health() -> HealthResponse:
    return HealthResponse(status="ok", service="HoneyChain API")


@router.get(
    "/health/db",
    response_model=ApiResponse[dict],
    summary="Database readiness",
    description="Verifies that the API can reach PostgreSQL and that migrations are applied.",
)
def health_db(
    session: Session = Depends(db_session),
    settings: Settings = Depends(get_settings),
) -> dict:
    from sqlalchemy import inspect

    info = check_database_connection(settings)
    tables: list[str] = []
    if info["connected"]:
        tables = sorted(inspect(session.get_bind()).get_table_names())

    status = "ok" if info["connected"] else "degraded"
    if not info["connected"]:
        logger.error("Database readiness check failed")
    return ok(
        {
            "status": status,
            "database": {
                "connected": info["connected"],
                "dialect": info["dialect"],
                "server_version": info["server_version"],
                "environment": info["environment"],
            },
            "tables": tables,
        }
    )


@router.get(
    "/health/mqtt",
    response_model=ApiResponse[MqttHealth],
    summary="MQTT ingest status",
    description=(
        "Reports whether the broker consumer is running and what it has received. "
        "``not_configured`` is a normal state: without a broker the HTTP ingest "
        "endpoint (``POST /api/v1/iot/telemetry``) still accepts telemetry."
    ),
)
def health_mqtt() -> dict:
    from app.services.mqtt_service import get_ingest_service

    return ok(MqttHealth(**get_ingest_service().health()))


@router.get(
    "/health/detailed",
    response_model=HealthDetailResponse,
    summary="Full component report",
    description=(
        "Reports the status of each subsystem. Blockchain, IoT and AI components "
        "report 'not_configured' until their phases are implemented — this is "
        "expected, not an error."
    ),
)
def health_detailed(settings: Settings = Depends(get_settings)) -> HealthDetailResponse:
    database = check_database_connection(settings)

    def placeholder(configured: bool) -> str:
        return "configured" if configured else "not_configured"

    components: dict[str, object] = {
        "database": {
            "status": "ok" if database["connected"] else "down",
            "dialect": database["dialect"],
        },
        "authentication": {"status": "ok", "strategy": "JWT (access + rotating refresh)"},
        "blockchain": {
            "status": "configured" if settings.blockchain_configured else "disabled",
            "phase": "Phase 8",
            "service": "Hyperledger Fabric transaction API",
        },
        # Phase 3 delivered the IoT foundation (device registry, sensor
        # configuration, MQTT + HTTP telemetry ingest). The status here reflects
        # whether a broker is configured, not whether the module exists.
        "iot": {
            "status": "ok" if settings.MQTT_BROKER_URL else "not_configured",
            "phase": "Phase 3",
            "ingest": "MQTT + HTTP",
            "broker_configured": bool(settings.MQTT_BROKER_URL),
        },
        "ai": {"status": placeholder(bool(settings.AI_API_KEY)), "phase": "Phase 5"},
    }
    all_ok = database["connected"]
    return HealthDetailResponse(
        status="ok" if all_ok else "degraded",
        service=settings.SERVICE_NAME,
        version=settings.VERSION,
        environment=settings.ENVIRONMENT,
        timestamp=datetime.now(timezone.utc),
        components=components,
    )
