from django.shortcuts import redirect
from django.urls import reverse


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
