"""
Admin maintenance API package.

Feature #353: Refactored from monolithic admin_maintenance.py into cohesive sub-modules.

All endpoints are combined into a single `router` export. The prefix
`/api/admin/maintenance` is applied in main.py — sub-routers use no prefix.
"""

from fastapi import APIRouter

from .maintenance import router as maintenance_router
from .reembed import router as reembed_router
from .soft_delete import router as soft_delete_router
from .embedding_backup import router as embedding_backup_router
from .audit import router as audit_router
from .integrity import router as integrity_router
from .dashboard import router as dashboard_router

router = APIRouter()
router.include_router(maintenance_router)
router.include_router(reembed_router)
router.include_router(soft_delete_router)
router.include_router(embedding_backup_router)
router.include_router(audit_router)
router.include_router(integrity_router)
router.include_router(dashboard_router)
