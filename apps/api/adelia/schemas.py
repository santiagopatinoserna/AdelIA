from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DocumentOut(BaseModel):
    id: UUID
    source: Literal["web", "manual"]
    mime_type: str
    s3_key: str
    raw_text: str | None
    created_at: datetime
    processed_at: datetime | None
    status: Literal["uploaded", "processing", "ready", "failed"]

    model_config = ConfigDict(from_attributes=True)


def derive_status(raw_text: str | None, processed_at: datetime | None) -> Literal["processing", "ready", "failed"]:
    if processed_at and raw_text is not None:
        return "ready"
    if processed_at and raw_text is None:
        return "failed"
    return "processing"
