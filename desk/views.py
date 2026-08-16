from __future__ import annotations

import base64
import csv
import io
import json
from datetime import timedelta
from functools import wraps
from typing import Any, Callable

from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import IntegrityError, connection, transaction
from django.db.models import Q, QuerySet
from django.http import Http404, HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from tvs_dms.exporter import tabular
from tvs_dms.forms import MODULES, MODULES_BY_ROLE, ROLE_LABELS, modules_for_role
from tvs_dms.security import SecurityError, encrypt_bytes

from .crypto import data_key, key_fingerprint
from .forms import (
    ActivityEntryForm,
    LoginForm,
    PasswordResetForm,
    SetupForm,
    StrongPasswordChangeForm,
    UserCreateForm,
)
from .models import ActivityRecord, AuditLog, ModuleControl, Profile, SiteSettings


def initialized() -> bool:
    return User.objects.exists()


def role_of(user: User) -> str:
    try:
        return user.desk_profile.role
    except Profile.DoesNotExist as exc:
        raise PermissionDenied("This account has no Activity Desk role.") from exc


def admin_required(view: Callable) -> Callable:
    @wraps(view)
    @login_required
    def wrapped(request: HttpRequest, *args: Any, **kwargs: Any) -> HttpResponse:
        if role_of(request.user) != "administrator":
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapped


def audit(user: User | None, action: str, target: str = "") -> None:
    AuditLog.objects.create(user=user, action=action, target=target[:255])


def module_enabled(module_key: str) -> bool:
    control = ModuleControl.objects.filter(module_key=module_key).first()
    return True if control is None else control.enabled


def allowed_modules(user: User, include_disabled: bool = False):
    modules = modules_for_role(role_of(user))
    if include_disabled or role_of(user) == "administrator":
        return modules
    disabled = set(ModuleControl.objects.filter(enabled=False).values_list("module_key", flat=True))
    return [module for module in modules if module.key not in disabled]


def records_for(user: User) -> QuerySet[ActivityRecord]:
    queryset = ActivityRecord.objects.select_related("owner", "owner__desk_profile")
    return queryset if role_of(user) == "administrator" else queryset.filter(owner=user)


def record_to_dict(record: ActivityRecord) -> dict[str, Any]:
    profile = getattr(record.owner, "desk_profile", None)
    return {
        "id": str(record.id),
        "module_key": record.module_key,
        "module_name": record.module_name,
        "role": record.role,
        "status": record.status,
        "owner_name": profile.display_name if profile else record.owner.username,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "data": record.get_data(),
    }


@require_GET
def home(request: HttpRequest) -> HttpResponse:
    if not initialized():
        return redirect("setup")
    return redirect("dashboard" if request.user.is_authenticated else "login")


@require_http_methods(["GET", "POST"])
def setup(request: HttpRequest) -> HttpResponse:
    if initialized():
        return redirect("dashboard" if request.user.is_authenticated else "login")
    form = SetupForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                if initialized():
                    raise IntegrityError("Setup was completed in another request.")
                user = User.objects.create_user(
                    username=form.cleaned_data["username"],
                    password=form.cleaned_data["password"],
                )
                Profile.objects.create(
                    user=user,
                    display_name=form.cleaned_data["display_name"].strip(),
                    role="administrator",
                    must_change_password=False,
                )
                SiteSettings.objects.create(school_name=form.cleaned_data["school_name"].strip())
                audit(user, "system_setup", "cloud_database")
        except IntegrityError:
            messages.error(request, "Setup has already been completed. Sign in instead.")
            return redirect("login")
        auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        messages.success(request, "Secure workspace created. Add staff accounts from Users.")
        return redirect("dashboard")
    return render(request, "desk/setup.html", {"form": form, "setup_mode": True})


@require_http_methods(["GET", "POST"])
def login_view(request: HttpRequest) -> HttpResponse:
    if not initialized():
        return redirect("setup")
    if request.user.is_authenticated:
        return redirect("dashboard")
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"].strip()
        user = User.objects.filter(username__iexact=username).select_related("desk_profile").first()
        generic_error = "Invalid username or password."
        if not user or not user.is_active:
            form.add_error(None, generic_error)
        else:
            profile = user.desk_profile
            now = timezone.now()
            if profile.locked_until and profile.locked_until > now:
                seconds = max(1, int((profile.locked_until - now).total_seconds()))
                form.add_error(None, f"Account temporarily locked. Try again in {seconds} seconds.")
            elif not user.check_password(form.cleaned_data["password"]):
                profile.failed_attempts += 1
                if profile.failed_attempts >= 5:
                    profile.failed_attempts = 0
                    profile.locked_until = now + timedelta(minutes=5)
                profile.save(update_fields=("failed_attempts", "locked_until", "updated_at"))
                form.add_error(None, generic_error)
            else:
                profile.failed_attempts = 0
                profile.locked_until = None
                profile.save(update_fields=("failed_attempts", "locked_until", "updated_at"))
                auth_login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                audit(user, "login", user.username)
                next_url = request.POST.get("next", "")
                if next_url.startswith("/") and not next_url.startswith("//"):
                    return redirect(next_url)
                return redirect("dashboard")
    return render(request, "desk/login.html", {"form": form, "next": request.GET.get("next", "")})


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        audit(request.user, "logout", request.user.username)
    auth_logout(request)
    return redirect("login")


@login_required
@require_http_methods(["GET", "POST"])
def change_password(request: HttpRequest) -> HttpResponse:
    form = StrongPasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        profile = user.desk_profile
        profile.must_change_password = False
        profile.failed_attempts = 0
        profile.locked_until = None
        profile.save(update_fields=("must_change_password", "failed_attempts", "locked_until", "updated_at"))
        update_session_auth_hash(request, user)
        audit(user, "password_changed", user.username)
        messages.success(request, "Your password has been changed.")
        return redirect("dashboard")
    return render(request, "desk/change_password.html", {"form": form})


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    query = request.GET.get("q", "").strip()
    modules = allowed_modules(request.user)
    if query:
        modules = [module for module in modules if query.casefold() in module.name.casefold()]
    records = records_for(request.user)
    counts = {
        "total": records.count(),
        "submitted": records.filter(status=ActivityRecord.SUBMITTED).count(),
        "draft": records.filter(status=ActivityRecord.DRAFT).count(),
    }
    grouped: list[tuple[str, list[Any]]] = []
    for role, label in ROLE_LABELS.items():
        role_modules = [module for module in modules if module.role == role]
        if role_modules:
            grouped.append((label, role_modules))
    return render(request, "desk/dashboard.html", {"counts": counts, "module_groups": grouped, "query": query})


def _load_record_for_user(user: User, record_id: str) -> ActivityRecord:
    record = get_object_or_404(ActivityRecord.objects.select_related("owner"), pk=record_id)
    if role_of(user) != "administrator" and record.owner_id != user.id:
        raise PermissionDenied
    return record


@login_required
@require_http_methods(["GET", "POST"])
def record_form(request: HttpRequest, module_key: str, record_id: str | None = None) -> HttpResponse:
    module = MODULES.get(module_key)
    if module is None:
        raise Http404("Unknown form")
    user_role = role_of(request.user)
    if user_role != "administrator" and user_role != module.role:
        raise PermissionDenied
    if user_role != "administrator" and not module_enabled(module.key):
        messages.error(request, "This form has been disabled by an administrator.")
        return redirect("dashboard")

    record = _load_record_for_user(request.user, record_id) if record_id else None
    if record and record.module_key != module.key:
        raise Http404("Record does not belong to this form")
    try:
        initial = record.get_data() if record else {}
    except SecurityError:
        messages.error(request, "This record could not be decrypted. Ask the administrator to check the data key.")
        return redirect("records")

    action = request.POST.get("action", "draft")
    submitted = action == "submit"
    form = ActivityEntryForm(
        request.POST or None,
        module=module,
        submitted=submitted,
        initial=initial,
    )
    if request.method == "POST" and form.is_valid():
        payload = form.payload()
        with transaction.atomic():
            if record is None:
                record = ActivityRecord(
                    module_key=module.key,
                    module_name=module.name,
                    role=module.role,
                    owner=request.user,
                )
            record.status = ActivityRecord.SUBMITTED if submitted else ActivityRecord.DRAFT
            record.event_date = form.cleaned_data.get("event_date")
            record.set_data(payload)
            record.save()
            audit(request.user, "record_updated" if record_id else "record_created", f"{module.key}:{record.id}")
        messages.success(request, f"{module.name} saved as {'submitted' if submitted else 'a draft'}.")
        return redirect("records")
    return render(
        request,
        "desk/record_form.html",
        {"form": form, "module": module, "module_role_label": ROLE_LABELS[module.role], "record": record},
    )


@login_required
def records(request: HttpRequest) -> HttpResponse:
    queryset = records_for(request.user)
    query = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()
    module_key = request.GET.get("module", "").strip()
    if query:
        queryset = queryset.filter(
            Q(module_name__icontains=query)
            | Q(owner__username__icontains=query)
            | Q(owner__desk_profile__display_name__icontains=query)
        )
    if status in {ActivityRecord.DRAFT, ActivityRecord.SUBMITTED}:
        queryset = queryset.filter(status=status)
    available = allowed_modules(request.user, include_disabled=True)
    allowed_keys = {module.key for module in available}
    if module_key in allowed_keys:
        queryset = queryset.filter(module_key=module_key)
    page = Paginator(queryset, 40).get_page(request.GET.get("page"))
    return render(
        request,
        "desk/records.html",
        {"page": page, "modules": available, "query": query, "status": status, "selected_module": module_key},
    )


@login_required
def reports(request: HttpRequest) -> HttpResponse:
    return render(request, "desk/reports.html", {"modules": allowed_modules(request.user, include_disabled=True)})


def _filtered_export_records(request: HttpRequest) -> list[dict[str, Any]]:
    queryset = records_for(request.user)
    status = request.GET.get("status", "")
    module_key = request.GET.get("module", "")
    allowed_keys = {module.key for module in allowed_modules(request.user, include_disabled=True)}
    if status in {ActivityRecord.DRAFT, ActivityRecord.SUBMITTED}:
        queryset = queryset.filter(status=status)
    if module_key in allowed_keys:
        queryset = queryset.filter(module_key=module_key)
    return [record_to_dict(record) for record in queryset]


@login_required
@require_GET
def export_records(request: HttpRequest, file_type: str) -> HttpResponse:
    rows = _filtered_export_records(request)
    headers, values = tabular(rows)
    timestamp = timezone.localtime().strftime("%Y%m%d-%H%M")
    if file_type == "csv":
        output = io.StringIO(newline="")
        writer = csv.writer(output)
        writer.writerow(headers)
        writer.writerows(values)
        response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="TVS-activity-records-{timestamp}.csv"'
    elif file_type == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Activity Records"
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = f"A1:{get_column_letter(max(1, len(headers)))}1"
        fill = PatternFill("solid", fgColor="183B66")
        for column, header in enumerate(headers, 1):
            cell = sheet.cell(1, column, header)
            cell.font = Font(color="FFFFFF", bold=True)
            cell.fill = fill
            cell.alignment = Alignment(vertical="center")
        for row_number, row in enumerate(values, 2):
            for column, value in enumerate(row, 1):
                sheet.cell(row_number, column, value)
        for column, header in enumerate(headers, 1):
            lengths = [len(str(row[column - 1])) for row in values[:200]]
            sheet.column_dimensions[get_column_letter(column)].width = min(45, max([12, len(header) + 2] + lengths))
        output_bytes = io.BytesIO()
        workbook.save(output_bytes)
        response = HttpResponse(
            output_bytes.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="TVS-activity-records-{timestamp}.xlsx"'
    else:
        raise Http404
    audit(request.user, f"export_{file_type}", f"{len(rows)} records")
    return response


@admin_required
@require_http_methods(["GET", "POST"])
def users(request: HttpRequest) -> HttpResponse:
    form = UserCreateForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            user = User.objects.create_user(
                username=form.cleaned_data["username"],
                password=form.cleaned_data["password"],
            )
            Profile.objects.create(
                user=user,
                display_name=form.cleaned_data["display_name"].strip(),
                role=form.cleaned_data["role"],
            )
            audit(request.user, "user_created", user.username)
        messages.success(request, f"Account created for {user.desk_profile.display_name}.")
        return redirect("users")
    user_rows = User.objects.select_related("desk_profile").order_by("desk_profile__display_name")
    return render(request, "desk/users.html", {"form": form, "users": user_rows})


@admin_required
@require_POST
def toggle_user(request: HttpRequest, user_id: int) -> HttpResponse:
    target = get_object_or_404(User.objects.select_related("desk_profile"), pk=user_id)
    if target == request.user:
        messages.error(request, "You cannot deactivate your own account.")
    else:
        target.is_active = not target.is_active
        target.save(update_fields=("is_active",))
        action = "user_activated" if target.is_active else "user_deactivated"
        audit(request.user, action, target.username)
        messages.success(request, f"{target.desk_profile.display_name} is now {'active' if target.is_active else 'inactive'}.")
    return redirect("users")


@admin_required
@require_http_methods(["GET", "POST"])
def reset_password(request: HttpRequest, user_id: int) -> HttpResponse:
    target = get_object_or_404(User.objects.select_related("desk_profile"), pk=user_id)
    form = PasswordResetForm(request.POST or None, user=target)
    if request.method == "POST" and form.is_valid():
        target.set_password(form.cleaned_data["password"])
        target.save(update_fields=("password",))
        target.desk_profile.failed_attempts = 0
        target.desk_profile.locked_until = None
        target.desk_profile.must_change_password = target != request.user
        target.desk_profile.save(
            update_fields=("failed_attempts", "locked_until", "must_change_password", "updated_at")
        )
        audit(request.user, "password_reset", target.username)
        messages.success(request, f"Password reset for {target.desk_profile.display_name}.")
        return redirect("users")
    return render(request, "desk/reset_password.html", {"form": form, "target": target})


@admin_required
@require_http_methods(["GET", "POST"])
def form_controls(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        module_key = request.POST.get("module_key", "")
        module = MODULES.get(module_key)
        if not module:
            raise Http404
        control, _ = ModuleControl.objects.get_or_create(module_key=module_key)
        control.enabled = request.POST.get("enabled") == "true"
        control.save()
        audit(request.user, "form_enabled" if control.enabled else "form_disabled", module_key)
        messages.success(request, f"{module.name} {'enabled' if control.enabled else 'disabled'}.")
        return redirect(f"{reverse('form_controls')}#{module_key}")
    states = {row.module_key: row.enabled for row in ModuleControl.objects.all()}
    groups = [
        (ROLE_LABELS[role], [(module, states.get(module.key, True)) for module in modules])
        for role, modules in MODULES_BY_ROLE.items()
    ]
    return render(request, "desk/form_controls.html", {"module_groups": groups})


@admin_required
def audit_log(request: HttpRequest) -> HttpResponse:
    page = Paginator(AuditLog.objects.select_related("user", "user__desk_profile"), 100).get_page(request.GET.get("page"))
    return render(request, "desk/audit.html", {"page": page})


@admin_required
@require_GET
def backup(request: HttpRequest) -> HttpResponse:
    return render(request, "desk/backup.html", {"fingerprint": key_fingerprint()})


@admin_required
@require_POST
def backup_download(request: HttpRequest) -> HttpResponse:
    users_data = []
    for user in User.objects.select_related("desk_profile").all():
        users_data.append(
            {
                "username": user.username,
                "password_hash": user.password,
                "active": user.is_active,
                "display_name": user.desk_profile.display_name,
                "role": user.desk_profile.role,
                "must_change_password": user.desk_profile.must_change_password,
            }
        )
    records_data = []
    for record in ActivityRecord.objects.all():
        records_data.append(
            {
                "id": str(record.id),
                "module_key": record.module_key,
                "module_name": record.module_name,
                "role": record.role,
                "owner": record.owner.username,
                "status": record.status,
                "event_date": record.event_date.isoformat() if record.event_date else "",
                "nonce": base64.b64encode(bytes(record.payload_nonce)).decode("ascii"),
                "ciphertext": base64.b64encode(bytes(record.payload_ciphertext)).decode("ascii"),
                "tag": base64.b64encode(bytes(record.payload_tag)).decode("ascii"),
                "created_at": record.created_at.isoformat(),
                "updated_at": record.updated_at.isoformat(),
            }
        )
    payload = {
        "format": "tvs-cloud-backup",
        "version": 1,
        "created_at": timezone.now().isoformat(),
        "key_fingerprint": key_fingerprint(),
        "school_name": SiteSettings.school_name_value(),
        "users": users_data,
        "module_controls": list(ModuleControl.objects.values("module_key", "enabled")),
        "records": records_data,
    }
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    nonce, ciphertext, tag = encrypt_bytes(raw, data_key(), b"tvs-cloud-backup-v1")
    envelope = {
        "format": "tvs-cloud-envelope",
        "version": 1,
        "nonce": base64.b64encode(nonce).decode("ascii"),
        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        "tag": base64.b64encode(tag).decode("ascii"),
    }
    content = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    audit(request.user, "backup_created", f"{len(records_data)} records")
    filename = f"TVS-backup-{timezone.localtime():%Y%m%d-%H%M}.tvsbackup"
    response = HttpResponse(content, content_type="application/octet-stream")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


@require_GET
def health(request: HttpRequest) -> JsonResponse:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
        cursor.fetchone()
    return JsonResponse({"ok": True, "service": "tvs-activity-desk"})
