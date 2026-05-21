# tasks/__init__.py
# Top-level tasks package — required so Celery can resolve "tasks.celery_app"
# when the worker is started from the project root directory.
from app.tasks.celery_app import celery_app

__all__ = ["celery_app"]
