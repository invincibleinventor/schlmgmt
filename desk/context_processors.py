from django.core.exceptions import ImproperlyConfigured
from django.db import OperationalError, ProgrammingError

from tvs_dms.config import APP_NAME, APP_VERSION
from tvs_dms.forms import ROLE_LABELS

from .store import get_store


def workspace(request):
    try:
        school_name = get_store().school_name()
    except (ImproperlyConfigured, OperationalError, ProgrammingError):
        school_name = "School Activity Management"
    profile = getattr(request.user, "desk_profile", None) if request.user.is_authenticated else None
    return {
        "app_name": APP_NAME,
        "app_version": APP_VERSION,
        "school_name": school_name,
        "current_profile": profile,
        "role_labels": ROLE_LABELS,
    }
