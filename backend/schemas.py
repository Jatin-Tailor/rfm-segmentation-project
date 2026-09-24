"""
schemas.py
Pydantic models used for API responses (and request validation where needed).
"""

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class CustomerSegmentOut(BaseModel):
    customer_id: str
    email: Optional[str] = None
    recency: float
    frequency: float
    monetary: float
    segment: str

    class Config:
        from_attributes = True


class RunSummaryOut(BaseModel):
    id: int
    filename: str
    upload_timestamp: datetime
    total_customers: int
    total_revenue: float
    status: str
    segment_counts: Optional[dict] = None

    class Config:
        from_attributes = True


class UploadResponse(BaseModel):
    run: RunSummaryOut
    segments: List[CustomerSegmentOut]


class ErrorDetail(BaseModel):
    detail: str
