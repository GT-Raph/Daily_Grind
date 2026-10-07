"""Durable email order alerts. Provider acceptance does not imply delivery."""
import uuid
from datetime import timedelta
from smtplib import SMTPAuthenticationError, SMTPException

from django.conf import settings
from django.core.mail import EmailMessage
from django.db.models import Q
from django.utils import timezone

from .models import OrderNotification


def configuration_issues():
    issues = {}
    if not settings.SHOP_ORDER_EMAIL or not settings.DEFAULT_FROM_EMAIL or not settings.EMAIL_HOST:
        issues["email"] = "Email needs the shop address, sender address and SMTP settings."
    elif settings.EMAIL_HOST_USER and not settings.EMAIL_HOST_PASSWORD:
        issues["email"] = "Email needs the SMTP password for the configured sender. For Gmail, use an App Password."
    return issues


def send_email(order):
    items = "\n".join(f"{item.quantity} x {item.name} — GH₵{item.subtotal:.2f}" for item in order.items.all())
    body = (f"New pickup order {order.reference}\n\nCustomer: {order.customer_name}\nPhone: {order.phone}\n\n"
            f"{items}\n\nTotal due at the shop: GH₵{order.total:.2f}\n"
            f"Notes: {order.notes or 'None'}\n\nOpen the staff order screen to accept the order.\n"
            "Payment: pay at pickup. This order has not been paid online.")
    sent = EmailMessage(subject=f"New pickup order {order.reference}", body=body,
                        from_email=settings.DEFAULT_FROM_EMAIL, to=[settings.SHOP_ORDER_EMAIL]).send(fail_silently=False)
    if sent != 1:
        raise RuntimeError("Email provider did not accept the message.")
    return ""


def process_notifications(limit=50):
    """Claim email jobs with a lease. Historical non-email jobs remain inactive."""
    now = timezone.now()
    eligible = OrderNotification.objects.filter(
        channel=OrderNotification.Channel.EMAIL,
        status__in=["pending", "blocked", "failed"], next_attempt_at__lte=now, attempts__lt=5
    ).filter(Q(lease_until__isnull=True) | Q(lease_until__lt=now))
    ids = list(eligible.order_by("next_attempt_at").values_list("pk", flat=True)[:limit])
    issues = configuration_issues()
    processed = 0
    for pk in ids:
        lease = uuid.uuid4()
        if not eligible.filter(pk=pk).update(lease_token=lease, lease_until=timezone.now() + timedelta(minutes=2)):
            continue
        job = OrderNotification.objects.select_related("order").get(pk=pk)
        update = {"lease_until": None, "lease_token": None}
        if job.channel in issues:
            update.update(status="blocked", last_error=issues[job.channel], next_attempt_at=timezone.now() + timedelta(seconds=60))
        else:
            attempt = job.attempts + 1
            update["attempts"] = attempt
            try:
                provider_id = send_email(job.order)
            except Exception as exc:
                # Provider exceptions may contain addresses or credentials; never store raw exception text.
                if isinstance(exc, SMTPAuthenticationError):
                    error = "Email login was rejected. Check the sender and App Password."
                elif isinstance(exc, SMTPException):
                    error = "Email provider did not accept this alert. Check its configuration."
                elif isinstance(exc, (TimeoutError, OSError)):
                    error = "Email provider could not be reached."
                else:
                    error = "Email provider did not accept this alert. Check its configuration."
                update.update(status="failed", last_error=error,
                              next_attempt_at=timezone.now() + timedelta(seconds=min(30 * 2 ** (attempt - 1), 900)))
            else:
                update.update(status="submitted", submitted_at=timezone.now(), provider_id=provider_id, last_error="")
        OrderNotification.objects.filter(pk=pk, lease_token=lease).update(**update)
        processed += 1
    return processed
