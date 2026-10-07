from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from .content import page_content
from .forms import SubscriptionForm
from .models import Subscriber


@require_GET
def home(request):
    return render(request, "website/home.html", {**page_content(), "form": SubscriptionForm()})


@require_POST
def subscribe(request):
    form = SubscriptionForm(request.POST)
    if not form.is_valid():
        return render(request, "website/home.html", {**page_content(), "form": form}, status=400)
    Subscriber.objects.get_or_create(email=form.cleaned_data["email"])
    messages.success(request, "You're on the list. We'll email you when there's something new.")
    return redirect(reverse("website:home") + "#newsletter")
