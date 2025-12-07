"""
Policy model for storing dynamic configuration.
"""

from sqlalchemy import Column, String, Text

from .database import Base


class Policy(Base):
    """Policy configuration stored in database."""

    __tablename__ = "policy"

    key = Column(String(255), primary_key=True)
    value = Column(Text, nullable=False)  # JSON format
