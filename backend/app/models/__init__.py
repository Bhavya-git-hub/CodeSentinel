"""SQLAlchemy ORM models.

Importing this package registers every table on ``Base.metadata``, which Alembic
autogenerate and the test schema fixtures both depend on.
"""

from app.models.base import Base
from app.models.code import Dependency, File, FileMetric, Finding
from app.models.enums import AnalyzerStatus, EdgeType, ScanStatus, Severity
from app.models.history import Commit, Prediction
from app.models.repository import Repository, Scan

__all__ = [
    "AnalyzerStatus",
    "Base",
    "Commit",
    "Dependency",
    "EdgeType",
    "File",
    "FileMetric",
    "Finding",
    "Prediction",
    "Repository",
    "Scan",
    "ScanStatus",
    "Severity",
]
