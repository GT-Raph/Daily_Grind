from django.urls import path
from django.views.generic import RedirectView
from staff_portal import views as staff_views
from . import order_views, views

app_name = "website"
urlpatterns = [
    path("", views.home, name="home"), path("subscribe/", views.subscribe, name="subscribe"),
    path("order/", order_views.basket, name="basket"),
    path("order/items/", order_views.change_cart, name="change_cart"),
    path("order/checkout/", order_views.checkout, name="checkout"),
    path("order/receipt/<uuid:order_id>/", order_views.receipt, name="receipt"),
    # Preserve bookmarks and already-open forms while staff move to /staff/.
    path("shop/orders/", RedirectView.as_view(pattern_name="staff:orders", query_string=True), name="shop_orders"),
    path("shop/orders/<uuid:order_id>/status/", staff_views.order_status, name="order_status"),
]
