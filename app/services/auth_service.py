import bcrypt
from app.helper.error_handler import BadRequestError, ConflictError, NotFoundError
import jwt as pyjwt
from flask import current_app

from app.extensions import db
from app.helper.error_handler import AuthError
from app.helper.jwt_handler import (
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.helper.logger import json_logger
from app.helper.oauth_service import get_google_client
from app.models.user import User
from app.schema.auth_schema import (
    LoginUserPasswordSchema,
    RefreshTokenRequestSchema,
    RegisterUserSchema,
    TokenResponseSchema,
    UserResponseSchema,
)


def google_authorize_redirect(redirect_uri: str):
    """Initiate Google OAuth2 redirect."""
    google = get_google_client()
    return google.authorize_redirect(redirect_uri)


def google_callback_service() -> dict:
    """
    Handle Google OAuth2 callback.

    Exchanges auth code for tokens, finds/creates user, returns JWT tokens.

    Returns:
        dict with token response data.

    Raises:
        AuthError: If Google authorization or user info retrieval fails.
    """
    google = get_google_client()

    try:
        token = google.authorize_access_token()
    except Exception as e:
        json_logger.error(f"Failed to authorize with Google: {str(e)}")
        raise AuthError(
            message="Authentication failed",
            error="Failed to authorize with Google",
        )

    user_info = token.get("userinfo")
    if not user_info:
        json_logger.error("Failed to retrieve user info from Google")
        raise AuthError(
            message="Authentication failed",
            error="Failed to retrieve user information",
        )

    user = _find_or_create_user(user_info)

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        json_logger.error(f"Database error during user creation/update: {str(e)}")
        raise AuthError(
            message="Authentication failed",
            error="Failed to save user data",
        )

    json_logger.info(f"User {user.email} authenticated via Google OAuth")
    return _generate_token_response(user)


def refresh_token_service(body: RefreshTokenRequestSchema) -> dict:
    """
    Refresh an access token using a valid refresh token.

    Args:
        body: Validated refresh token request schema.

    Returns:
        dict with new token response data.

    Raises:
        AuthError: If refresh token is expired, invalid, wrong type, or user not found.
    """
    try:
        payload = decode_token(body.refresh_token)
    except pyjwt.ExpiredSignatureError:
        raise AuthError(message="Unauthorized", error="Refresh token has expired")
    except pyjwt.InvalidTokenError:
        raise AuthError(message="Unauthorized", error="Invalid refresh token")

    if payload.get("type") != "refresh":
        raise AuthError(message="Unauthorized", error="Invalid token type")

    user = db.session.get(User, payload["sub"])
    if not user:
        raise AuthError(message="Unauthorized", error="User not found")

    json_logger.info(f"Token refreshed for user {user.email}")
    return _generate_token_response(user)


def get_current_user_service(payload: dict) -> dict:
    """
    Serialize the current user's profile data.

    Args:
        payload: JWT payload dict with sub, role, name, email.

    Returns:
        dict with serialized user profile.
    """
    user = db.session.get(User, payload["sub"])
    if not user:
        raise NotFoundError("User not found")
    response = UserResponseSchema.model_validate(user)
    return response.model_dump(mode="json")


def logout_service(payload: dict) -> None:
    """
    Handle user logout (logging only, JWT is stateless).

    Args:
        payload: JWT payload dict.
    """
    json_logger.info(f"User {payload.get('email')} logged out")


# --- Private helpers ---


def _find_or_create_user(user_info: dict) -> User:
    """Find an existing user by OAuth ID/email or create a new one."""
    user = User.query.filter_by(
        oauth_provider="google", oauth_id=str(user_info["sub"])
    ).first()

    if not user:
        user = User.query.filter_by(email=user_info["email"]).first()
        if user and user.deleted_at:
            raise BadRequestError(
                error="Your account has been deactivated by admin. Please contact admin for more information.",
            )
        if user:
            user.oauth_provider = "google"
            user.oauth_id = str(user_info["sub"])
            user.profile_picture = user_info.get("picture")
        else:
            user = User(
                oauth_provider="google",
                oauth_id=str(user_info["sub"]),
                name=user_info.get("name", user_info["email"]),
                email=user_info["email"],
                profile_picture=user_info.get("picture"),
            )
            db.session.add(user)
    else:
        user.name = user_info.get("name", user.name)
        user.profile_picture = user_info.get("picture", user.profile_picture)

    return user


def _generate_token_response(user: User) -> dict:
    """Generate JWT access + refresh tokens and return as dict."""
    access_token = create_access_token(user.id, user.role, user.name, user.email)
    refresh_token = create_refresh_token(user.id)
    expires_in = current_app.config["JWT_ACCESS_TOKEN_EXPIRES"]

    response = TokenResponseSchema(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=expires_in,
    )
    return response.model_dump()


def register_user_service(data: RegisterUserSchema) -> dict:
    """Register a new user with email and password."""
    existing = User.query.filter_by(email=data.email).first()
    if existing and existing.deleted_at:
        raise BadRequestError(
            message="Your account has been deactivated by admin. Please contact admin for more information.",
            error="Your account has been deactivated by admin. Please contact admin for more information.",
        )
    if existing:
        raise ConflictError(
            error="User already exists. Please login with your email and password.",
        )

    hashed = bcrypt.hashpw(data.password.encode("utf-8"), bcrypt.gensalt()).decode(
        "utf-8"
    )

    user = User(
        name=data.name,
        email=data.email,
        password_hash=hashed,
    )
    db.session.add(user)
    db.session.commit()

    response = UserResponseSchema.model_validate(user)
    return response.model_dump(mode="json")


def login_user_password_service(data: LoginUserPasswordSchema) -> dict:
    """Login a user with email and password."""
    user = User.query.filter_by(email=data.email).first()

    if not user or not user.password_hash:
        raise BadRequestError(
            error="Email or Password is invalid",
        )

    if user.deleted_at:
        raise BadRequestError(
            error="Your account has been deactivated by admin. Please contact admin for more information.",
        )

    if not bcrypt.checkpw(
        data.password.encode("utf-8"), user.password_hash.encode("utf-8")
    ):
        raise BadRequestError(
            error="Email or Password is invalid",
        )

    return _generate_token_response(user)
