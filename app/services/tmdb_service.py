"""TMDB sync service — frontend-driven batch architecture.

- sync_movies_batch(): Process a single TMDB page synchronously (frontend calls repeatedly)
- sync_movies_changes(): Incremental sync via TMDB /movie/changes API (single call)
- fetch_and_cache_videos(): On-demand video fetch for movie detail (cache in DB)

All sync operations are synchronous — no background threads.
The frontend drives full sync by calling sync_movies_batch() page-by-page.
"""

from datetime import datetime, timezone, timedelta

import requests

from app.extensions import db
from app.models.movie import Movie
from app.models.movie_video import MovieVideo
from app.models.sync_log import SyncLog
from app.helper import logger as app_logger
from app.helper.tmdb_helper import (
    BATCH_SIZE,
    batched,
    sync_genres,
    process_movie_batch,
    fetch_changed_movie_ids_page,
    fetch_movie_detail,
    fetch_movie_videos,
    fetch_single_page,
    serialize_sync_log,
)

# ─── ORDERED ENDPOINTS FOR FULL SYNC ─────────────────────────────────────────
SYNC_ENDPOINTS = [
    "/movie/popular",
    "/movie/now_playing",
]


# ══════════════════════════════════════════════════════════════════════════════
# 1. BATCH SYNC — process one page at a time (frontend-driven)
# ══════════════════════════════════════════════════════════════════════════════


def sync_movies_batch(endpoint=None, page=1, max_pages=None, sync_log_id=None):
    """Process a single TMDB page synchronously.

    If endpoint is None, this is the initial call — sync genres and return
    the first endpoint + page for the frontend to begin fetching.

    Args:
        endpoint: TMDB endpoint path, e.g. "/movie/popular"
        page: Page number to fetch (1-indexed)
        max_pages: Optional cap per endpoint
        sync_log_id: UUID string of the current Sync log to append progress to.

    Returns:
        dict with batch results and next_endpoint/next_page info
    """
    try:
        # ── Initial call: sync genres, return starting point ──
        if endpoint is None:
            # Check if there is an active sync already running
            active_sync = SyncLog.query.filter_by(status="in_progress").first()

            if active_sync:
                from app.helper.error_handler import ConflictError

                raise ConflictError(
                    error="Active sync process detected. Please wait for the current process to complete before starting a new one. This happen because another admin is running the sync process. This happen because another admin is running the sync process.",
                    message="Sync in progress",
                )

            genre_map = sync_genres()
            first_endpoint = SYNC_ENDPOINTS[0]

            # Create a new SyncLog entry to track this sync session
            sync_log = SyncLog(
                sync_type="full",
                last_sync_at=datetime.now(timezone.utc),
                total_inserted=0,
                total_updated=0,
                status="in_progress",
                last_synced_endpoint=first_endpoint,
                last_synced_page=0,
            )
            db.session.add(sync_log)
            db.session.commit()

            app_logger.json_logger.info(
                f"[batch] Sync session started, genres synced. "
                f"sync_log_id={sync_log.id}"
            )

            return {
                "status": "in_progress",
                "endpoint": first_endpoint,
                "current_page": 0,
                "next_endpoint": first_endpoint,
                "next_page": 1,
                "total_pages": None,
                "batch_inserted": 0,
                "batch_updated": 0,
                "cumulative_inserted": 0,
                "cumulative_updated": 0,
                "sync_log_id": str(sync_log.id),
            }

        # ── Validate endpoint ──
        if endpoint not in SYNC_ENDPOINTS:
            raise ValueError(f"Invalid endpoint: {endpoint}. Valid: {SYNC_ENDPOINTS}")

        # ── Pre-check: Abort if sync was manually stopped ──
        if sync_log_id:
            current_log = SyncLog.query.get(sync_log_id)
            if current_log and current_log.status == "stopped":
                return {
                    "status": "stopped",
                    "endpoint": endpoint,
                    "current_page": page,
                    "next_endpoint": None,
                    "next_page": None,
                    "total_pages": None,
                    "batch_inserted": 0,
                    "batch_updated": 0,
                    "cumulative_inserted": current_log.total_inserted,
                    "cumulative_updated": current_log.total_updated,
                    "sync_log_id": sync_log_id,
                }

        # ── Fetch + process one page ──
        genre_map = sync_genres()  # Idempotent, won't re-insert existing
        movies, total_pages = fetch_single_page(endpoint, page)

        # Apply max_pages cap
        effective_max = total_pages
        if max_pages is not None:
            effective_max = min(total_pages, max_pages)

        batch_inserted = 0
        batch_updated = 0

        if movies:
            batch = [(endpoint, page, m) for m in movies]
            batch_inserted, batch_updated, _, _ = process_movie_batch(batch, genre_map)
            db.session.commit()

        app_logger.json_logger.info(
            f"[batch] {endpoint} page {page}/{effective_max}: "
            f"+{batch_inserted} new, ~{batch_updated} updated"
        )

        # ── Determine next step ──
        next_endpoint = None
        next_page = None
        status = "in_progress"

        if page < effective_max:
            if max_pages is not None and page >= max_pages:
                status = "completed"
            else:
                next_endpoint = endpoint
                next_page = page + 1
        else:
            if max_pages is not None:
                # If frontend explicitly set a max page limit, we complete the entire sync
                # here instead of jumping to the next endpoint list.
                status = "completed"
            else:
                # Move to next endpoint
                current_idx = SYNC_ENDPOINTS.index(endpoint)
                if current_idx + 1 < len(SYNC_ENDPOINTS):
                    next_endpoint = SYNC_ENDPOINTS[current_idx + 1]
                    next_page = 1
                else:
                    # All endpoints done
                    status = "completed"

        # ── Update SyncLog ──
        sync_log = None
        if sync_log_id:
            sync_log = SyncLog.query.get(sync_log_id)
        else:
            # Fallback for backward compatibility or if frontend forgot it
            sync_log = (
                SyncLog.query.filter_by(sync_type="full", status="in_progress")
                .order_by(SyncLog.created_at.desc())
                .first()
            )

        if sync_log:
            sync_log.total_inserted += batch_inserted
            sync_log.total_updated += batch_updated
            sync_log.last_synced_endpoint = endpoint
            sync_log.last_synced_page = page
            # If we are resuming after a failure, mark it back to in_progress
            if sync_log.status == "failed":
                sync_log.status = "in_progress"
                sync_log.error_message = None

            if sync_log.status == "stopped":
                status = "stopped"
                next_endpoint = None
                next_page = None
            elif status == "completed":
                sync_log.status = "success"
                
            db.session.commit()

            cumulative_inserted = sync_log.total_inserted
            cumulative_updated = sync_log.total_updated
            returned_sync_log_id = str(sync_log.id)
        else:
            cumulative_inserted = batch_inserted
            cumulative_updated = batch_updated
            returned_sync_log_id = None

        return {
            "status": status,
            "endpoint": endpoint,
            "current_page": page,
            "next_endpoint": next_endpoint,
            "next_page": next_page,
            "total_pages": effective_max,
            "batch_inserted": batch_inserted,
            "batch_updated": batch_updated,
            "cumulative_inserted": cumulative_inserted,
            "cumulative_updated": cumulative_updated,
            "sync_log_id": returned_sync_log_id,
        }

    except Exception as e:
        db.session.rollback()
        app_logger.json_logger.error(f"[batch] Sync failed: {e}", exc_info=True)

        # Mark sync log as failed if one exists
        log = None
        if sync_log_id:
            log = SyncLog.query.get(sync_log_id)
        if not log:
            log = (
                SyncLog.query.filter_by(sync_type="full", status="in_progress")
                .order_by(SyncLog.created_at.desc())
                .first()
            )

        if log:
            log.status = "failed"
            log.error_message = str(e)
            db.session.commit()

        raise


def stop_sync_batch(sync_log_id: str):
    """Mark an ongoing sync session as stopped."""
    sync_log = SyncLog.query.get(sync_log_id)
    if not sync_log:
        from app.helper.error_handler import NotFoundError

        raise NotFoundError(error=f"Sync log {sync_log_id} not found")

    if sync_log.status == "in_progress":
        sync_log.status = "stopped"
        db.session.commit()
        app_logger.json_logger.info(f"[batch] Sync {sync_log_id} manually stopped.")

    return serialize_sync_log(sync_log)


# ══════════════════════════════════════════════════════════════════════════════
# 2. INCREMENTAL SYNC — only changed movies via /movie/changes
# ══════════════════════════════════════════════════════════════════════════════


def sync_movies_changes(page=1, max_pages=None, sync_log_id=None):
    """
    Incremental sync: only update movies that changed in the last 14 days.
    Uses TMDB /movie/changes API, then updates matching movies in our DB.
    Runs synchronously page-by-page.
    """
    sync_start = datetime.now(timezone.utc)
    batch_inserted = 0
    batch_updated = 0
    status = "in_progress"

    end_date = sync_start.date()
    start_date = end_date - timedelta(days=14)

    # Initial call logic
    if not sync_log_id:
        # Check if there is an active sync already running
        active_sync = SyncLog.query.filter_by(status="in_progress").first()
        if active_sync:
            from app.helper.error_handler import ConflictError

            raise ConflictError(
                error="Active sync process detected. Please wait for the current process to complete before starting a new one. This happen because another admin is running the sync process.",
                message="Sync in progress",
            )

        sync_log = SyncLog(
            sync_type="changes",
            last_sync_at=sync_start,
            total_inserted=0,
            total_updated=0,
            status="in_progress",
            last_synced_endpoint="changes",
            last_synced_page=0,
        )
        db.session.add(sync_log)
        db.session.commit()
        sync_log_id = str(sync_log.id)
        app_logger.json_logger.info(
            f"[changes] Sync session started. sync_log_id={sync_log_id}"
        )

    try:
        # Pre-check if sync was manually stopped
        if sync_log_id:
            current_log = SyncLog.query.get(sync_log_id)
            if current_log and current_log.status == "stopped":
                return {
                    "status": "stopped",
                    "endpoint": "changes",
                    "current_page": page,
                    "next_endpoint": None,
                    "next_page": None,
                    "total_pages": None,
                    "batch_inserted": 0,
                    "batch_updated": 0,
                    "cumulative_inserted": current_log.total_inserted,
                    "cumulative_updated": current_log.total_updated,
                    "sync_log_id": sync_log_id,
                }

        app_logger.json_logger.info(
            f"[changes] Fetching changed movie IDs from {start_date} to {end_date} (page {page})"
        )

        changed_tmdb_ids, total_pages = fetch_changed_movie_ids_page(
            start_date, end_date, page
        )

        effective_max = total_pages
        if max_pages is not None:
            effective_max = min(total_pages, max_pages)

        app_logger.json_logger.info(
            f"[changes] Found {len(changed_tmdb_ids)} changed movies on TMDB, page {page}/{effective_max}"
        )

        if changed_tmdb_ids:
            # Find which of these changed movies exist in our DB
            existing_movies = {
                m.api_id: m
                for m in Movie.query.filter(
                    Movie.api_id.in_(list(changed_tmdb_ids)),
                    Movie.source == "tmdb",
                ).all()
            }

            if existing_movies:
                app_logger.json_logger.info(
                    f"[changes] {len(existing_movies)} changed movies exist in our DB, updating..."
                )

                genre_map = sync_genres()

                # Process in chunks with commit per chunk
                movie_ids_list = list(existing_movies.keys())
                import concurrent.futures

                for chunk_ids in batched(movie_ids_list, BATCH_SIZE):
                    tmdb_data_results = []

                    # Fetch TMDB data concurrently (no DB operations inside threads)
                    with concurrent.futures.ThreadPoolExecutor(
                        max_workers=10
                    ) as executor:
                        future_to_id = {
                            executor.submit(fetch_movie_detail, api_id): api_id
                            for api_id in chunk_ids
                        }
                        for future in concurrent.futures.as_completed(future_to_id):
                            api_id = future_to_id[future]
                            try:
                                tmdb_data = future.result()
                                tmdb_data_results.append((api_id, tmdb_data))
                            except requests.RequestException as e:
                                app_logger.json_logger.warning(
                                    f"[changes] Failed to fetch movie {api_id}: {e}"
                                )
                                continue

                    # Process the fetched data sequentially to avoid DB locks
                    for api_id, tmdb_data in tmdb_data_results:
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

                        # Update genres from detail response
                        tmdb_genres = tmdb_data.get("genres", [])
                        movie.genres = [
                            genre_map[g["id"]]
                            for g in tmdb_genres
                            if g["id"] in genre_map
                        ]

                        batch_updated += 1

                    db.session.commit()

        # Update sync log
        sync_log = SyncLog.query.get(sync_log_id)
        if sync_log:
            sync_log.total_updated += batch_updated
            sync_log.last_synced_page = page

            if sync_log.status == "failed":
                sync_log.status = "in_progress"
                sync_log.error_message = None

            if sync_log.status == "stopped":
                status = "stopped"
                next_page = None
            elif page < effective_max:
                if max_pages is not None and page >= max_pages:
                    status = "completed"
                    next_page = None
                else:
                    next_page = page + 1
            else:
                next_page = None
                if max_pages is not None:
                    status = "completed"
                else:
                    status = "completed"

            if next_page is None:
                sync_log.status = "success"
                status = "completed"

            db.session.commit()

            cumulative_inserted = sync_log.total_inserted
            cumulative_updated = sync_log.total_updated
        else:
            cumulative_inserted = 0
            cumulative_updated = batch_updated

            if page < effective_max:
                if max_pages is not None and page >= max_pages:
                    status = "completed"
                    next_page = None
                else:
                    next_page = page + 1
            else:
                next_page = None
                status = "completed"

            if next_page is None:
                status = "completed"

        return {
            "status": status,
            "endpoint": "changes",
            "current_page": page,
            "next_endpoint": "changes" if next_page else None,
            "next_page": next_page,
            "total_pages": total_pages,
            "batch_inserted": batch_inserted,
            "batch_updated": batch_updated,
            "cumulative_inserted": cumulative_inserted,
            "cumulative_updated": cumulative_updated,
            "sync_log_id": sync_log_id,
        }

    except Exception as e:
        db.session.rollback()
        app_logger.json_logger.error(f"Incremental sync failed: {e}", exc_info=True)

        sync_log = SyncLog.query.get(sync_log_id)
        if sync_log:
            sync_log.status = "failed"
            sync_log.error_message = str(e)
            db.session.commit()

        raise


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
