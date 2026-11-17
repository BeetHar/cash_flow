from django.urls import path

from . import management_views, procurement_views, views


app_name = "web"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("health/", views.health_view, name="health"),
    path("settings/users/", management_views.user_list_view, name="user-list"),
    path(
        "settings/users/new/",
        management_views.user_create_view,
        name="user-create",
    ),
    path(
        "settings/users/<uuid:user_id>/edit/",
        management_views.user_edit_view,
        name="user-edit",
    ),
    path(
        "settings/users/<uuid:user_id>/password/",
        management_views.user_password_view,
        name="user-password",
    ),
    path("settings/roles/", management_views.role_list_view, name="role-list"),
    path(
        "settings/roles/new/",
        management_views.role_create_view,
        name="role-create",
    ),
    path(
        "settings/roles/<int:role_id>/edit/",
        management_views.role_edit_view,
        name="role-edit",
    ),
    path(
        "purchase-orders/",
        procurement_views.purchase_order_list_view,
        name="purchase-order-list",
    ),
    path(
        "purchase-orders/new/",
        procurement_views.purchase_order_create_view,
        name="purchase-order-create",
    ),
    path(
        "purchase-orders/<uuid:purchase_order_id>/",
        procurement_views.purchase_order_detail_view,
        name="purchase-order-detail",
    ),
    path(
        "purchase-orders/<uuid:purchase_order_id>/edit/",
        procurement_views.purchase_order_edit_view,
        name="purchase-order-edit",
    ),
    path(
        "purchase-orders/<uuid:purchase_order_id>/cancel/",
        procurement_views.purchase_order_cancel_view,
        name="purchase-order-cancel",
    ),
    path("suppliers/", procurement_views.supplier_list_view, name="supplier-list"),
    path(
        "suppliers/new/",
        procurement_views.supplier_create_view,
        name="supplier-create",
    ),
    path(
        "suppliers/import/",
        procurement_views.supplier_import_view,
        name="supplier-import",
    ),
    path(
        "suppliers/import/confirm/",
        procurement_views.supplier_import_confirm_view,
        name="supplier-import-confirm",
    ),
    path(
        "suppliers/<uuid:supplier_id>/edit/",
        procurement_views.supplier_edit_view,
        name="supplier-edit",
    ),
]
