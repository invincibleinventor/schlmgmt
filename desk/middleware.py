import os

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.http import HttpResponseNotFound
from django.shortcuts import redirect
from django.urls import reverse

from .store import get_store


class VercelPreviewGuardMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if os.getenv("VERCEL_ENV") == "preview" and not settings.TVS_ALLOW_VERCEL_PREVIEW:
            return HttpResponseNotFound("Preview deployment disabled for school data safety.")
        return self.get_response(request)


class ActivityDeskAuthenticationMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.user = AnonymousUser()
        user_id = request.session.get("tvs_user_id")
        legacy_user_id = request.session.get("_auth_user_id")
        if user_id or legacy_user_id:
            user = get_store().get_user(user_id or legacy_user_id)
            session_version = request.session.get("tvs_session_version")
            valid_version = legacy_user_id or (
                user and session_version == getattr(user.desk_profile, "session_version", 1)
            )
            if user and user.is_active and valid_version:
                request.user = user
            elif user_id:
                request.session.flush()
        return self.get_response(request)


class ActivityDeskSecurityMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = None
        if request.user.is_authenticated:
            profile = getattr(request.user, "desk_profile", None)
            allowed = {
                reverse("change_password"),
                reverse("logout"),
                reverse("health"),
            }
            if profile and profile.must_change_password and request.path not in allowed:
                response = redirect("change_password")
        if response is None:
            response = self.get_response(request)
        response["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; form-action 'self'; "
            "frame-ancestors 'none'; object-src 'none'; img-src 'self' data:; "
            "font-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'"
        )
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        return response
