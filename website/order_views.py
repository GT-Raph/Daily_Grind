import uuid

from django.conf import settings
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from .cart import MAX_ITEMS, MAX_PER_ITEM, catalogue, fingerprint, get_cart
from .content import page_content
from .forms import CheckoutForm
from .models import Customer, Order, OrderItem, OrderNotification


@require_POST
def change_cart(request):
    error = None
    product_id = request.POST.get("product_id", "")
    action = request.POST.get("action", "add")
    cart = {line["id"]: line["quantity"] for line in get_cart(request)["lines"]}
    try:
        quantity = int(request.POST.get("quantity", "1"))
    except (ValueError, TypeError):
        quantity = -1
    if not settings.ORDERING_ENABLED:
        error = "Online ordering is currently unavailable. Please call the shop."
    elif product_id not in catalogue() or action not in {"add", "update", "remove"}:
        error = "That item is unavailable. Please choose from the menu."
    else:
        amount = 0 if action == "remove" else quantity + (cart.get(product_id, 0) if action == "add" else 0)
        if quantity < 0 or (action != "remove" and not 1 <= amount <= MAX_PER_ITEM):
            error = f"Choose between 1 and {MAX_PER_ITEM} of each item, or select Remove."
        elif sum(cart.values()) - cart.get(product_id, 0) + amount > MAX_ITEMS:
            error = f"Please call the shop for orders of more than {MAX_ITEMS} items."
        else:
            if amount:
                cart[product_id] = amount
            else:
                cart.pop(product_id, None)
            request.session["cart"] = cart
            request.session.pop("checkout_token", None)
            request.session.pop("checkout_fingerprint", None)
    if request.headers.get("Accept") == "application/json":
        basket = get_cart(request)
        return JsonResponse({"error": error, "count": basket["count"], "total": str(basket["total"])}, status=400 if error else 200)
    if error:
        messages.error(request, error)
    return redirect("website:basket")


@never_cache
@require_GET
def basket(request):
    cart = get_cart(request)
    available = {line["id"]: line["quantity"] for line in cart["lines"]}
    if set(request.session.get("cart", {})) - set(available):
        messages.warning(request, "Some items are no longer available and have been removed from your order.")
        request.session["cart"] = available
    return render(request, "website/basket.html", {**page_content(), "basket": cart})


def prepare_checkout(request, cart):
    current = fingerprint(cart)
    if not request.session.get("checkout_token") or request.session.get("checkout_fingerprint") != current:
        request.session["checkout_token"] = str(uuid.uuid4())
        request.session["checkout_fingerprint"] = current
    if not request.session.get("order_owner"):
        request.session["order_owner"] = str(uuid.uuid4())
    return request.session["checkout_token"]


@never_cache
@require_http_methods(["GET", "POST"])
def checkout(request):
    cart = get_cart(request)
    # A retry of a successful POST returns the same receipt, even after the basket is cleared.
    if request.method == "POST" and request.session.get("order_owner"):
        try:
            token = uuid.UUID(request.POST.get("checkout_token", ""))
        except (ValueError, TypeError, AttributeError):
            token = None
        existing = Order.objects.filter(checkout_token=token, owner_token=request.session["order_owner"]).first() if token else None
        if existing:
            return redirect("website:receipt", order_id=existing.id)
    if not settings.ORDERING_ENABLED or not cart["lines"]:
        return redirect("website:basket")
    status = 200
    if request.method == "POST":
        form = CheckoutForm(request.POST, cart=cart)
        valid = form.is_valid()
        if (str(form.cleaned_data.get("checkout_token", "")) != request.session.get("checkout_token")
                or request.session.get("checkout_fingerprint") != fingerprint(cart)):
            token = prepare_checkout(request, cart)
            data = request.POST.copy()
            data["checkout_token"] = token
            form = CheckoutForm(data, cart=cart)
            form.is_valid()
            form.add_error(None, "Your basket has changed. Review the total and place your order again.")
            valid = False
        if valid:
            try:
                with transaction.atomic():
                    customer, _ = Customer.objects.update_or_create(phone=form.cleaned_data["phone"],
                        defaults={"name": form.cleaned_data["customer_name"]})
                    order = Order.objects.create(
                        **form.cleaned_data, customer=customer, owner_token=request.session["order_owner"], total=cart["total"])
                    OrderItem.objects.bulk_create([OrderItem(order=order, product_id=line["id"],
                        name=line["name"], quantity=line["quantity"], unit_price=line["price"]) for line in cart["lines"]])
                    OrderNotification.objects.create(order=order, channel=OrderNotification.Channel.EMAIL)
            except IntegrityError:
                order = Order.objects.filter(checkout_token=form.cleaned_data["checkout_token"],
                    owner_token=request.session["order_owner"]).first()
                if order is None:
                    raise
            request.session["cart"] = {}
            request.session.pop("checkout_token", None)
            request.session.pop("checkout_fingerprint", None)
            return redirect("website:receipt", order_id=order.id)
        status = 400
    else:
        form = CheckoutForm(initial={"checkout_token": prepare_checkout(request, cart)}, cart=cart)
    return render(request, "website/checkout.html", {**page_content(), "basket": cart, "checkout_form": form}, status=status)


@never_cache
@require_GET
def receipt(request, order_id):
    order = get_object_or_404(Order.objects.prefetch_related("items"), pk=order_id,
                             owner_token=request.session.get("order_owner") or uuid.UUID(int=0))
    template = "website/includes/receipt_details.html" if request.GET.get("partial") == "1" else "website/receipt.html"
    return render(request, template, {**page_content(), "order": order})
