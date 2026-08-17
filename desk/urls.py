from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("setup/", views.setup, name="setup"),
    path("login/", views.login_view, name="login"),
    path("logout/", views.logout_view, name="logout"),
    path("account/password/", views.change_password, name="change_password"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("records/", views.records, name="records"),
    path("records/new/<slug:module_key>/", views.record_form, name="record_new"),
    path("records/<uuid:record_id>/edit/<slug:module_key>/", views.record_form, name="record_edit"),
    path("reports/", views.reports, name="reports"),
    path("reports/export/<str:file_type>/", views.export_records, name="export_records"),
    path("reports/visibility/", views.field_visibility, name="field_visibility"),
    path("reports/<slug:module_key>/", views.module_report, name="module_report"),
    path("reports/<slug:module_key>/export/<str:file_type>/", views.export_report, name="export_report"),
    path("users/", views.users, name="users"),
    path("users/<str:user_id>/toggle/", views.toggle_user, name="toggle_user"),
    path("users/<str:user_id>/password/", views.reset_password, name="reset_password"),
    path("forms/", views.form_controls, name="form_controls"),
    path("audit/", views.audit_log, name="audit_log"),
    path("backup/", views.backup, name="backup"),
    path("backup/download/", views.backup_download, name="backup_download"),
    path("health/", views.health, name="health"),
]
