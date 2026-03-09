import uuid
from datetime import datetime, timezone

from app.extensions import db


class SyncLog(db.Model):
    __tablename__ = "sync_logs"

    id = db.Column(db.UUID, primary_key=True, default=uuid.uuid4)
    sync_type = db.Column(
        db.String(20), nullable=False, default="full", comment="full or changes"
    )
    last_sync_at = db.Column(db.DateTime, nullable=False)
    total_inserted = db.Column(db.Integer, nullable=False, default=0)
    total_updated = db.Column(db.Integer, nullable=False, default=0)
    status = db.Column(db.String(20), nullable=False, comment="success, failed, in_progress, stopped")
    last_synced_endpoint = db.Column(
        db.String(50), nullable=True, comment="last endpoint synced"
    )
    last_synced_page = db.Column(db.Integer, nullable=True, comment="last page synced")
    error_message = db.Column(db.Text, nullable=True, comment="error message if failed")
    created_at = db.Column(
        db.DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )

    def __repr__(self):
        return f"<SyncLog {self.status} at {self.last_sync_at}>"
