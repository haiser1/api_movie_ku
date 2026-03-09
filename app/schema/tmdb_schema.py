from typing import Optional, Literal
from pydantic import BaseModel, Field


class SyncMoviesRequestSchema(BaseModel):
    mode: Literal["full", "changes"] = Field(
        default="full",
        description="Sync mode. 'full' syncs page-by-page from TMDB list endpoints. 'changes' syncs recent changes in one call.",
    )
    endpoint: Optional[str] = Field(
        default=None,
        description="TMDB endpoint to sync from, e.g. '/movie/popular'. If null on first call, backend returns the starting endpoint.",
    )
    page: int = Field(
        default=1,
        ge=1,
        description="Which page to process for this batch call.",
    )
    max_pages: Optional[int] = Field(
        default=None,
        ge=1,
        le=500,
        description="Limit the number of pages to sync per endpoint (1-500).",
    )
    sync_log_id: Optional[str] = Field(
        default=None,
        description="UUID of the SyncLog to resume. If provided, accumulates progress in this log. Required for subsequent batch calls to track stats correctly.",
    )


class SyncBatchResponseSchema(BaseModel):
    status: Literal["in_progress", "completed", "failed", "stopped"]
    endpoint: Optional[str] = None
    current_page: Optional[int] = None
    next_endpoint: Optional[str] = None
    next_page: Optional[int] = None
    total_pages: Optional[int] = None
    batch_inserted: int = 0
    batch_updated: int = 0
    cumulative_inserted: int = 0
    cumulative_updated: int = 0
    sync_log_id: Optional[str] = None


class SyncStopRequestSchema(BaseModel):
    sync_log_id: str = Field(
        description="UUID of the SyncLog to stop.",
    )
