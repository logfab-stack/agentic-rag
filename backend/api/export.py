"""
Export API Endpoints

Handles exporting analysis results to CSV format.
"""

import csv
import io
import logging
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

router = APIRouter()


class ExportRequest(BaseModel):
    """Request model for exporting results."""
    data: List[Dict[str, Any]]
    filename: Optional[str] = "export.csv"
    columns: Optional[List[str]] = None


@router.post("/results")
async def export_results(request: ExportRequest):
    """
    Export analysis results as CSV file.

    Args:
        request: ExportRequest with data, filename, and optional column order

    Returns:
        StreamingResponse with CSV file
    """
    try:
        if not request.data:
            raise HTTPException(status_code=400, detail="No data provided for export")

        # Create CSV in memory
        output = io.StringIO()

        # Determine columns from the data
        if request.columns:
            fieldnames = request.columns
        else:
            # Get all unique keys from all rows
            fieldnames = list(dict.fromkeys(
                key for row in request.data for key in row.keys()
            ))

        writer = csv.DictWriter(output, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()

        for row in request.data:
            writer.writerow(row)

        # Reset position to start of StringIO
        output.seek(0)

        # Create response
        filename = request.filename if request.filename.endswith('.csv') else f"{request.filename}.csv"

        logger.info(f"Exporting {len(request.data)} rows to {filename}")

        return StreamingResponse(
            iter([output.getvalue()]),
            media_type="text/csv",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Cache-Control": "no-cache"
            }
        )

    except Exception as e:
        logger.error(f"Error exporting results: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to export results: {str(e)}")
