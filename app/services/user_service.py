from datetime import datetime, timezone
import bcrypt

from app.extensions import db
from app.models.user import User
from app.helper.error_handler import NotFoundError, BadRequestError
from app.schema.user_schema import UserUpdateSchema, UserChangePasswordSchema
from app.schema.auth_schema import UserResponseSchema

def update_user_profile(user_id: str, data: UserUpdateSchema):
    """Update current user's profile information."""
    user = User.query.get(user_id)
    if not user or user.deleted_at:
        raise NotFoundError(error="User not found")
        
    if data.name is not None:
        user.name = data.name
    if data.profile_picture is not None:
        user.profile_picture = data.profile_picture
        
    user.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    
    response = UserResponseSchema.model_validate(user)
    return response.model_dump(mode="json")


def change_user_password(user_id: str, data: UserChangePasswordSchema):
    """Change the password for the current user."""
    user = User.query.get(user_id)
    if not user or user.deleted_at:
        raise NotFoundError(error="User not found")
        
    if not user.password_hash:
        raise BadRequestError(error="User logged in via OAuth, does not have a password set")

    if not bcrypt.checkpw(data.old_password.encode("utf-8"), user.password_hash.encode("utf-8")):
        raise BadRequestError(error="Incorrect old password")
        
    hashed_new = bcrypt.hashpw(data.new_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    user.password_hash = hashed_new
    user.updated_at = datetime.now(timezone.utc)
    db.session.commit()
