"""TMDB helper functions — API calls, generators, batch processing, serialization."""

from datetime import datetime
from itertools import islice

import requests

from app.extensions import db
from app.models.movie import Movie
from app.models.genre import Genre
from app.models.movie_image import MovieImage
from app.helper import logger as app_logger
from config import Config

BATCH_SIZE = 100

# TMDB API hard limit for paginated endpoints
TMDB_MAX_PAGES = 500


# ─── AUTH ─────────────────────────────────────────────────────────────────────


def get_headers():
    """Build TMDB API authorization headers."""
    token = Config.TMDB_ACCESS_TOKEN
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }


# ─── GENERIC UTILS ───────────────────────────────────────────────────────────


def batched(iterable, size):
    """Split iterable into chunks of `size`."""
    it = iter(iterable)
    while chunk := list(islice(it, size)):
        yield chunk


# ─── SINGLE PAGE FETCHER ─────────────────────────────────────────────────────


def fetch_single_page(endpoint, page):
    """Fetch exactly one page from a TMDB list endpoint.

    Returns:
        (movies_list, total_pages) — movies is a list of dicts, total_pages is
        the TMDB-reported total (capped at TMDB_MAX_PAGES).
    """
    if page > TMDB_MAX_PAGES:
        return [], TMDB_MAX_PAGES

    headers = get_headers()
    resp = requests.get(
        f"{Config.TMDB_BASE_URL}{endpoint}",
        headers=headers,
        params={"page": page, "language": "en-US"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    movies = data.get("results", [])
    total_pages = min(data.get("total_pages", 1), TMDB_MAX_PAGES)
    return movies, total_pages


# ─── GENRE SYNC ───────────────────────────────────────────────────────────────


def sync_genres():
    """Sync genres from TMDB, return dict {tmdb_genre_id: Genre object}."""
    headers = get_headers()
    try:
        resp = requests.get(
            f"{Config.TMDB_BASE_URL}/genre/movie/list",
            headers=headers,
            params={"language": "en-US"},
            timeout=10,
        )
        resp.raise_for_status()
        tmdb_genres = resp.json().get("genres", [])
    except requests.RequestException as e:
        app_logger.json_logger.warning(f"Failed to fetch TMDB genres: {e}")
        return {}

    existing = {g.name: g for g in Genre.query.all()}
    genre_map = {}
    new_genres = []

    for tg in tmdb_genres:
        if tg["name"] in existing:
            genre_map[tg["id"]] = existing[tg["name"]]
        else:
            genre = Genre(name=tg["name"])
            new_genres.append(genre)
            genre_map[tg["id"]] = genre

    if new_genres:
        db.session.bulk_save_objects(new_genres)
        db.session.commit()

        refreshed = {
            g.name: g
            for g in Genre.query.filter(
                Genre.name.in_([g.name for g in new_genres])
            ).all()
        }
        for tmdb_id, genre in genre_map.items():
            if genre.id is None:
                genre_map[tmdb_id] = refreshed[genre.name]

    return genre_map


# ─── MOVIE BATCH PROCESSOR ───────────────────────────────────────────────────


def process_movie_batch(batch, genre_map):
    """
    Process one batch of movies — upsert movie + basic images (poster/backdrop).
    Idempotent: checks api_id for duplicates, skips existing images by URL.

    Returns:
        (inserted_count, updated_count, last_endpoint, last_page)
    """
    movie_dicts = [m for _, _, m in batch]
    last_endpoint = batch[-1][0]
    last_page = batch[-1][1]

    tmdb_ids = [str(m["id"]) for m in movie_dicts]

    existing_movies = {
        m.api_id: m for m in Movie.query.filter(Movie.api_id.in_(tmdb_ids)).all()
    }

    new_movies = []
    updated_count = 0
    new_images = []

    for tmdb_movie in movie_dicts:
        api_id = str(tmdb_movie["id"])
        is_new = api_id not in existing_movies

        if is_new:
            movie = Movie(api_id=api_id, source="tmdb")
            new_movies.append((movie, tmdb_movie))
        else:
            movie = existing_movies[api_id]
            updated_count += 1

        movie.title = tmdb_movie.get("title", "Untitled")
        movie.overview = tmdb_movie.get("overview")
        movie.popularity = tmdb_movie.get("popularity")
        movie.rating = tmdb_movie.get("vote_average")
        movie.status = "active"

        release_str = tmdb_movie.get("release_date")
        if release_str:
            try:
                movie.release_date = datetime.strptime(release_str, "%Y-%m-%d").date()
            except ValueError:
                pass

        if not is_new:
            tmdb_genre_ids = tmdb_movie.get("genre_ids", [])
            movie.genres = [
                genre_map[gid] for gid in tmdb_genre_ids if gid in genre_map
            ]

    # Insert new movies
    for movie, tmdb_movie in new_movies:
        db.session.add(movie)
        db.session.flush()

        tmdb_genre_ids = tmdb_movie.get("genre_ids", [])
        movie.genres = [genre_map[gid] for gid in tmdb_genre_ids if gid in genre_map]

        # Basic images from list response (poster + backdrop)
        poster_path = tmdb_movie.get("poster_path")
        if poster_path:
            new_images.append(
                MovieImage(
                    movie_id=movie.id,
                    image_type="poster",
                    image_url=f"{Config.TMDB_IMAGE_BASE}/w500{poster_path}",
                )
            )

        backdrop_path = tmdb_movie.get("backdrop_path")
        if backdrop_path:
            new_images.append(
                MovieImage(
                    movie_id=movie.id,
                    image_type="backdrop",
                    image_url=f"{Config.TMDB_IMAGE_BASE}/w1280{backdrop_path}",
                )
            )

    if new_images:
        db.session.bulk_save_objects(new_images)

    return len(new_movies), updated_count, last_endpoint, last_page


# ─── TMDB API FETCHERS ───────────────────────────────────────────────────────


def fetch_changed_movie_ids_page(start_date, end_date, page=1):
    """
    Fetch list of TMDB movie IDs that changed between start_date and end_date for a specific page.
    Uses paginated /movie/changes endpoint. Max 14 day range.
    Returns:
        (changed_ids, total_pages)
    """
    if page > TMDB_MAX_PAGES:
        return set(), TMDB_MAX_PAGES

    headers = get_headers()
    changed_ids = set()

    resp = requests.get(
        f"{Config.TMDB_BASE_URL}/movie/changes",
        headers=headers,
        params={
            "start_date": start_date.strftime("%Y-%m-%d"),
            "end_date": end_date.strftime("%Y-%m-%d"),
            "page": page,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    results = data.get("results", [])
    for item in results:
        changed_ids.add(str(item["id"]))

    total_pages = min(data.get("total_pages", 1), TMDB_MAX_PAGES)

    return changed_ids, total_pages


def fetch_movie_detail(tmdb_id):
    """Fetch full movie detail from TMDB /movie/{id}."""
    headers = get_headers()
    resp = requests.get(
        f"{Config.TMDB_BASE_URL}/movie/{tmdb_id}",
        headers=headers,
        params={"language": "en-US"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_movie_videos(tmdb_id):
    """Fetch videos (trailers, teasers) for a specific movie from TMDB."""
    headers = get_headers()
    try:
        resp = requests.get(
            f"{Config.TMDB_BASE_URL}/movie/{tmdb_id}/videos",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("results", [])
    except requests.RequestException:
        return []


# ─── SERIALIZERS ──────────────────────────────────────────────────────────────


def serialize_sync_log(log):
    """Serialize a SyncLog model to dict."""
    return {
        "id": str(log.id),
        "sync_type": log.sync_type,
        "last_sync_at": log.last_sync_at.isoformat() if log.last_sync_at else None,
        "total_inserted": log.total_inserted,
        "total_updated": log.total_updated,
        "status": log.status,
        "last_synced_endpoint": log.last_synced_endpoint,
        "last_synced_page": log.last_synced_page,
        "error_message": log.error_message,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }
