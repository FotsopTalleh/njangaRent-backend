# tasks/celery_app.py  (project-root-level shim)
# Allows `celery -A tasks.celery_app worker` to work from the project root.
from app.tasks.celery_app import celery_app  # noqa: F401
