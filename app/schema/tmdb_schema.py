from typing import Optional, Literal
from pydantic import BaseModel, Field


class SyncMoviesRequestSchema(BaseModel):
    mode: Literal["full", "changes"] = Field(
        default="full",
        description="Sync mode. 'full' syncs from popular lists. 'changes' syncs recent changes.",
    )
    resume: bool = Field(
        default=False,
        description="Resume from last failed sync position (full mode only)",
    )
    max_pages: Optional[int] = Field(
        default=None,
        ge=1,
        le=500,
        description="Limit the number of pages to sync (1-500)",
    )


class SyncStartedDataSchema(BaseModel):
    message: str
    type: Literal["movies", "changes"]
    started_at: str


class SyncStopResponseDataSchema(BaseModel):
    message: str
