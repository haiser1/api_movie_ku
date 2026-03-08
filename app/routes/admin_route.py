"""Admin routes — dashboard, movie management, TMDB sync, and user management."""

from flask import Blueprint, request, g

from app.helper.auth_middleware import admin_required
from app.helper.base_response import response_success
from app.helper.error_handler import handle_errors
from app.helper.pagination import get_pagination_params
from app.schema.movie_schema import (
    AdminMovieCreateSchema,
    AdminMovieUpdateSchema,
    serialize_movie,
)
from app.schema.admin_schema import (
    AdminCreateUserSchema,
    AdminUpdateUserSchema,
    AdminListUserSchema,
)
from app.services import admin_service

admin_bp = Blueprint("admin", __name__)


# ==================== DASHBOARD ====================


@admin_bp.route("/dashboard")
@admin_required
@handle_errors
def get_dashboard():
    """Get analytics dashboard data.

    Query params:
        start_date: YYYY-MM-DD (default: 30 days ago)
        end_date:   YYYY-MM-DD (default: today)
    """
    data = admin_service.get_dashboard(
        start_date=request.args.get("start_date"),
        end_date=request.args.get("end_date"),
    )
    return response_success("Dashboard retrieved", data=data)


# ==================== ADMIN MOVIES ====================


@admin_bp.route("/movies")
@admin_required
@handle_errors
def list_admin_movies():
    """List all movies (admin view, includes archived)."""
    page, per_page = get_pagination_params()
    movies, meta = admin_service.list_admin_movies(
        search=request.args.get("search"),
        source=request.args.get("source"),
        status=request.args.get("status"),
        sort=request.args.get("sort_by", "created_at"),
        order=request.args.get("order_by", "desc"),
        page=page,
        per_page=per_page,
    )
    return response_success(
        "Movies retrieved",
        data=[serialize_movie(m) for m in movies],
        meta=meta,
    )


@admin_bp.route("/movies", methods=["POST"])
@admin_required
@handle_errors
def create_admin_movie():
    """Create a movie with admin-level fields."""
    body = AdminMovieCreateSchema(**request.get_json())
    movie = admin_service.create_admin_movie(body)
    return response_success(
        "Movie created", data=serialize_movie(movie), status_code=201
    )


@admin_bp.route("/movies/<id>", methods=["PUT"])
@admin_required
@handle_errors
def update_admin_movie(id):
    """Update any movie (admin has full access)."""
    body = AdminMovieUpdateSchema(**request.get_json())
    movie = admin_service.update_admin_movie(id, body)
    return response_success("Movie updated", data=serialize_movie(movie))


@admin_bp.route("/movies/<id>", methods=["DELETE"])
@admin_required
@handle_errors
def delete_admin_movie(id):
    """Soft-delete any movie."""
    admin_service.delete_admin_movie(id)
    return response_success("Movie deleted")


# ==================== ADMIN USER MANAGEMENT ====================


@admin_bp.route("/users")
@admin_required
@handle_errors
def list_users():
    """List all users with optional search, role, and status filter.

    Query params:
        search: Partial match on name or email.
        role: Filter by role (user|admin).
        status: Filter by active/inactive status (active|inactive).
        sort_by: Field to sort (name|email|created_at). Default: created_at.
        order_by: Sort direction (asc|desc). Default: desc.
        page: Page number. Default: 1.
        per_page: Items per page. Default: 10.
    """
    filters = AdminListUserSchema(**request.args.to_dict())
    users, meta = admin_service.list_users(filters)
    return response_success(
        "Users retrieved",
        data=[admin_service._serialize_user(u) for u in users],
        meta=meta,
    )


@admin_bp.route("/users", methods=["POST"])
@admin_required
@handle_errors
def create_user():
    """Admin creates a new user (role: user or admin)."""
    body = AdminCreateUserSchema(**request.get_json())
    user = admin_service.create_user(body)
    return response_success("User created", data=user, status_code=201)


@admin_bp.route("/users/<id>", methods=["PUT"])
@admin_required
@handle_errors
def update_user(id):
    """Admin updates a user's name, role, or profile picture.

    Admin cannot change their own role.
    """
    body = AdminUpdateUserSchema(**request.get_json())
    user = admin_service.update_user(
        id, body, current_admin_id=g.current_user.get("sub")
    )
    return response_success("User updated", data=user)


@admin_bp.route("/users/<id>", methods=["DELETE"])
@admin_required
@handle_errors
def delete_user(id):
    """Soft-delete a user (role=user only). Admin accounts cannot be deleted."""
    admin_service.soft_delete_user(id, current_admin_id=g.current_user.get("sub"))
    return response_success("User deleted")


@admin_bp.route("/users/<id>/reactivate", methods=["PATCH"])
@admin_required
@handle_errors
def reactivate_user(id):
    """Admin reactivates a soft-deleted user (role=user only)."""
    user = admin_service.reactivate_user(id)
    return response_success("User reactivated", data=user)
