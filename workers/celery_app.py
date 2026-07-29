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

    # ---------------------------------------------------------------
    # Bounded waits when the broker is unreachable.
    #
    # db.database.log_case_event() publishes a webhook task on every
    # case event - creating a case, advancing the workflow, uploading a
    # document. That publish happens inside the user's own request.
    #
    # Celery's defaults are built for a worker, which should wait:
    #
    #     Backend.retry_policy = {'max_retries': 20, 'interval_step': 1}
    #
    # Twenty attempts, one second apart. With Redis down, every click
    # froze the page for twenty seconds and then failed silently,
    # because the caller wraps the publish in a try/except. The user
    # saw a spinner and no explanation.
    #
    # Shortening this loses nothing real. Twenty seconds of retrying
    # buys no durability guarantee: if the broker is down longer than
    # that the task is dropped anyway, so the wait was only ever a
    # lottery ticket the user paid for. The durable answer is a
    # transactional outbox - see the note at the end of this file.
    #
    # Publisher side only
    # -------------------
    # broker_connection_max_retries is deliberately NOT set here. It is
    # shared with the worker's own connection handling, and a worker
    # that gives up after two attempts dies on any broker restart
    # instead of reconnecting. The settings below bound publishing and
    # result lookups without touching the consume loop.
    #
    # Worst case is now roughly 2s to connect plus two short retries,
    # against 20s before.
    # ---------------------------------------------------------------
    broker_connection_timeout=2.0,

    broker_transport_options={
        # socket_connect_timeout only. socket_timeout would also apply
        # to the worker's blocking BRPOP read, which is supposed to
        # block.
        "socket_connect_timeout": 2.0,
    },

    task_publish_retry_policy={
        "max_retries": 2,
        "interval_start": 0,
        "interval_step": 0.2,
        "interval_max": 0.5,
    },

    result_backend_transport_options={
        "socket_connect_timeout": 2.0,
        "retry_policy": {
            "max_retries": 2,
            "interval_start": 0,
            "interval_step": 0.2,
            "interval_max": 0.5,
        },
    },
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
