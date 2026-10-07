from functools import wraps
from urllib.parse import parse_qs, urlsplit

from django.contrib import messages
from django.contrib.auth.views import LoginView, LogoutView, redirect_to_login
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from website.models import Order, OrderNotification
from website.notifications import configuration_issues

from .forms import StaffAuthenticationForm, can_view_orders


class StaffLoginView(LoginView):
    template_name = "staff_portal/login.html"
    authentication_form = StaffAuthenticationForm
    next_page = "staff:orders"

    def get_redirect_url(self):
        # Only return to the staff queue, never an action, partial, or external URL.
        target = urlsplit(super().get_redirect_url())
        if target.path == reverse("staff:orders"):
            history = parse_qs(target.query).get("history") == ["1"]
            return reverse("staff:orders") + ("?history=1" if history else "")
        return ""

    def get(self, request, *args, **kwargs):
        if can_view_orders(request.user):
            return redirect(self.get_success_url())
        return super().get(request, *args, **kwargs)


class StaffLogoutView(LogoutView):
    def get_success_url(self):
        return reverse("staff:login")


def staff_access(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse("staff:login"))
        if not can_view_orders(request.user):
            return render(request, "staff_portal/access_denied.html", status=403)
        return view(request, *args, **kwargs)
    return wrapped


@never_cache
@staff_access
@require_GET
def orders(request):
    queue = Order.objects.prefetch_related("items", Prefetch("notifications",
        queryset=OrderNotification.objects.filter(channel=OrderNotification.Channel.EMAIL)))
    history = request.GET.get("history") == "1"
    if history:
        queue = queue.filter(status__in=[Order.Status.COMPLETED, Order.Status.CANCELLED])[:50]
    else:
        queue = queue.exclude(status__in=[Order.Status.COMPLETED, Order.Status.CANCELLED]).order_by("created_at")
    context = {"orders": queue, "history": history,
               "can_change": request.user.has_perm("website.change_order"),
               "notification_issues": configuration_issues(), "checked_at": timezone.now()}
    template = "staff_portal/includes/order_queue.html" if request.GET.get("partial") == "1" else "staff_portal/orders.html"
    return render(request, template, context)


@never_cache
@staff_access
@require_POST
def order_status(request, order_id):
    if not request.user.has_perm("website.change_order"):
        return render(request, "staff_portal/access_denied.html", {"view_only": True}, status=403)
    order = get_object_or_404(Order, pk=order_id)
    status = request.POST.get("status")
    allowed = [order.next_status] if order.next_status else []
    if order.status in [Order.Status.NEW, Order.Status.ACCEPTED, Order.Status.READY]:
        allowed.append(Order.Status.CANCELLED)
    if status not in allowed or request.POST.get("previous_status") != order.status:
        messages.error(request, "This order changed. Check its current status before updating it.")
    else:
        updated = Order.objects.filter(pk=order.id, status=order.status).update(status=status, updated_at=timezone.now())
        if not updated:
            messages.error(request, "Another team member updated this order. Please check its status.")
    return redirect("staff:orders")
