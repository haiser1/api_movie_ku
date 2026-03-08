from flask import Blueprint, request, g

from app.helper.auth_middleware import jwt_required
from app.helper.base_response import response_success
from app.helper.error_handler import handle_errors
from app.schema.user_schema import UserUpdateSchema, UserChangePasswordSchema
from app.services.user_service import update_user_profile, change_user_password

user_bp = Blueprint("user", __name__)


@user_bp.route("/me", methods=["PUT"])
@jwt_required
@handle_errors
def update_profile():
    """Update current user's profile information."""
    body_data = request.get_json(silent=True) or {}
    body = UserUpdateSchema(**body_data)
    data = update_user_profile(g.current_user["sub"], body)
    return response_success("User profile updated successfully", data=data)


@user_bp.route("/me/password", methods=["PUT"])
@jwt_required
@handle_errors
def change_password():
    """Change current user's password."""
    body_data = request.get_json(silent=True) or {}
    body = UserChangePasswordSchema(**body_data)
    change_user_password(g.current_user["sub"], body)
    return response_success("Password changed successfully")
