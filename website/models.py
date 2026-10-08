import uuid
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator, URLValidator
from django.db import models, transaction
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils import timezone


class Subscriber(models.Model):
    email = models.EmailField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.email


def new_product_id():
    return uuid.uuid4().hex


class MenuPrice(models.Model):
    class Category(models.TextChoices):
        COFFEE = "coffee", "Coffee"
        TEA = "tea", "Tea"
        DRINKS = "drinks", "Juices & smoothies"
        FOOD = "food", "Food"

    product_id = models.SlugField(primary_key=True, editable=False, default=new_product_id)
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=6, choices=Category.choices)
    note = models.CharField("description", max_length=240, blank=True)
    price = models.DecimalField("price (GH₵)", max_digits=7, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal("0.01"))])
    call_to_order = models.BooleanField(default=False,
        help_text="Show this item on the menu, but ask customers to call instead of adding it to their basket.")
    price_label = models.CharField("display price", max_length=40, blank=True,
        help_text="For call-to-order items only, e.g. GH₵30 / 45 or Ask for price. Leave blank to display the price above.")
    order_note_prompt = models.CharField("required order choices", max_length=240, blank=True,
        help_text="For combos, say which choices the customer must write in their checkout notes.")
    is_active = models.BooleanField("on the menu", default=True,
        help_text="Uncheck to remove this product from the menu temporarily. Existing orders are kept.")
    photo = models.ImageField("photo", upload_to="menu/", blank=True,
        help_text="Upload a photo from your computer: JPG, PNG or WebP, up to 8 MB. It is resized for the menu automatically "
                  "and shown instead of any photo URL or built-in artwork.")
    image_url = models.URLField("photo URL", max_length=500, blank=True, validators=[URLValidator(schemes=["https"])],
        help_text="Optional HTTPS address of a product photo, used when no photo is uploaded. "
                  "Leave blank to keep the existing photo or show the shop's bean mark.")
    image_path = models.CharField(max_length=200, blank=True, editable=False)
    featured = models.BooleanField(default=False, editable=False)
    display_order = models.PositiveSmallIntegerField(default=1000, help_text="Lower numbers appear first.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "menu product"
        verbose_name_plural = "menu products"
        constraints = [models.CheckConstraint(condition=models.Q(price__gte=Decimal("0.01")),
                                               name="menu_price_positive"),
                       models.CheckConstraint(condition=models.Q(category__in=["coffee", "tea", "drinks", "food"]),
                                               name="menu_product_category"),
                       models.CheckConstraint(condition=models.Q(call_to_order=True) | models.Q(price__isnull=False),
                                               name="orderable_product_has_price"),
                       models.CheckConstraint(condition=models.Q(call_to_order=True) | models.Q(price_label=""),
                                               name="price_label_requires_call")]

    def clean(self):
        super().clean()
        if not self.call_to_order and self.price is None:
            raise ValidationError({"price": "Enter a price for online ordering, or select Call to order."})
        if self.price_label and not self.call_to_order:
            raise ValidationError({"price_label": "Display prices are only for call-to-order items. Online orders use the price above."})

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        previous = None
        update_fields = kwargs.get("update_fields")
        photo_included = update_fields is None or "photo" in update_fields
        if self.pk and photo_included:
            previous = MenuPrice.objects.filter(pk=self.pk).values_list("photo", flat=True).first()
        super().save(*args, **kwargs)
        # A replaced or cleared upload is deleted once the change is committed, so the media folder holds no orphans.
        if not photo_included or not previous:
            return
        persisted = MenuPrice.objects.filter(pk=self.pk).values_list("photo", flat=True).first()
        if previous != persisted:
            storage = self.photo.storage
            transaction.on_commit(lambda: storage.delete(previous))


# Runs for single and bulk admin deletes alike (bulk deletes skip Model.delete).
@receiver(post_delete, sender=MenuPrice)
def remove_deleted_product_photo(sender, instance, **kwargs):
    if instance.photo.name:
        name, storage = instance.photo.name, instance.photo.storage
        transaction.on_commit(lambda: storage.delete(name))


class Discount(models.Model):
    class Scope(models.TextChoices):
        ALL = "all", "All products"
        PRODUCT = "product", "One product"

    scope = models.CharField("apply to", max_length=7, choices=Scope.choices, default=Scope.ALL)
    product = models.ForeignKey(MenuPrice, on_delete=models.CASCADE, null=True, blank=True,
        related_name="discounts", help_text="Choose a product only when applying the discount to one product.")
    percentage = models.DecimalField("discount percentage", max_digits=5, decimal_places=2,
        validators=[MinValueValidator(Decimal("0")), MaxValueValidator(Decimal("100"))],
        help_text="Enter 0 to 100. A product discount replaces the all-products discount; they never add together. "
                  "Use 0 for a product to exclude it from the all-products discount.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["scope", "product__name"]
        constraints = [
            models.CheckConstraint(condition=models.Q(percentage__gte=0, percentage__lte=100),
                                   name="discount_percentage_range"),
            models.CheckConstraint(condition=(models.Q(scope="all", product__isnull=True)
                                              | models.Q(scope="product", product__isnull=False)),
                                   name="discount_scope_matches_product"),
            models.UniqueConstraint(fields=["scope"], condition=models.Q(scope="all"),
                                    name="one_all_products_discount"),
            models.UniqueConstraint(fields=["product"], condition=models.Q(scope="product"),
                                    name="one_discount_per_product"),
        ]

    def clean(self):
        super().clean()
        if self.scope == self.Scope.PRODUCT and not self.product_id:
            raise ValidationError({"product": "Choose the product that should receive this discount."})
        if self.scope == self.Scope.ALL and self.product_id:
            raise ValidationError({"product": "Leave Product empty when applying a discount to all products."})
        others = type(self).objects.exclude(pk=self.pk)
        if self.scope == self.Scope.ALL and others.filter(scope=self.Scope.ALL).exists():
            raise ValidationError({"scope": "An all-products discount already exists. Edit that discount instead."})
        if self.scope == self.Scope.PRODUCT and self.product_id and others.filter(product_id=self.product_id).exists():
            raise ValidationError({"product": "This product already has a discount. Edit that discount instead."})

    def __str__(self):
        target = self.product.name if self.product_id else "All products"
        return f"{target}: {self.percentage:g}% off"


class Customer(models.Model):
    name = models.CharField(max_length=80)
    phone = models.CharField(max_length=20, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.name} · {self.phone}"


class Order(models.Model):
    class Status(models.TextChoices):
        NEW = "new", "Awaiting shop confirmation"
        ACCEPTED = "accepted", "Preparing your order"
        READY = "ready", "Ready for pickup"
        COMPLETED = "completed", "Collected"
        CANCELLED = "cancelled", "Cancelled"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    checkout_token = models.UUIDField(unique=True, editable=False)
    owner_token = models.UUIDField(editable=False)
    customer = models.ForeignKey(Customer, related_name="orders", on_delete=models.SET_NULL, null=True, blank=True)
    customer_name = models.CharField(max_length=80)
    phone = models.CharField(max_length=20)
    notes = models.CharField(max_length=500, blank=True)
    total = models.DecimalField(max_digits=9, decimal_places=2)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.NEW)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    @property
    def reference(self):
        return f"DG-{self.id.hex[:10].upper()}"

    @property
    def next_status(self):
        return {self.Status.NEW: self.Status.ACCEPTED, self.Status.ACCEPTED: self.Status.READY,
                self.Status.READY: self.Status.COMPLETED}.get(self.status)

    def __str__(self):
        return self.reference


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name="items", on_delete=models.CASCADE)
    product_id = models.SlugField()
    name = models.CharField(max_length=120)
    quantity = models.PositiveSmallIntegerField()
    unit_price = models.DecimalField(max_digits=7, decimal_places=2)

    class Meta:
        constraints = [models.CheckConstraint(condition=models.Q(quantity__gte=1, quantity__lte=20),
                                               name="order_item_quantity_range")]

    @property
    def subtotal(self):
        return self.unit_price * self.quantity


class OrderNotification(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "email", "Email"
        # Kept for historical records; checkout and the worker use email only.
        WHATSAPP = "whatsapp", "WhatsApp"

    class Status(models.TextChoices):
        PENDING = "pending", "Queued"
        BLOCKED = "blocked", "Needs configuration"
        SUBMITTED = "submitted", "Sent to provider"
        FAILED = "failed", "Needs retry"

    order = models.ForeignKey(Order, related_name="notifications", on_delete=models.CASCADE)
    channel = models.CharField(max_length=10, choices=Channel.choices)
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.UUIDField(null=True, blank=True, editable=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    provider_id = models.CharField(max_length=100, blank=True)
    last_error = models.CharField(max_length=240, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["order", "channel"], name="one_alert_per_channel")]
        indexes = [models.Index(fields=["status", "next_attempt_at"])]
