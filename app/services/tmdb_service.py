"""TMDB sync service — simplified architecture.

- sync_movies(): Bulk sync movies + basic poster/backdrop from TMDB list endpoints
- sync_movies_changes(): Incremental sync via TMDB /movie/changes API
- fetch_and_cache_videos(): On-demand video fetch for movie detail (cache in DB)

All sync operations run in background ThreadPoolExecutor with live status tracking.
"""

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta

import requests
from flask import current_app

from app.extensions import db
from app.models.movie import Movie
from app.models.movie_video import MovieVideo
from app.models.sync_log import SyncLog
from app.helper import logger as app_logger
from app.helper.tmdb_helper import (
    BATCH_SIZE,
    batched,
    iter_unique_movies,
    sync_genres,
    process_movie_batch,
    fetch_changed_movie_ids,
    fetch_movie_detail,
    fetch_movie_videos,
    serialize_sync_log,
)
from sqlalchemy import or_

# ─── ORDERED ENDPOINTS FOR FULL SYNC ─────────────────────────────────────────
SYNC_ENDPOINTS = [
    ("/movie/popular", None),
    ("/movie/now_playing", 3),
]

# ─── IN-MEMORY SYNC STATE ────────────────────────────────────────────────────

_sync_lock = threading.Lock()
_sync_state = {
    "is_running": False,
    "type": None,
    "total_processed": 0,
    "total_inserted": 0,
    "total_updated": 0,
    "current_endpoint": None,
    "current_page": None,
    "started_at": None,
    "finished_at": None,
    "error": None,
    "stop_requested": False,
}

_executor = ThreadPoolExecutor(max_workers=2)


def _reset_state(sync_type):
    """Reset in-memory state for a new sync run."""
    _sync_state.update(
        {
            "is_running": True,
            "type": sync_type,
            "total_processed": 0,
            "total_inserted": 0,
            "total_updated": 0,
            "current_endpoint": None,
            "current_page": None,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "finished_at": None,
            "error": None,
            "stop_requested": False,
        }
    )


# ══════════════════════════════════════════════════════════════════════════════
# 1. FULL SYNC — movies from /movie/popular + /movie/now_playing
# ══════════════════════════════════════════════════════════════════════════════


def sync_movies(resume=False, max_pages=None):
    """Sync movies from TMDB list endpoints (all available pages)."""
    sync_start = datetime.now(timezone.utc)
    total_inserted = 0
    total_updated = 0
    status = "success"
    last_endpoint = None
    last_page = None
    error_message = None

    resume_endpoint = None
    resume_page = None

    if resume:
        last_failed = (
            SyncLog.query.filter(
                or_(SyncLog.status == "failed", SyncLog.status == "stopped")
            )
            .order_by(SyncLog.created_at.desc())
            .first()
        )
        if last_failed and last_failed.last_synced_endpoint:
            resume_endpoint = last_failed.last_synced_endpoint
            resume_page = last_failed.last_synced_page
            app_logger.json_logger.info(
                f"Resuming sync from endpoint={resume_endpoint}, page={resume_page}"
            )

    try:
        genre_map = sync_genres()

        endpoints = SYNC_ENDPOINTS
        if max_pages is not None:
            endpoints = [
                (ep, min(mp, max_pages) if mp else max_pages)
                for ep, mp in SYNC_ENDPOINTS
            ]

        movie_stream = iter_unique_movies(
            endpoints,
            resume_endpoint=resume_endpoint,
            resume_page=resume_page,
        )

        for batch in batched(movie_stream, BATCH_SIZE):
            if _sync_state["stop_requested"]:
                status = "stopped"
                app_logger.json_logger.info("Movie sync stopped by user request.")
                break

            inserted, updated, last_endpoint, last_page = process_movie_batch(
                batch, genre_map
            )
            total_inserted += inserted
            total_updated += updated

            db.session.commit()

            # Update live state
            _sync_state["total_inserted"] = total_inserted
            _sync_state["total_updated"] = total_updated
            _sync_state["total_processed"] = total_inserted + total_updated
            _sync_state["current_endpoint"] = last_endpoint
            _sync_state["current_page"] = last_page

            app_logger.json_logger.info(
                f"[movies] Batch done: +{inserted} new, ~{updated} updated "
                f"(total: {total_inserted} new, {total_updated} updated) "
                f"[{last_endpoint} page {last_page}]"
            )

    except Exception as e:
        db.session.rollback()
        status = "failed"
        error_message = str(e)
        app_logger.json_logger.error(f"Movie sync failed: {e}", exc_info=True)

    finally:
        sync_log = SyncLog(
            last_sync_at=sync_start,
            total_inserted=total_inserted,
            total_updated=total_updated,
            status=status,
            last_synced_endpoint=last_endpoint,
            last_synced_page=last_page,
            error_message=error_message,
        )
        db.session.add(sync_log)
        db.session.commit()

    return serialize_sync_log(sync_log)


# ══════════════════════════════════════════════════════════════════════════════
# 2. INCREMENTAL SYNC — only changed movies via /movie/changes
# ══════════════════════════════════════════════════════════════════════════════


def sync_movies_changes():
    """
    Incremental sync: only update movies that changed in the last 14 days.
    Uses TMDB /movie/changes API, then updates matching movies in our DB.
    """
    sync_start = datetime.now(timezone.utc)
    total_inserted = 0
    total_updated = 0
    status = "success"
    error_message = None

    try:
        end_date = datetime.now(timezone.utc).date()
        start_date = end_date - timedelta(days=14)

        app_logger.json_logger.info(
            f"[changes] Fetching changed movie IDs from {start_date} to {end_date}"
        )

        changed_tmdb_ids = fetch_changed_movie_ids(start_date, end_date)
        app_logger.json_logger.info(
            f"[changes] Found {len(changed_tmdb_ids)} changed movies on TMDB"
        )

        if not changed_tmdb_ids:
            app_logger.json_logger.info("[changes] No changes found, skipping.")
            status = "success"
            return

        # Find which of these changed movies exist in our DB
        existing_movies = {
            m.api_id: m
            for m in Movie.query.filter(
                Movie.api_id.in_(list(changed_tmdb_ids)),
                Movie.source == "tmdb",
            ).all()
        }

        if not existing_movies:
            app_logger.json_logger.info(
                "[changes] None of the changed movies exist in our DB."
            )
            status = "success"
            return

        app_logger.json_logger.info(
            f"[changes] {len(existing_movies)} changed movies exist in our DB, updating..."
        )

        genre_map = sync_genres()

        # Process in chunks
        movie_ids_list = list(existing_movies.keys())
        for chunk_ids in batched(movie_ids_list, BATCH_SIZE):
            if _sync_state["stop_requested"]:
                status = "stopped"
                app_logger.json_logger.info("Incremental sync stopped by user request.")
                break

            for api_id in chunk_ids:
                try:
                    tmdb_data = fetch_movie_detail(api_id)
                except requests.RequestException as e:
                    app_logger.json_logger.warning(
                        f"[changes] Failed to fetch movie {api_id}: {e}"
                    )
                    continue

                movie = existing_movies[api_id]

                # Update fields
                movie.title = tmdb_data.get("title", movie.title)
                movie.overview = tmdb_data.get("overview", movie.overview)
                movie.popularity = tmdb_data.get("popularity", movie.popularity)
                movie.rating = tmdb_data.get("vote_average", movie.rating)

                release_str = tmdb_data.get("release_date")
                if release_str:
                    try:
                        movie.release_date = datetime.strptime(
                            release_str, "%Y-%m-%d"
                        ).date()
                    except ValueError:
                        pass

                # Update genres from detail response (uses "genres" not "genre_ids")
                tmdb_genres = tmdb_data.get("genres", [])
                movie.genres = [
                    genre_map[g["id"]] for g in tmdb_genres if g["id"] in genre_map
                ]

                total_updated += 1

            db.session.commit()

            _sync_state["total_updated"] = total_updated
            _sync_state["total_processed"] = total_updated

            app_logger.json_logger.info(
                f"[changes] Chunk done: {total_updated} movies updated"
            )

    except Exception as e:
        db.session.rollback()
        status = "failed"
        error_message = str(e)
        app_logger.json_logger.error(f"Incremental sync failed: {e}", exc_info=True)

    finally:
        sync_log = SyncLog(
            last_sync_at=sync_start,
            total_inserted=total_inserted,
            total_updated=total_updated,
            status=status,
            last_synced_endpoint="changes",
            last_synced_page=None,
            error_message=error_message,
        )
        db.session.add(sync_log)
        db.session.commit()

    return serialize_sync_log(sync_log)


# ══════════════════════════════════════════════════════════════════════════════
# 3. ON-DEMAND VIDEO FETCH (cache in DB)
# ══════════════════════════════════════════════════════════════════════════════


def fetch_and_cache_videos(movie):
    """
    On-demand video fetch: if movie has no videos in DB, fetch from TMDB and cache.
    Only for source='tmdb' movies with an api_id.

    Args:
        movie: Movie model instance (with videos relationship loaded)

    Returns:
        list of MovieVideo instances
    """
    # Already have videos cached — return them
    if movie.videos:
        return movie.videos

    # Only fetch for TMDB-sourced movies
    if movie.source != "tmdb" or not movie.api_id:
        return []

    videos = fetch_movie_videos(movie.api_id)
    if not videos:
        return []

    # Deduplicate by video_key
    existing_keys = set(
        row[0]
        for row in db.session.query(MovieVideo.video_key)
        .filter(MovieVideo.movie_id == movie.id)
        .all()
    )

    new_videos = []
    for v in videos[:5]:  # Limit to 5 videos per movie
        video_type = v.get("type", "").lower()
        if video_type not in ("trailer", "teaser"):
            continue
        site = v.get("site", "").lower()
        if site not in ("youtube", "vimeo"):
            continue
        key = v.get("key", "")
        if key in existing_keys:
            continue
        existing_keys.add(key)

        new_videos.append(
            MovieVideo(
                movie_id=movie.id,
                video_type=video_type,
                site=site,
                video_key=key,
                official=v.get("official", False),
            )
        )

    if new_videos:
        db.session.bulk_save_objects(new_videos)
        db.session.commit()

        # Refresh movie.videos to include newly saved records
        db.session.refresh(movie)

    return movie.videos


# ══════════════════════════════════════════════════════════════════════════════
# BACKGROUND RUNNER
# ══════════════════════════════════════════════════════════════════════════════

_SYNC_FUNCTIONS = {
    "movies": sync_movies,
    "changes": sync_movies_changes,
}


def start_sync_background(sync_type, resume=False, max_pages=None):
    """
    Start a sync in a background thread.

    Args:
        sync_type: "movies" or "changes"
        resume: Only applies to "movies" sync

    Returns:
        dict with sync start info

    Raises:
        ValueError: If sync is already running or invalid type
    """
    if sync_type not in _SYNC_FUNCTIONS:
        raise ValueError(
            f"Invalid sync type: {sync_type}. Valid: {list(_SYNC_FUNCTIONS.keys())}"
        )

    with _sync_lock:
        if _sync_state["is_running"]:
            raise ValueError(
                f"A sync is already running (type={_sync_state['type']}). "
                "Check GET /sync/status for progress."
            )
        _reset_state(sync_type)

    app = current_app._get_current_object()
    sync_fn = _SYNC_FUNCTIONS[sync_type]

    def _run():
        try:
            with app.app_context():
                if sync_type == "movies":
                    sync_fn(resume=resume, max_pages=max_pages)
                else:
                    sync_fn()
        except Exception as e:
            _sync_state["error"] = str(e)
            app_logger.json_logger.error(
                f"Background {sync_type} sync failed: {e}", exc_info=True
            )
        finally:
            _sync_state["is_running"] = False
            _sync_state["finished_at"] = datetime.now(timezone.utc).isoformat()

    _executor.submit(_run)

    return {
        "message": f"{sync_type.capitalize()} sync started in background",
        "type": sync_type,
        "started_at": _sync_state["started_at"],
    }


# ══════════════════════════════════════════════════════════════════════════════
# STATUS
# ══════════════════════════════════════════════════════════════════════════════


def stop_sync():
    """Request a running sync to stop."""
    with _sync_lock:
        if not _sync_state["is_running"]:
            return {"message": "No sync is currently running."}
        _sync_state["stop_requested"] = True
        return {"message": "Stop requested. Sync will halt after the current batch."}


def get_sync_status():
    """
    Get sync status.

    If a sync is running, return live in-memory state.
    Otherwise, return the most recent SyncLog from DB.
    """
    if _sync_state["is_running"]:
        return {
            "is_running": True,
            "type": _sync_state["type"],
            "total_processed": _sync_state["total_processed"],
            "total_inserted": _sync_state["total_inserted"],
            "total_updated": _sync_state["total_updated"],
            "current_endpoint": _sync_state["current_endpoint"],
            "current_page": _sync_state["current_page"],
            "started_at": _sync_state["started_at"],
            "error": _sync_state["error"],
            "stop_requested": _sync_state.get("stop_requested", False),
        }

    if _sync_state.get("finished_at"):
        return {
            "is_running": False,
            "type": _sync_state["type"],
            "total_processed": _sync_state["total_processed"],
            "total_inserted": _sync_state["total_inserted"],
            "total_updated": _sync_state["total_updated"],
            "started_at": _sync_state["started_at"],
            "finished_at": _sync_state["finished_at"],
            "error": _sync_state["error"],
            "stop_requested": False,
        }

    log = SyncLog.query.order_by(SyncLog.created_at.desc()).first()
    if not log:
        return {"is_running": False, "message": "No sync has been run yet."}
    return serialize_sync_log(log)
