from pydantic import BaseModel, Field, EmailStr
from typing import Optional
from uuid import UUID


class TokenResponseSchema(BaseModel):
    """Schema for JWT token response after successful authentication."""

    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = Field(description="Access token expiration time in seconds")


class RefreshTokenRequestSchema(BaseModel):
    """Schema for refresh token request body."""

    refresh_token: str


class UserResponseSchema(BaseModel):
    """Schema for user profile response."""

    id: UUID
    name: str
    email: str
    role: str
    profile_picture: Optional[str] = None
    oauth_provider: Optional[str] = None

    class Config:
        from_attributes = True


class AuthErrorSchema(BaseModel):
    """Schema for authentication error responses."""

    success: bool = False
    message: str
    error: Optional[str] = None


class RegisterUserSchema(BaseModel):
    """Schema for user registration."""

    name: str = Field(..., min_length=1, max_length=255)
    email: EmailStr = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=255)


class LoginUserPasswordSchema(BaseModel):
    """Schema for user login with password."""

    email: EmailStr = Field(..., min_length=5, max_length=255)
    password: str = Field(..., min_length=8, max_length=255)
