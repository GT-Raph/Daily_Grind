from django.urls import path

from . import views

app_name = "staff"
urlpatterns = [
    path("", views.orders, name="orders"),
    path("login/", views.StaffLoginView.as_view(), name="login"),
    path("logout/", views.StaffLogoutView.as_view(), name="logout"),
    path("orders/<uuid:order_id>/status/", views.order_status, name="order_status"),
]
