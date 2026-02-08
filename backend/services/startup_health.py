"""
Post-Startup Health Check with Auto-Fix (Feature #348).

Runs after database initialization to verify system integrity and
auto-fix recoverable issues. Checks:
1. DB triggers exist (chunk_count triggers on document_embeddings)
2. chunk_count is synchronized with actual embedding count
3. No orphan embeddings (embeddings without parent document)
4. BM25 index is in sync with embeddings

Auto-fixes recoverable issues and logs warnings for manual intervention.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from sqlalchemy import text

logger = logging.getLogger(__name__)


@dataclass
class HealthCheckResult:
    """Result of a single health check."""
    name: str
    status: str  # "ok", "fixed", "warning", "error"
    message: str
    fixed: int = 0
    details: Optional[Dict] = None


@dataclass
class StartupHealthReport:
    """Overall startup health check report."""
    checks: List[HealthCheckResult] = field(default_factory=list)
    duration_ms: float = 0.0
    issues_found: int = 0
    issues_fixed: int = 0

    def to_dict(self) -> Dict:
        return {
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "message": c.message,
                    "fixed": c.fixed,
                    **({"details": c.details} if c.details else {}),
                }
                for c in self.checks
            ],
            "duration_ms": round(self.duration_ms, 2),
            "issues_found": self.issues_found,
            "issues_fixed": self.issues_fixed,
        }


# Module-level storage for the last startup health report
_last_report: Optional[StartupHealthReport] = None


def get_last_report() -> Optional[Dict]:
    """Return the last startup health report as a dict, or None."""
    if _last_report is None:
        return None
    return _last_report.to_dict()


def run_startup_health_check() -> StartupHealthReport:
    """
    Run all startup health checks and auto-fix recoverable issues.

    This is called once during application startup, after DB init.
    Uses sync database sessions (startup runs before async loop is fully ready).
    """
    global _last_report

    start = time.time()
    report = StartupHealthReport()

    logger.info("[Feature #348] Running post-startup health checks...")

    try:
        from core.database import SessionLocal

        with SessionLocal() as session:
            # Check 1: Verify chunk_count triggers exist
            report.checks.append(_check_triggers(session))

            # Check 2: Sync chunk_count mismatches
            report.checks.append(_check_chunk_count_sync(session))

            # Check 3: Detect orphan embeddings
            report.checks.append(_check_orphan_embeddings(session))

            # Check 4: Verify BM25 index sync
            report.checks.append(_check_bm25_sync(session))

            session.commit()

    except Exception as e:
        logger.error(f"[Feature #348] Startup health check failed: {e}")
        report.checks.append(HealthCheckResult(
            name="health_check_error",
            status="error",
            message=f"Health check could not complete: {e}",
        ))

    report.duration_ms = (time.time() - start) * 1000
    report.issues_found = sum(1 for c in report.checks if c.status not in ("ok",))
    report.issues_fixed = sum(c.fixed for c in report.checks)

    # Log summary
    ok_count = sum(1 for c in report.checks if c.status == "ok")
    fixed_count = sum(1 for c in report.checks if c.status == "fixed")
    warn_count = sum(1 for c in report.checks if c.status == "warning")
    err_count = sum(1 for c in report.checks if c.status == "error")

    summary_parts = []
    if ok_count:
        summary_parts.append(f"{ok_count} ok")
    if fixed_count:
        summary_parts.append(f"{fixed_count} auto-fixed")
    if warn_count:
        summary_parts.append(f"{warn_count} warnings")
    if err_count:
        summary_parts.append(f"{err_count} errors")

    logger.info(
        f"[Feature #348] Startup health check complete in {report.duration_ms:.0f}ms: "
        + ", ".join(summary_parts)
    )

    _last_report = report
    return report


def _check_triggers(session) -> HealthCheckResult:
    """Check 1: Verify chunk_count triggers exist on document_embeddings."""
    try:
        result = session.execute(text("""
            SELECT tgname FROM pg_trigger
            WHERE tgrelid = 'document_embeddings'::regclass
            AND tgname LIKE 'trg_update_chunk_count_%'
        """))
        triggers = [row[0] for row in result.fetchall()]

        expected = {
            "trg_update_chunk_count_insert",
            "trg_update_chunk_count_delete",
            "trg_update_chunk_count_update",
        }
        found = set(triggers)
        missing = expected - found

        if not missing:
            return HealthCheckResult(
                name="chunk_count_triggers",
                status="ok",
                message=f"All {len(expected)} chunk_count triggers present",
            )

        # Auto-fix: recreate missing triggers
        logger.warning(f"[Feature #348] Missing triggers: {missing} - recreating...")
        _recreate_chunk_count_triggers(session)

        # Verify fix
        result = session.execute(text("""
            SELECT tgname FROM pg_trigger
            WHERE tgrelid = 'document_embeddings'::regclass
            AND tgname LIKE 'trg_update_chunk_count_%'
        """))
        after_fix = {row[0] for row in result.fetchall()}
        still_missing = expected - after_fix

        if still_missing:
            return HealthCheckResult(
                name="chunk_count_triggers",
                status="warning",
                message=f"Could not recreate triggers: {still_missing}",
                details={"missing": list(still_missing)},
            )

        return HealthCheckResult(
            name="chunk_count_triggers",
            status="fixed",
            message=f"Recreated {len(missing)} missing triggers: {', '.join(missing)}",
            fixed=len(missing),
        )

    except Exception as e:
        # Table might not exist yet (fresh DB before create_all)
        if "does not exist" in str(e):
            return HealthCheckResult(
                name="chunk_count_triggers",
                status="ok",
                message="document_embeddings table not yet created - triggers will be applied by migrations",
            )
        return HealthCheckResult(
            name="chunk_count_triggers",
            status="error",
            message=f"Trigger check failed: {e}",
        )


def _recreate_chunk_count_triggers(session) -> None:
    """Recreate the chunk_count trigger function and triggers."""
    session.execute(text("""
        CREATE OR REPLACE FUNCTION update_document_chunk_count()
        RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                UPDATE documents SET chunk_count = chunk_count + 1
                WHERE id = NEW.document_id;
                RETURN NEW;
            ELSIF TG_OP = 'DELETE' THEN
                UPDATE documents SET chunk_count = GREATEST(chunk_count - 1, 0)
                WHERE id = OLD.document_id;
                RETURN OLD;
            ELSIF TG_OP = 'UPDATE' THEN
                IF TG_ARGV[0] = 'has_status' THEN
                    IF OLD.status = 'active' AND NEW.status = 'pending_delete' THEN
                        UPDATE documents SET chunk_count = GREATEST(chunk_count - 1, 0)
                        WHERE id = NEW.document_id;
                    ELSIF OLD.status = 'pending_delete' AND NEW.status = 'active' THEN
                        UPDATE documents SET chunk_count = chunk_count + 1
                        WHERE id = NEW.document_id;
                    END IF;
                END IF;
                RETURN NEW;
            END IF;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql;
    """))

    session.execute(text("""
        DO $$
        BEGIN
            DROP TRIGGER IF EXISTS trg_update_chunk_count_insert ON document_embeddings;
            DROP TRIGGER IF EXISTS trg_update_chunk_count_delete ON document_embeddings;
            DROP TRIGGER IF EXISTS trg_update_chunk_count_update ON document_embeddings;

            CREATE TRIGGER trg_update_chunk_count_insert
                AFTER INSERT ON document_embeddings
                FOR EACH ROW EXECUTE FUNCTION update_document_chunk_count();

            CREATE TRIGGER trg_update_chunk_count_delete
                AFTER DELETE ON document_embeddings
                FOR EACH ROW EXECUTE FUNCTION update_document_chunk_count();

            CREATE TRIGGER trg_update_chunk_count_update
                AFTER UPDATE ON document_embeddings
                FOR EACH ROW EXECUTE FUNCTION update_document_chunk_count('has_status');
        END $$;
    """))


def _check_chunk_count_sync(session) -> HealthCheckResult:
    """Check 2: Sync chunk_count for all documents with actual embedding count."""
    try:
        # Feature #361: Only count active embeddings to match what chunk_count triggers track
        result = session.execute(text("""
            SELECT d.id, d.title, d.chunk_count, COUNT(de.id) as actual_count
            FROM documents d
            LEFT JOIN document_embeddings de ON d.id = de.document_id
                AND (de.status = 'active' OR de.status IS NULL)
            WHERE d.document_type = 'unstructured'
            GROUP BY d.id, d.title, d.chunk_count
            HAVING d.chunk_count != COUNT(de.id)
        """))
        mismatches = result.fetchall()

        if not mismatches:
            return HealthCheckResult(
                name="chunk_count_sync",
                status="ok",
                message="All document chunk_counts match actual embedding counts",
            )

        # Auto-fix: update chunk_count to match actual count
        fixed_count = 0
        for row in mismatches:
            doc_id, title, stored, actual = row
            logger.info(
                f"[Feature #348] Fixing chunk_count for '{title}': "
                f"{stored} -> {actual}"
            )
            session.execute(
                text("UPDATE documents SET chunk_count = :actual WHERE id = :doc_id"),
                {"actual": actual, "doc_id": doc_id},
            )
            fixed_count += 1

        return HealthCheckResult(
            name="chunk_count_sync",
            status="fixed",
            message=f"Fixed chunk_count for {fixed_count} documents",
            fixed=fixed_count,
            details={
                "examples": [
                    {"id": r[0][:8], "title": r[1][:30], "was": r[2], "now": r[3]}
                    for r in mismatches[:5]
                ]
            },
        )

    except Exception as e:
        if "does not exist" in str(e):
            return HealthCheckResult(
                name="chunk_count_sync",
                status="ok",
                message="Tables not yet created - skipping chunk_count sync",
            )
        return HealthCheckResult(
            name="chunk_count_sync",
            status="error",
            message=f"Chunk count sync check failed: {e}",
        )


def _check_orphan_embeddings(session) -> HealthCheckResult:
    """Check 3: Detect orphan embeddings (embeddings without a parent document)."""
    try:
        result = session.execute(text("""
            SELECT de.document_id, COUNT(*) as count
            FROM document_embeddings de
            LEFT JOIN documents d ON de.document_id = d.id
            WHERE d.id IS NULL
            GROUP BY de.document_id
        """))
        orphans = result.fetchall()

        if not orphans:
            return HealthCheckResult(
                name="orphan_embeddings",
                status="ok",
                message="No orphan embeddings found",
            )

        total = sum(row[1] for row in orphans)

        # Orphan embeddings are a warning - don't auto-delete as it's destructive
        return HealthCheckResult(
            name="orphan_embeddings",
            status="warning",
            message=(
                f"Found {total} orphan embeddings across {len(orphans)} missing documents. "
                f"Run POST /api/admin/maintenance/cleanup-orphans to clean up."
            ),
            details={
                "total_orphan_embeddings": total,
                "missing_document_ids": [row[0][:8] + "..." for row in orphans[:5]],
            },
        )

    except Exception as e:
        if "does not exist" in str(e):
            return HealthCheckResult(
                name="orphan_embeddings",
                status="ok",
                message="Tables not yet created - skipping orphan check",
            )
        return HealthCheckResult(
            name="orphan_embeddings",
            status="error",
            message=f"Orphan embeddings check failed: {e}",
        )


def _check_bm25_sync(session) -> HealthCheckResult:
    """Check 4: Verify BM25 index is in sync with embeddings."""
    try:
        # Get actual embedding count from DB
        result = session.execute(text(
            "SELECT COUNT(*) FROM document_embeddings"
        ))
        db_count = result.scalar() or 0

        # Get BM25 index count
        try:
            from services.bm25_service import BM25IndexService
            bm25 = BM25IndexService()
            bm25_count = len(bm25._chunk_metadata)
        except Exception:
            bm25_count = 0

        if db_count == 0 and bm25_count == 0:
            return HealthCheckResult(
                name="bm25_sync",
                status="ok",
                message="No embeddings - BM25 index empty as expected",
            )

        # Allow some tolerance (BM25 might exclude empty chunks)
        diff = abs(db_count - bm25_count)
        threshold = max(1, int(db_count * 0.05))  # 5% tolerance

        if diff <= threshold:
            return HealthCheckResult(
                name="bm25_sync",
                status="ok",
                message=f"BM25 index in sync (DB: {db_count}, BM25: {bm25_count})",
            )

        # Auto-fix: rebuild BM25 index
        logger.info(
            f"[Feature #348] BM25 index out of sync (DB: {db_count}, BM25: {bm25_count}) "
            f"- rebuilding..."
        )
        try:
            rebuilt_count = bm25.rebuild_from_embedding_store()
            return HealthCheckResult(
                name="bm25_sync",
                status="fixed",
                message=f"Rebuilt BM25 index: {bm25_count} -> {rebuilt_count} chunks (DB has {db_count})",
                fixed=1,
                details={"db_count": db_count, "old_bm25": bm25_count, "new_bm25": rebuilt_count},
            )
        except Exception as rebuild_err:
            return HealthCheckResult(
                name="bm25_sync",
                status="warning",
                message=f"BM25 out of sync (DB: {db_count}, BM25: {bm25_count}). Rebuild failed: {rebuild_err}",
                details={"db_count": db_count, "bm25_count": bm25_count},
            )

    except Exception as e:
        if "does not exist" in str(e):
            return HealthCheckResult(
                name="bm25_sync",
                status="ok",
                message="Tables not yet created - skipping BM25 sync check",
            )
        return HealthCheckResult(
            name="bm25_sync",
            status="error",
            message=f"BM25 sync check failed: {e}",
        )
