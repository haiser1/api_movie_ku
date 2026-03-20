from flask import Blueprint, request, url_for, g, make_response, redirect
from urllib.parse import urlencode

from app.helper.auth_middleware import jwt_required
from app.helper.base_response import response_success
from app.helper.error_handler import handle_errors
from app.schema.auth_schema import (
    LoginUserPasswordSchema,
    RefreshTokenRequestSchema,
    RegisterUserSchema,
)
from app.services.auth_service import (
    google_authorize_redirect,
    google_callback_service,
    refresh_token_service,
    get_current_user_service,
    logout_service,
    register_user_service,
    login_user_password_service,
)
from config import Config

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/google/login")
@handle_errors
def google_login():
    """
    Initiate Google OAuth2 login flow.

    Redirects the user to Google's OAuth consent screen.
    After authorization, Google redirects back to the callback URL.

    Returns:
        Redirect to Google OAuth consent page.
    """
    redirect_uri = url_for("auth.google_callback", _external=True)
    return google_authorize_redirect(redirect_uri)


@auth_bp.route("/google/callback")
@handle_errors
def google_callback():
    """
    Handle the OAuth2 callback from Google.

    Exchanges the authorization code for tokens, fetches user info,
    creates or updates the user in the database, and returns JWT tokens.
    Passes tokens as query parameters then redirects to the frontend.

    Returns:
        Redirect to frontend callback page with JWT tokens in query parameters.
    """
    data = google_callback_service()

    params = {}
    if data.get("access_token"):
        params["access_token"] = data["access_token"]
    if data.get("refresh_token"):
        params["refresh_token"] = data["refresh_token"]

    query_params = urlencode(params)
    redirect_url = (
        f"{Config.FE_REDIRECT_URL}?{query_params}"
        if query_params
        else Config.FE_REDIRECT_URL
    )
    response = make_response(redirect(redirect_url))
    return response


@auth_bp.route("/refresh", methods=["POST"])
@handle_errors
def refresh_token():
    """
    Refresh an access token using a valid refresh token.

    Reads refresh_token from JSON body.
    Returns a new access token if the refresh token is valid.

    Returns:
        JSON response with new access_token, refresh_token, token_type, and expires_in.
    """
    body_data = request.get_json(silent=True)
    refresh_token_value = body_data.get("refresh_token") if body_data else None

    if not refresh_token_value:
        from app.helper.base_response import response_error

        return response_error(
            message="Unauthorized",
            error="Refresh token is required",
            status_code=401,
        )

    body = RefreshTokenRequestSchema(refresh_token=refresh_token_value)
    data = refresh_token_service(body)
    json_response, status_code = response_success(
        "Token refreshed successfully", data=data
    )
    response = make_response(json_response, status_code)
    return response


@auth_bp.route("/me")
@jwt_required
@handle_errors
def get_current_user():
    """
    Get the current authenticated user's profile.

    Requires a valid JWT access token in the Authorization header.

    Returns:
        JSON response with user profile data.
    """
    data = get_current_user_service(g.current_user)
    return response_success("User profile retrieved", data=data)


@auth_bp.route("/logout", methods=["POST"])
@jwt_required
@handle_errors
def logout():
    """
    Logout the user.

    Since JWT is stateless, actual token invalidation would require
    a token blacklist (e.g., Redis).

    Returns:
        JSON response confirming logout.
    """
    logout_service(g.current_user)
    json_response, status_code = response_success("Logged out successfully")
    response = make_response(json_response, status_code)
    return response


@auth_bp.route("/register", methods=["POST"])
@handle_errors
def register_user_route():
    """
    Register a new user.

    Returns:
        JSON response with user data.
    """
    body_data = request.get_json(silent=True)
    body = RegisterUserSchema(**body_data)
    data = register_user_service(body)
    json_response, status_code = response_success(
        "User registered successfully", data=data, status_code=201
    )
    response = make_response(json_response, status_code)
    return response


@auth_bp.route("/email-password/login", methods=["POST"])
@handle_errors
def login_email_password():
    """
    Login with email and password.

    Returns:
        JSON response with user data.
    """
    body_data = request.get_json(silent=True)
    body = LoginUserPasswordSchema(**body_data)
    data = login_user_password_service(body)
    json_response, status_code = response_success(
        "User logged in successfully", data=data, status_code=200
    )
    response = make_response(json_response, status_code)
    return response
