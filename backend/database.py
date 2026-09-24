"""
database.py
Defines the SQLite persistence layer using SQLAlchemy ORM.

Tables:
    - Run: one row per uploaded batch/file
    - CustomerSegment: one row per customer, linked to a Run via foreign key
"""

from datetime import datetime

from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    ForeignKey,
)
from sqlalchemy.orm import declarative_base, relationship, sessionmaker

DATABASE_URL = "sqlite:///./rfm_engine.db"

# check_same_thread=False is required for SQLite when accessed from
# multiple FastAPI request threads.
engine = create_engine(
    DATABASE_URL, connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Run(Base):
    """Represents a single uploaded-file processing batch."""

    __tablename__ = "runs"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String, nullable=False)
    upload_timestamp = Column(DateTime, default=datetime.utcnow)
    total_customers = Column(Integer, nullable=False, default=0)
    total_revenue = Column(Float, nullable=False, default=0.0)
    status = Column(String, nullable=False, default="completed")

    segments = relationship(
        "CustomerSegment",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class CustomerSegment(Base):
    """Represents one customer's RFM metrics + assigned segment for a Run."""

    __tablename__ = "customer_segments"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("runs.id"), nullable=False, index=True)
    customer_id = Column(String, nullable=False, index=True)
    email = Column(String, nullable=True)

    recency = Column(Float, nullable=False)
    frequency = Column(Float, nullable=False)
    monetary = Column(Float, nullable=False)

    segment = Column(String, nullable=False, index=True)

    run = relationship("Run", back_populates="segments")


def init_db() -> None:
    """Create all tables if they do not already exist."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """FastAPI dependency that yields a DB session and always closes it."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
