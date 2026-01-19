"""Database models for PostgreSQL."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Float, Integer, String, Text, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class User(Base):
    """User model for budget tracking."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    
    # Budget tracking
    daily_budget_usd: Mapped[float] = mapped_column(Float, default=1.0)
    daily_blogs_limit: Mapped[int] = mapped_column(Integer, default=10)
    
    # Usage tracking
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_blogs_generated: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    blogs: Mapped[list["Blog"]] = relationship("Blog", back_populates="user")
    cost_records: Mapped[list["CostRecord"]] = relationship("CostRecord", back_populates="user")


class Blog(Base):
    """Generated blog record."""

    __tablename__ = "blogs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.user_id"), nullable=False)
    session_id: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    
    # Content
    topic: Mapped[str] = mapped_column(String(500), nullable=False)
    audience: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Metadata
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    sources_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), default="in_progress")  # in_progress, completed, failed
    
    # Cost
    total_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="blogs")
    cost_records: Mapped[list["CostRecord"]] = relationship("CostRecord", back_populates="blog")


class CostRecord(Base):
    """Cost tracking per agent invocation."""

    __tablename__ = "cost_records"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(255), ForeignKey("users.user_id"), nullable=False)
    blog_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("blogs.id"), nullable=True)
    session_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    # Agent info
    agent_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    
    # Token usage
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0)
    
    # Cost
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    
    # Metadata
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="cost_records")
    blog: Mapped[Optional["Blog"]] = relationship("Blog", back_populates="cost_records")
