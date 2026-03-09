"""TMDB routes — trigger batch sync, check last sync."""

from flask import Blueprint, request

from app.models.sync_log import SyncLog
from app.helper.auth_middleware import admin_required
from app.helper.tmdb_helper import serialize_sync_log
from app.helper.base_response import response_success
from app.helper.error_handler import handle_errors
from app.schema.tmdb_schema import SyncMoviesRequestSchema, SyncBatchResponseSchema, SyncStopRequestSchema
from app.services import tmdb_service

tmdb_bp = Blueprint("tmdb", __name__)


@tmdb_bp.route("/sync/movies", methods=["POST"])
@admin_required
@handle_errors
def trigger_movie_sync():
    """Sync movies from TMDB (batch, one page per call).

    Body parameters (JSON):
        mode: "full" (default) or "changes" (incremental, last 14 days)
        endpoint: TMDB endpoint path (e.g. "/movie/popular") — only for full mode
        page: Page number to process (default 1) — only for full mode
        max_pages: Integer (1-500) to limit pages per endpoint
    """
    body = SyncMoviesRequestSchema(**request.get_json() or {})

    if body.mode == "changes":
        data = tmdb_service.sync_movies_changes(
            page=body.page,
            max_pages=body.max_pages,
            sync_log_id=body.sync_log_id,
        )
    else:
        # Full sync — process one page
        data = tmdb_service.sync_movies_batch(
            endpoint=body.endpoint,
            page=body.page,
            max_pages=body.max_pages,
            sync_log_id=body.sync_log_id,
        )

    response_data = SyncBatchResponseSchema(**data).model_dump()

    msg = (
        "Sync completed"
        if data["status"] == "completed"
        else f"Batch processed: {data['endpoint']} page {data['current_page']}"
    )
    status_code = 200 if data["status"] == "completed" else 202

    return response_success(msg, data=response_data, status_code=status_code)


@tmdb_bp.route("/sync/last-sync")
@admin_required
@handle_errors
def get_last_sync():
    """Get the last completed sync log from the database."""
    log = SyncLog.query.order_by(SyncLog.created_at.desc()).first()
    if not log:
        return response_success("No sync has been run yet", data=None)
    return response_success("Last sync retrieved", data=serialize_sync_log(log))


@tmdb_bp.route("/sync/stop", methods=["POST"])
@admin_required
@handle_errors
def stop_movie_sync():
    """
    Manually mark a running batch sync as stopped.
    
    Body parameters (JSON):
        sync_log_id: UUID of the SyncLog to stop
    """
    body = SyncStopRequestSchema(**request.get_json() or {})
    data = tmdb_service.stop_sync_batch(body.sync_log_id)
    return response_success("Sync stopped successfully", data=data)
