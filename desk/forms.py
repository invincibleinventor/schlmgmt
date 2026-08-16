from __future__ import annotations

import hmac
from datetime import date, datetime
from typing import Any

from django import forms
from django.conf import settings
from django.contrib.auth import password_validation
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError

from tvs_dms.forms import ROLE_LABELS, Field, Module


def validate_strong_password(password: str, user: User | None = None) -> str:
    password_validation.validate_password(password, user=user)
    if not any(char.isupper() for char in password):
        raise ValidationError("Include at least one uppercase letter.")
    if not any(char.islower() for char in password):
        raise ValidationError("Include at least one lowercase letter.")
    if not any(char.isdigit() for char in password):
        raise ValidationError("Include at least one number.")
    return password


class SetupForm(forms.Form):
    school_name = forms.CharField(max_length=180, label="School name")
    display_name = forms.CharField(max_length=160, label="Administrator name")
    username = forms.CharField(max_length=150, initial="admin")
    password = forms.CharField(widget=forms.PasswordInput, label="Master password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm master password")
    setup_token = forms.CharField(widget=forms.PasswordInput, label="Deployment setup token")

    def clean_username(self) -> str:
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("That username already exists.")
        return username

    def clean_password(self) -> str:
        return validate_strong_password(self.cleaned_data["password"])

    def clean_setup_token(self) -> str:
        token = self.cleaned_data["setup_token"]
        if not hmac.compare_digest(token, settings.TVS_SETUP_TOKEN):
            raise ValidationError("The deployment setup token is incorrect.")
        return token

    def clean(self) -> dict[str, Any]:
        values = super().clean()
        if values.get("password") and values.get("confirm_password") != values["password"]:
            self.add_error("confirm_password", "Passwords do not match.")
        return values


class LoginForm(forms.Form):
    username = forms.CharField(max_length=150, widget=forms.TextInput(attrs={"autofocus": True, "autocomplete": "username"}))
    password = forms.CharField(widget=forms.PasswordInput(attrs={"autocomplete": "current-password"}))


class UserCreateForm(forms.Form):
    username = forms.CharField(max_length=150)
    display_name = forms.CharField(max_length=160, label="Display name")
    role = forms.ChoiceField(choices=tuple((key, label) for key, label in ROLE_LABELS.items() if key != "administrator"))
    password = forms.CharField(widget=forms.PasswordInput, label="Temporary password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm password")

    def clean_username(self) -> str:
        username = self.cleaned_data["username"].strip()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError("That username already exists.")
        return username

    def clean_password(self) -> str:
        return validate_strong_password(self.cleaned_data["password"])

    def clean(self) -> dict[str, Any]:
        values = super().clean()
        if values.get("password") and values.get("confirm_password") != values["password"]:
            self.add_error("confirm_password", "Passwords do not match.")
        return values


class PasswordResetForm(forms.Form):
    password = forms.CharField(widget=forms.PasswordInput, label="New password")
    confirm_password = forms.CharField(widget=forms.PasswordInput, label="Confirm new password")

    def __init__(self, *args: Any, user: User, **kwargs: Any) -> None:
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_password(self) -> str:
        return validate_strong_password(self.cleaned_data["password"], self.user)

    def clean(self) -> dict[str, Any]:
        values = super().clean()
        if values.get("password") and values.get("confirm_password") != values["password"]:
            self.add_error("confirm_password", "Passwords do not match.")
        return values


class StrongPasswordChangeForm(PasswordChangeForm):
    def clean_new_password1(self) -> str:
        return validate_strong_password(self.cleaned_data["new_password1"], self.user)


def _web_field(definition: Field, *, submitted: bool) -> forms.Field:
    required = definition.required and submitted
    attrs: dict[str, Any] = {"placeholder": definition.hint} if definition.hint else {}
    if definition.kind == "longtext":
        return forms.CharField(label=definition.label, required=required, widget=forms.Textarea(attrs={**attrs, "rows": 4}))
    if definition.kind == "integer":
        return forms.IntegerField(label=definition.label, required=required, min_value=0, widget=forms.NumberInput(attrs=attrs))
    if definition.kind == "date":
        return forms.DateField(
            label=definition.label,
            required=required,
            input_formats=("%Y-%m-%d", "%d-%m-%Y"),
            widget=forms.DateInput(format="%Y-%m-%d", attrs={**attrs, "type": "date"}),
        )
    if definition.kind == "choice":
        choices = (("", "Select…"),) + tuple((choice, choice) for choice in definition.choices)
        return forms.ChoiceField(label=definition.label, required=required, choices=choices)
    return forms.CharField(label=definition.label, required=required, widget=forms.TextInput(attrs=attrs))


class ActivityEntryForm(forms.Form):
    def __init__(
        self,
        *args: Any,
        module: Module,
        submitted: bool,
        initial: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        self.module = module
        self.submitted = submitted
        normalized = dict(initial or {})
        for definition in module.fields:
            if definition.kind == "date" and normalized.get(definition.key):
                value = normalized[definition.key]
                if isinstance(value, str):
                    for pattern in ("%d-%m-%Y", "%Y-%m-%d"):
                        try:
                            normalized[definition.key] = datetime.strptime(value, pattern).date()
                            break
                        except ValueError:
                            continue
        super().__init__(*args, initial=normalized, **kwargs)
        for definition in module.fields:
            self.fields[definition.key] = _web_field(definition, submitted=submitted)
            if definition.required:
                self.fields[definition.key].help_text = "Required when submitting"

    def payload(self) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for definition in self.module.fields:
            value = self.cleaned_data.get(definition.key)
            if isinstance(value, date):
                value = value.strftime("%d-%m-%Y")
            if value not in (None, ""):
                result[definition.key] = value
        return result
