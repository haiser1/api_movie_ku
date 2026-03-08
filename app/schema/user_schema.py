from typing import Optional
from pydantic import BaseModel, Field


class UserUpdateSchema(BaseModel):
    """Schema for a user updating their own profile."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    profile_picture: Optional[str] = Field(None, max_length=500)


class UserChangePasswordSchema(BaseModel):
    """Schema for a user changing their password."""

    old_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, max_length=255)
