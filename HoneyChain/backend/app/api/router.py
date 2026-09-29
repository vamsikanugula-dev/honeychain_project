"""Version 1 API router.

Every feature phase mounts its own router here, which is why adding a module
never requires editing ``main.py`` or restructuring existing code::

    # Phase 3 — blockchain traceability
    from app.routes import traceability
    api_router.include_router(traceability.router)
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.routes import (
    admin,
    ai,
    auth,
    batches,
    beekeepers,
    clusters,
    collections,
    distribution,
    health,
    hives,
    iot,
    laboratory,
    meta,
    packaging,
    processing,
    profile,
    users,
)

api_router = APIRouter()

# -- Foundation (Phase 1) ---------------------------------------------------
api_router.include_router(health.router)
api_router.include_router(meta.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)

# -- User, role & beekeeper management (Phase 2) ----------------------------
api_router.include_router(profile.router)
api_router.include_router(beekeepers.router)
api_router.include_router(clusters.router)
api_router.include_router(admin.router)

# -- Hive management & smart-hive IoT foundation (Phase 3) ------------------
api_router.include_router(hives.router)
api_router.include_router(iot.router)

# -- AI insights (Phase 4) --------------------------------------------------
api_router.include_router(ai.router)

# -- Collections & honey batches (Phase 5) ----------------------------------
# A harvest is recorded by its beekeeper; completing it produces the single batch
# the later supply-chain modules will move. Nothing beyond collection exists yet.
api_router.include_router(collections.router)
api_router.include_router(batches.router)

# -- Processing & laboratory quality (Phase 6) ------------------------------
# A batch leaves the apiary as COLLECTED. Processing records what was done to the
# honey and moves it to LAB_TESTING; laboratory testing records what was measured
# and decides APPROVED or REJECTED. Both write to the batch's single record through
# the transition table — neither keeps a copy of it, so a KVIC officer reading a
# cluster sees the same rows the beekeeper and the technician see.
api_router.include_router(processing.router)
api_router.include_router(laboratory.router)

# -- Packaging, distribution and retail receipt (Phase 7) -------------------
# An approved batch is packed into packages, the packages are shipped, and the
# retailer confirms what arrived. Every step writes to the batch's single record
# through the transition table, so the beekeeper watching their own honey and the
# officer watching their cluster read the same rows the packer and the carrier do.
api_router.include_router(packaging.router)
api_router.include_router(distribution.router)

# -- Planned phases (uncomment as each module is implemented) ---------------
# from app.routes import blockchain, supply_chain
# api_router.include_router(blockchain.router)        # later phase — chain anchoring
# api_router.include_router(supply_chain.router)      # later phase — packaging, distribution, QR


@api_router.get("/", include_in_schema=False)
def api_root() -> dict:
    """Small discovery document for developers hitting the API root."""
    settings = get_settings()
    return {
        "service": settings.SERVICE_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "health": f"{settings.API_V1_PREFIX}/health",
    }
