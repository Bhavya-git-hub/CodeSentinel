"""Celery worker application and task definitions."""

from app.workers.celery_app import celery_app

__all__ = ["celery_app"]
