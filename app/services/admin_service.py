"""Admin service — business logic for admin operations."""

from flask import g
from app.schema.movie_schema import AdminMovieCreateSchema
from app.schema.admin_schema import AdminUserResponseSchema, AdminListUserSchema
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import case, func

from app.extensions import db
from app.models.movie import Movie
from app.models.user import User
from app.models.wishlist import Wishlist
from app.models.genre import Genre
from app.models.sync_log import SyncLog
from app.models.movie_genre import movie_genres
from app.helper.error_handler import NotFoundError
from app.helper.pagination import paginate
from app.services.movie_service import (
    _base_movie_query,
    _get_sort_column,
    get_movie_detail,
)


def _parse_date_range(start_date_str=None, end_date_str=None):
    """Parse date range strings, defaulting to last 30 days."""
    today = date.today()
    if end_date_str:
        try:
            end = datetime.strptime(end_date_str, "%Y-%m-%d").date()
        except ValueError:
            end = today
    else:
        end = today

    if start_date_str:
        try:
            start = datetime.strptime(start_date_str, "%Y-%m-%d").date()
        except ValueError:
            start = end - timedelta(days=30)
    else:
        start = end - timedelta(days=30)

    # Convert to datetime for timestamp comparisons
    start_dt = datetime.combine(start, datetime.min.time(), tzinfo=timezone.utc)
    end_dt = datetime.combine(end, datetime.max.time(), tzinfo=timezone.utc)
    return start, end, start_dt, end_dt


def _get_summary(start_dt, end_dt):
    """Build summary cards (totals + highlights) within date range."""
    base_filter = Movie.deleted_at.is_(None)

    total_movies = (
        db.session.query(func.count(Movie.id))
        .filter(base_filter, Movie.created_at.between(start_dt, end_dt))
        .scalar()
    )
    total_users = (
        db.session.query(func.count(User.id))
        .filter(User.created_at.between(start_dt, end_dt))
        .scalar()
    )
    total_wishlists = (
        db.session.query(func.count(Wishlist.id))
        .filter(Wishlist.created_at.between(start_dt, end_dt))
        .scalar()
    )

    # Overall totals (all time, not date-filtered)
    total_movies_all = (
        db.session.query(func.count(Movie.id)).filter(base_filter).scalar()
    )
    total_users_all = db.session.query(func.count(User.id)).scalar()
    total_wishlists_all = db.session.query(func.count(Wishlist.id)).scalar()

    # Top genre overall
    top_genre_row = (
        db.session.query(Genre.name, func.count(movie_genres.c.movie_id))
        .join(movie_genres, Genre.id == movie_genres.c.genre_id)
        .join(Movie, Movie.id == movie_genres.c.movie_id)
        .filter(base_filter)
        .group_by(Genre.name)
        .order_by(func.count(movie_genres.c.movie_id).desc())
        .first()
    )

    # Latest movie
    latest_movie = (
        Movie.query.filter(base_filter).order_by(Movie.created_at.desc()).first()
    )

    # Average rating
    avg_rating = (
        db.session.query(func.avg(Movie.rating))
        .filter(base_filter, Movie.rating.isnot(None))
        .scalar()
    )

    return {
        "total_movies": total_movies or 0,
        "total_users": total_users or 0,
        "total_wishlists": total_wishlists or 0,
        "total_movies_all": total_movies_all or 0,
        "total_users_all": total_users_all or 0,
        "total_wishlists_all": total_wishlists_all or 0,
        "top_genre": top_genre_row[0] if top_genre_row else None,
        "latest_movie": {
            "id": str(latest_movie.id),
            "title": latest_movie.title,
            "created_at": latest_movie.created_at.isoformat(),
        }
        if latest_movie
        else None,
        "average_rating": round(float(avg_rating), 2) if avg_rating else 0,
    }


def _get_pie_charts(start_dt, end_dt):
    """Build pie chart datasets within date range."""
    base_filter = (
        Movie.deleted_at.is_(None),
        Movie.created_at.between(start_dt, end_dt),
    )

    # Movies by genre
    movies_by_genre = (
        db.session.query(Genre.name, func.count(movie_genres.c.movie_id))
        .join(movie_genres, Genre.id == movie_genres.c.genre_id)
        .join(Movie, Movie.id == movie_genres.c.movie_id)
        .filter(*base_filter)
        .group_by(Genre.name)
        .order_by(func.count(movie_genres.c.movie_id).desc())
        .limit(10)
        .all()
    )

    # Movies by source
    movies_by_source = (
        db.session.query(Movie.source, func.count(Movie.id))
        .filter(*base_filter)
        .group_by(Movie.source)
        .all()
    )

    # Movies by status
    movies_by_status = (
        db.session.query(Movie.status, func.count(Movie.id))
        .filter(Movie.deleted_at.is_(None), Movie.created_at.between(start_dt, end_dt))
        .group_by(Movie.status)
        .all()
    )

    # Sync log status
    sync_by_status = (
        db.session.query(SyncLog.status, func.count(SyncLog.id))
        .filter(SyncLog.created_at.between(start_dt, end_dt))
        .group_by(SyncLog.status)
        .all()
    )

    def to_pie_with_percentage(rows):
        total = sum(value for _, value in rows)
        return [
            {
                "label": label,
                "value": value,
                "percentage": round((value / total * 100), 2) if total > 0 else 0.00,
            }
            for label, value in rows
        ]

    return {
        "movies_by_genre": to_pie_with_percentage(movies_by_genre),
        "movies_by_source": to_pie_with_percentage(movies_by_source),
        "movies_by_status": to_pie_with_percentage(movies_by_status),
        "sync_by_status": to_pie_with_percentage(sync_by_status),
    }


def _get_column_charts(start, end, start_dt, end_dt):
    """Build column chart datasets within date range."""

    # Movies created per day
    movies_per_day = (
        db.session.query(
            func.date(Movie.created_at).label("day"),
            func.count(Movie.id),
        )
        .filter(Movie.deleted_at.is_(None), Movie.created_at.between(start_dt, end_dt))
        .group_by(func.date(Movie.created_at))
        .order_by(func.date(Movie.created_at))
        .all()
    )

    # Wishlists created per day
    wishlists_per_day = (
        db.session.query(
            func.date(Wishlist.created_at).label("day"),
            func.count(Wishlist.id),
        )
        .filter(Wishlist.created_at.between(start_dt, end_dt))
        .group_by(func.date(Wishlist.created_at))
        .order_by(func.date(Wishlist.created_at))
        .all()
    )

    # Users registered per day
    users_per_day = (
        db.session.query(
            func.date(User.created_at).label("day"),
            func.count(User.id),
        )
        .filter(User.created_at.between(start_dt, end_dt))
        .group_by(func.date(User.created_at))
        .order_by(func.date(User.created_at))
        .all()
    )

    # Rating distribution (grouped into ranges)
    rating_ranges = (
        db.session.query(
            case(
                (Movie.rating < 2, "0-2"),
                (Movie.rating < 4, "2-4"),
                (Movie.rating < 6, "4-6"),
                (Movie.rating < 8, "6-8"),
                else_="8-10",
            ).label("range"),
            func.count(Movie.id),
        )
        .filter(
            Movie.deleted_at.is_(None),
            Movie.rating.isnot(None),
            Movie.created_at.between(start_dt, end_dt),
        )
        .group_by("range")
        .order_by("range")
        .all()
    )

    def to_daily(rows):
        return [{"date": str(day), "count": count} for day, count in rows]

    return {
        "movies_per_day": to_daily(movies_per_day),
        "wishlists_per_day": to_daily(wishlists_per_day),
        "users_per_day": to_daily(users_per_day),
        "rating_distribution": [{"range": r, "count": c} for r, c in rating_ranges],
    }


def get_dashboard(start_date=None, end_date=None):
    """Get full analytics dashboard data.

    Args:
        start_date: Start date string (YYYY-MM-DD). Defaults to 30 days ago.
        end_date: End date string (YYYY-MM-DD). Defaults to today.

    Returns:
        dict with summary, pie_charts, and column_charts.
    """
    start, end, start_dt, end_dt = _parse_date_range(start_date, end_date)

    return {
        "date_range": {
            "start_date": str(start),
            "end_date": str(end),
        },
        "summary": _get_summary(start_dt, end_dt),
        "pie_charts": _get_pie_charts(start_dt, end_dt),
        "column_charts": _get_column_charts(start, end, start_dt, end_dt),
    }


def list_admin_movies(
    search=None,
    source=None,
    status=None,
    sort="created_at",
    order="desc",
    page=1,
    per_page=20,
):
    """List all movies for admin (including archived).

    Admin can see all statuses and sources.
    """
    query = _base_movie_query()

    if search:
        query = query.filter(Movie.title.ilike(f"%{search}%"))
    if source:
        query = query.filter(Movie.source == source)
    if status:
        query = query.filter(Movie.status == status)

    sort_col = _get_sort_column(sort)
    if order == "asc":
        query = query.order_by(sort_col.asc().nullslast())
    else:
        query = query.order_by(sort_col.desc().nullslast())

    return paginate(query, page, per_page)


def create_admin_movie(data: AdminMovieCreateSchema):
    """Create a movie with admin-level fields.

    Admin can set popularity, rating, is_featured, and status.
    """
    movie = Movie(
        source="admin",
        created_by=g.current_user.get("sub"),
        title=data.title,
        overview=data.overview,
        release_date=data.release_date,
        popularity=data.popularity,
        rating=data.rating,
        is_featured=data.is_featured if data.is_featured is not None else False,
        status=data.status if data.status else "active",
    )

    if data.genre_ids:
        genres = Genre.query.filter(Genre.id.in_(data.genre_ids)).all()
        if not genres:
            raise NotFoundError(error="Genre not found, please provide valid genre ids")
        movie.genres = genres

    db.session.add(movie)
    db.session.commit()

    return get_movie_detail(movie.id)


def update_admin_movie(movie_id, data):
    """Update any movie (admin has full access).

    Raises:
        NotFoundError: If movie not found.
    """
    movie = Movie.query.filter(Movie.id == movie_id, Movie.deleted_at.is_(None)).first()
    if not movie:
        raise NotFoundError(error="Movie not found")

    if data.title is not None:
        movie.title = data.title
    if data.overview is not None:
        movie.overview = data.overview
    if data.release_date is not None:
        movie.release_date = data.release_date
    if data.popularity is not None:
        movie.popularity = data.popularity
    if data.rating is not None:
        movie.rating = data.rating
    if data.is_featured is not None:
        movie.is_featured = data.is_featured
    if data.status is not None:
        movie.status = data.status
    if data.genre_ids is not None:
        genres = Genre.query.filter(Genre.id.in_(data.genre_ids)).all()
        movie.genres = genres

    movie.updated_at = datetime.now(timezone.utc)
    db.session.commit()

    return get_movie_detail(movie.id)


def delete_admin_movie(movie_id):
    """Soft-delete any movie (admin can delete any source).

    Raises:
        NotFoundError: If movie not found.
    """
    movie = Movie.query.filter(Movie.id == movie_id, Movie.deleted_at.is_(None)).first()
    if not movie:
        raise NotFoundError(error="Movie not found")

    movie.deleted_at = datetime.now(timezone.utc)
    db.session.commit()


# ==================== ADMIN USER MANAGEMENT ====================


def _serialize_user(user: User) -> dict:
    """Serialize a User model to a dict using Pydantic."""
    return AdminUserResponseSchema.model_validate(user).model_dump(mode="json")


def list_users(filters: AdminListUserSchema):
    """List all users with optional search, role, and status filter.

    Args:
        filters: AdminListUserSchema object containing filters.

    Returns:
        Tuple of (users list, pagination meta).
    """
    query = User.query

    if filters.search:
        query = query.filter(
            db.or_(
                User.name.ilike(f"%{filters.search}%"),
                User.email.ilike(f"%{filters.search}%"),
            )
        )
    if filters.role:
        query = query.filter(User.role == filters.role)

    if filters.status == "active":
        query = query.filter(User.deleted_at.is_(None))
    elif filters.status == "inactive":
        query = query.filter(User.deleted_at.isnot(None))

    sort_col = {
        "name": User.name,
        "email": User.email,
        "created_at": User.created_at,
    }.get(filters.sort_by, User.created_at)

    if filters.order_by == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    return paginate(query, filters.page, filters.per_page)


def create_user(data):
    """Admin creates a new user manually (no OAuth required).

    Args:
        data: AdminCreateUserSchema instance.

    Raises:
        ConflictError: If email already exists.

    Returns:
        Serialized user dict.
    """
    from app.helper.error_handler import ConflictError

    existing = User.query.filter_by(email=data.email).first()
    if existing:
        raise ConflictError(error=f"Email '{data.email}' is already registered")

    user = User(
        name=data.name,
        email=data.email,
        role=data.role,
        profile_picture=data.profile_picture,
    )
    db.session.add(user)
    db.session.commit()
    return _serialize_user(user)


def update_user(user_id, data, current_admin_id):
    """Admin updates a user's name, role, or profile picture.

    Args:
        user_id: Target user UUID.
        data: AdminUpdateUserSchema instance.
        current_admin_id: UUID string of the requesting admin.

    Raises:
        NotFoundError: If user not found.
        ForbiddenError: If trying to demote the requesting admin themselves.

    Returns:
        Serialized user dict.
    """
    from app.helper.error_handler import ForbiddenError

    user = User.query.filter_by(id=user_id).first()
    if not user:
        raise NotFoundError(error="User not found")

    # Prevent admin from changing their own role
    if (
        str(user.id) == str(current_admin_id)
        and data.role is not None
        and data.role != user.role
    ):
        raise ForbiddenError(error="You cannot change your own role")

    if data.name is not None:
        user.name = data.name
    if data.role is not None:
        user.role = data.role
    if data.profile_picture is not None:
        user.profile_picture = data.profile_picture

    user.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return _serialize_user(user)


def soft_delete_user(user_id):
    """Admin soft-deletes a user by setting deleted_at.

    Admin cannot delete other admins — only users with role='user'.

    Args:
        user_id: Target user UUID.

    Raises:
        NotFoundError: If user not found.
        ForbiddenError: If target user is an admin.
    """
    from app.helper.error_handler import ForbiddenError

    user = User.query.filter_by(id=user_id).first()
    if not user:
        raise NotFoundError(error="User not found")

    if user.role == "admin":
        raise ForbiddenError(error="Cannot delete another admin account")

    user.deleted_at = datetime.now(timezone.utc)
    db.session.commit()


def reactivate_user(user_id):
    """Admin reactivates a user by setting deleted_at to None.

    Args:
        user_id: Target user UUID.

    Raises:
        NotFoundError: If user not found.
        ForbiddenError: If target user is an admin.
    """
    from app.helper.error_handler import ForbiddenError

    user = User.query.filter_by(id=user_id).first()
    if not user:
        raise NotFoundError(error="User not found")

    if user.role == "admin":
        raise ForbiddenError(error="Cannot reactivate another admin account")

    user.deleted_at = None
    user.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return _serialize_user(user)
