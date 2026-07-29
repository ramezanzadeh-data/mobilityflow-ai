from workers.celery_app import celery_app
from core.communication.notifications import dispatch_webhooks


@celery_app.task(
    name="workers.notification_tasks.dispatch_webhook",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
)
def dispatch_webhook(self, company, event_type, payload):
    """
    Delivers webhooks for a case event. Runs off the request path - a
    slow or unreachable customer endpoint no longer blocks whatever
    triggered the event (case creation, status change, etc).
    """

    try:
        dispatch_webhooks(company=company, event_type=event_type, payload=payload)
    except Exception as exc:
        raise self.retry(exc=exc)
