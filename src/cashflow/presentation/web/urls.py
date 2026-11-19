from django.urls import path

from . import management_views, procurement_views, receivables_views, views


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
    path("daily/", receivables_views.daily_view, name="daily"),
    path("customers/", receivables_views.customer_list_view, name="customer-list"),
    path("customers/new/", receivables_views.customer_form_view, name="customer-create"),
    path("customers/<uuid:customer_id>/edit/", receivables_views.customer_form_view, name="customer-edit"),
    path("sales-invoices/", receivables_views.invoice_list_view, name="sales-invoice-list"),
    path("sales-invoices/new/", receivables_views.invoice_form_view, name="sales-invoice-create"),
    path("sales-invoices/import/", receivables_views.invoice_import_view, name="sales-invoice-import"),
    path("sales-invoices/import/confirm/", receivables_views.invoice_import_confirm_view, name="sales-invoice-import-confirm"),
    path("sales-invoices/<uuid:invoice_id>/", receivables_views.invoice_detail_view, name="sales-invoice-detail"),
    path("sales-invoices/<uuid:invoice_id>/edit/", receivables_views.invoice_form_view, name="sales-invoice-edit"),
    path("sales-invoices/<uuid:invoice_id>/<str:action>/", receivables_views.invoice_action_view, name="sales-invoice-action"),
    path("receipt-plans/", receivables_views.plan_list_view, name="receipt-plan-list"),
    path("receipt-plans/new/", receivables_views.plan_form_view, name="receipt-plan-create"),
    path("receipt-plans/<uuid:plan_id>/", receivables_views.plan_detail_view, name="receipt-plan-detail"),
    path("receipt-plans/<uuid:plan_id>/edit/", receivables_views.plan_form_view, name="receipt-plan-edit"),
]
