"""TMDB routes — trigger sync, stop sync, check status."""

from flask import Blueprint, request

from app.models.sync_log import SyncLog
from app.helper.auth_middleware import admin_required
from app.helper.tmdb_helper import serialize_sync_log
from app.helper.base_response import response_success
from app.helper.error_handler import handle_errors
from app.schema.tmdb_schema import SyncMoviesRequestSchema, SyncStartedDataSchema, SyncStopResponseDataSchema
from app.services import tmdb_service

tmdb_bp = Blueprint("tmdb", __name__)


@tmdb_bp.route("/sync/movies", methods=["POST"])
@admin_required
@handle_errors
def trigger_movie_sync():
    """Sync movies from TMDB (background).

    Body parameters (JSON):
        mode: "full" (default) or "changes" (incremental, last 14 days)
        resume: true/false (resume from last failed position, full mode only)
        max_pages: Integer (1-500) to limit number of pages to sync
    """
    body = SyncMoviesRequestSchema(**request.get_json() or {})

    sync_type = "changes" if body.mode == "changes" else "movies"

    try:
        data = tmdb_service.start_sync_background(
            sync_type, resume=body.resume, max_pages=body.max_pages
        )
    except ValueError as e:
        return response_success(str(e), status_code=409)

    response_data = SyncStartedDataSchema(**data).model_dump()

    msg = (
        "Incremental sync started (last 14 days changes)"
        if sync_type == "changes"
        else "Full movie sync started in background"
    )
    return response_success(msg, data=response_data, status_code=202)


@tmdb_bp.route("/sync/stop", methods=["POST"])
@admin_required
@handle_errors
def stop_movie_sync():
    """Stop a currently running sync."""
    data = tmdb_service.stop_sync()
    response_data = SyncStopResponseDataSchema(**data).model_dump()
    return response_success(data["message"], data=response_data)


@tmdb_bp.route("/sync/status")
@admin_required
@handle_errors
def get_sync_status():
    """Get current sync status (live progress or last completed sync)."""
    data = tmdb_service.get_sync_status()
    return response_success("Sync status retrieved", data=data)


@tmdb_bp.route("/sync/last-sync")
@admin_required
@handle_errors
def get_last_sync():
    """Get the last completed sync log from the database."""
    log = SyncLog.query.order_by(SyncLog.created_at.desc()).first()
    if not log:
        return response_success("No sync has been run yet", data=None)
    return response_success("Last sync retrieved", data=serialize_sync_log(log))
