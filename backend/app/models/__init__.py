"""SQLAlchemy ORM models.

Importing this package registers every table on ``Base.metadata``, which Alembic
autogenerate and the test schema fixtures both depend on.
"""

from app.models.base import Base
from app.models.code import Dependency, File, FileMetric, Finding
from app.models.enums import AnalyzerStatus, ChangeType, EdgeType, ScanStatus, Severity
from app.models.history import Commit, FileChange, Prediction
from app.models.repository import Repository, Scan

__all__ = [
    "AnalyzerStatus",
    "Base",
    "ChangeType",
    "Commit",
    "Dependency",
    "EdgeType",
    "File",
    "FileChange",
    "FileMetric",
    "Finding",
    "Prediction",
    "Repository",
    "Scan",
    "ScanStatus",
    "Severity",
]
