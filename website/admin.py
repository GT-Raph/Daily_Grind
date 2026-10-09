from django import forms
from django.contrib import admin
from django.core.files.uploadedfile import UploadedFile
from django.db.models import Count, Max, Min, Q, Sum
from django.urls import reverse
from django.utils import timezone
from django.templatetags.static import static
from django.utils.html import format_html
from urllib.parse import urlencode
from decimal import Decimal
import re

from .models import Customer, Discount, MenuPrice, Order, OrderItem, OrderNotification, Subscriber
from .photos import NOT_A_PHOTO, prepare_menu_photo

# The shop's name instead of Django's defaults: the page heading, the browser tab, and the dashboard.
admin.site.site_header = "The Daily Grind shop admin"
admin.site.site_title = "The Daily Grind admin"
admin.site.index_title = "Manage the shop"


@admin.register(Subscriber)
class SubscriberAdmin(admin.ModelAdmin):
    list_display = ("email", "created_at")
    search_fields = ("email",)
    readonly_fields = ("created_at",)


class AdministratorOnlyAdmin(admin.ModelAdmin):
    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_staff and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        # Model permissions alone never grant access to pricing or discounts.
        return self.has_view_permission(request, obj)

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def has_add_permission(self, request):
        return self.has_view_permission(request)

    def has_delete_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)


class MenuPriceForm(forms.ModelForm):
    class Meta:
        model = MenuPrice
        fields = "__all__"
        widgets = {"photo": forms.ClearableFileInput(attrs={"accept": "image/jpeg,image/png,image/webp"})}
        error_messages = {"photo": {"invalid_image": NOT_A_PHOTO}}

    def clean_photo(self):
        photo = self.cleaned_data.get("photo")
        # Only a newly chosen file is processed; an existing photo or a cleared one passes through unchanged.
        if isinstance(photo, UploadedFile):
            return prepare_menu_photo(photo, self.instance.pk or "product")
        return photo


@admin.register(MenuPrice)
class MenuPriceAdmin(AdministratorOnlyAdmin):
    form = MenuPriceForm
    list_display = ("name", "category", "price", "call_to_order", "is_active", "updated_at")
    list_filter = ("category", "is_active", "call_to_order")
    search_fields = ("name",)
    fields = ("name", "category", "note", "price", "call_to_order", "price_label", "order_note_prompt",
              "is_active", "current_photo", "photo", "image_url", "display_order", "updated_at")
    readonly_fields = ("current_photo", "updated_at")

    @admin.display(description="shown on the menu")
    def current_photo(self, product):
        if product.photo:
            source, label = product.photo.url, "Uploaded photo"
        elif product.image_url:
            source, label = product.image_url, "Photo from URL"
        elif product.image_path:
            source, label = static(product.image_path), "Built-in menu artwork"
        else:
            return "No photo yet. The menu shows the shop's bean mark."
        return format_html('<img src="{}" alt="" width="120" height="120" style="object-fit:contain;background:#fff;'
                           'border-radius:6px"><br>{}', source, label)
    actions = ("hide_products", "show_products")

    @admin.action(description="Remove selected products from the menu", permissions=["change"])
    def hide_products(self, request, queryset):
        for product in queryset.filter(is_active=True):
            product.is_active = False
            product.save(update_fields=["is_active", "updated_at"])
            self.log_change(request, product, "Removed from the menu.")
        self.message_user(request, "Selected products are off the menu. Existing orders are preserved.")

    @admin.action(description="Put selected products on the menu", permissions=["change"])
    def show_products(self, request, queryset):
        for product in queryset.filter(is_active=False):
            product.is_active = True
            product.save(update_fields=["is_active", "updated_at"])
            self.log_change(request, product, "Put back on the menu.")
        self.message_user(request, "Selected products are on the menu.")


@admin.register(Discount)
class DiscountAdmin(AdministratorOnlyAdmin):
    list_display = ("applies_to", "percent_off", "updated_at")
    list_filter = ("scope",)
    list_select_related = ("product",)
    search_fields = ("product__name",)
    fields = ("scope", "product", "percentage", "updated_at")
    readonly_fields = ("updated_at",)

    @admin.display(description="Applies to", ordering="product__name")
    def applies_to(self, obj):
        return obj.product.name if obj.product_id else "All products"

    @admin.display(description="Discount", ordering="percentage")
    def percent_off(self, obj):
        return f"{obj.percentage:g}%"


class CustomerActivityFilter(admin.SimpleListFilter):
    title = "customer activity"
    parameter_name = "activity"

    def lookups(self, request, model_admin):
        return [("repeat", "Repeat customers (2+ collected orders)"),
                ("once", "One collected order"), ("none", "No collected orders yet")]

    def queryset(self, request, queryset):
        if self.value() == "repeat":
            return queryset.filter(completed_count__gte=2)
        if self.value() == "once":
            return queryset.filter(completed_count=1)
        if self.value() == "none":
            return queryset.filter(completed_count=0)
        return queryset


@admin.register(Customer)
class CustomerAdmin(AdministratorOnlyAdmin):
    list_display = ("name", "completed_orders", "total_spent", "phone", "last_order", "order_history")
    search_fields = ("name", "phone")
    list_filter = (CustomerActivityFilter,)
    readonly_fields = ("name", "phone", "completed_orders", "total_spent", "first_order", "last_order", "order_history")
    fields = readonly_fields
    actions = None

    def get_queryset(self, request):
        completed = Q(orders__status=Order.Status.COMPLETED)
        return self.model.objects.annotate(
            completed_count=Count("orders", filter=completed),
            spent_total=Sum("orders__total", filter=completed, default=Decimal("0.00")),
            first_order_at=Min("orders__created_at"), last_order_at=Max("orders__created_at"),
        ).order_by(*self.get_ordering(request))

    def get_ordering(self, request):
        return ("-completed_count", "-spent_total", "name")

    def get_search_results(self, request, queryset, search_term):
        results, may_duplicate = super().get_search_results(request, queryset, search_term)
        phone = re.sub(r"[\s()\-]", "", search_term)
        if re.fullmatch(r"0\d{9}", phone):
            phone = "+233" + phone[1:]
        if re.fullmatch(r"\+[1-9]\d{7,14}", phone):
            results = results | queryset.filter(phone=phone)
        return results, may_duplicate

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Collected orders", ordering="completed_count")
    def completed_orders(self, obj):
        return obj.completed_count

    @admin.display(description="Spent (GH₵)", ordering="spent_total")
    def total_spent(self, obj):
        return f"{obj.spent_total:,.2f}"

    @admin.display(description="First order", ordering="first_order_at")
    def first_order(self, obj):
        return obj.first_order_at

    @admin.display(description="Last order", ordering="last_order_at")
    def last_order(self, obj):
        return obj.last_order_at

    @admin.display(description="Order history")
    def order_history(self, obj):
        url = reverse("admin:website_order_changelist") + "?" + urlencode({"customer__id__exact": obj.pk})
        return format_html('<a href="{}">View orders</a>', url)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0
    readonly_fields = ("product_id", "name", "quantity", "unit_price")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class NotificationInline(admin.TabularInline):
    model = OrderNotification
    extra = 0
    fields = ("channel", "status", "attempts", "last_error", "submitted_at", "provider_id")
    readonly_fields = fields
    can_delete = False

    def get_queryset(self, request):
        return super().get_queryset(request).filter(channel=OrderNotification.Channel.EMAIL)

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("reference", "customer_name", "phone", "total", "status", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("id", "customer_name", "phone")
    readonly_fields = ("id", "customer", "customer_name", "phone", "notes", "total", "created_at", "updated_at")
    exclude = ("checkout_token", "owner_token")
    inlines = (OrderItemInline, NotificationInline)
    actions = ("retry_alerts",)

    def has_add_permission(self, request):
        return False

    @admin.action(description="Retry failed / unconfigured order alerts", permissions=["change"])
    def retry_alerts(self, request, queryset):
        count = OrderNotification.objects.filter(order__in=queryset, channel=OrderNotification.Channel.EMAIL,
            status__in=["failed", "blocked"],
            lease_until__isnull=True).update(status="pending", attempts=0, next_attempt_at=timezone.now(), last_error="")
        self.message_user(request, f"Queued {count} alerts for the notification worker.")
