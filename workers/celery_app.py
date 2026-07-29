# Must run before REDIS_URL is read below and before the task modules in
# `include` import db.database / auth.*, all of which read configuration
# at import time. Without it, a worker started directly on a developer
# machine (rather than through Docker Compose) silently falls back to the
# localhost defaults - see bootstrap/environment.py.
from bootstrap import load_environment

load_environment()

import os  # noqa: E402  (deliberate - see above)

from celery import Celery  # noqa: E402

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "mobilityflow",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "workers.ocr_tasks",
        "workers.ai_tasks",
        "workers.email_tasks",
        "workers.pdf_tasks",
        "workers.notification_tasks",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    result_expires=3600,
    task_default_queue="mobilityflow",
    broker_connection_retry_on_startup=True,
)


from celery.signals import task_prerun, task_postrun, task_failure  # noqa: E402


@task_prerun.connect
def _on_task_prerun(task_id=None, **kwargs):
    from db.database import update_job_status
    try:
        update_job_status(task_id, "STARTED")
    except Exception:
        pass


@task_postrun.connect
def _on_task_postrun(task_id=None, state=None, **kwargs):
    from db.database import update_job_status
    try:
        update_job_status(task_id, state or "SUCCESS")
    except Exception:
        pass


@task_failure.connect
def _on_task_failure(task_id=None, **kwargs):
    from db.database import update_job_status
    try:
        update_job_status(task_id, "FAILURE")
    except Exception:
        pass
