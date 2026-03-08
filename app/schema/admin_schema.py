from datetime import datetime
from pydantic import BaseModel, Field
from typing import Literal, Optional
from uuid import UUID


class AdminCreateUserSchema(BaseModel):
    """Schema for admin creating a new user manually."""

    name: str = Field(..., min_length=1, max_length=255)
    email: str = Field(..., min_length=5, max_length=255)
    role: Literal["user", "admin"] = "user"
    profile_picture: Optional[str] = Field(None, max_length=500)


class AdminUpdateUserSchema(BaseModel):
    """Schema for admin updating a user's details or role."""

    name: Optional[str] = Field(None, min_length=1, max_length=255)
    role: Optional[Literal["user", "admin"]] = None
    profile_picture: Optional[str] = Field(None, max_length=500)


class AdminUserResponseSchema(BaseModel):
    """Schema for returning user data in the admin panel."""

    id: UUID
    name: str
    email: str
    role: str
    profile_picture: Optional[str] = None
    oauth_provider: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    deleted_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# search=None, role=None, sort="created_at", order="desc", page=1, per_page=20


class AdminListUserSchema(BaseModel):
    page: int = Field(1, ge=1)
    per_page: int = Field(10, ge=1)
    search: Optional[str] = None
    role: Optional[Literal["user", "admin"]] = None
    status: Optional[Literal["active", "inactive"]] = None
    sort_by: Optional[Literal["created_at", "name", "email"]] = "created_at"
    order_by: Optional[Literal["desc", "asc"]] = "desc"
