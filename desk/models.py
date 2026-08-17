from __future__ import annotations

import uuid

from django.contrib.auth.models import User
from django.db import models

from tvs_dms.forms import ROLE_LABELS

from .crypto import decrypt_payload, encrypt_payload

ROLE_CHOICES = tuple(ROLE_LABELS.items())


class SiteSettings(models.Model):
    school_name = models.CharField(max_length=180)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "site settings"

    @classmethod
    def school_name_value(cls) -> str:
        row = cls.objects.order_by("pk").first()
        return row.school_name if row else "School Activity Management"


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="desk_profile")
    display_name = models.CharField(max_length=160)
    role = models.CharField(max_length=32, choices=ROLE_CHOICES)
    must_change_password = models.BooleanField(default=True)
    failed_attempts = models.PositiveSmallIntegerField(default=0)
    locked_until = models.DateTimeField(null=True, blank=True)
    session_version = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.display_name


class ModuleControl(models.Model):
    module_key = models.CharField(max_length=80, unique=True)
    enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.module_key


class ActivityRecord(models.Model):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    STATUS_CHOICES = ((DRAFT, "Draft"), (SUBMITTED, "Submitted"))

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    module_key = models.CharField(max_length=80, db_index=True)
    module_name = models.CharField(max_length=160)
    role = models.CharField(max_length=32, choices=ROLE_CHOICES)
    owner = models.ForeignKey(User, on_delete=models.PROTECT, related_name="activity_records")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, db_index=True)
    event_date = models.DateField(null=True, blank=True, db_index=True)
    payload_nonce = models.BinaryField()
    payload_ciphertext = models.BinaryField()
    payload_tag = models.BinaryField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-updated_at",)
        indexes = [models.Index(fields=("module_key", "status"))]

    def set_data(self, value: dict) -> None:
        nonce, ciphertext, tag = encrypt_payload(value, str(self.id))
        self.payload_nonce = nonce
        self.payload_ciphertext = ciphertext
        self.payload_tag = tag

    def get_data(self) -> dict:
        return decrypt_payload(
            bytes(self.payload_nonce),
            bytes(self.payload_ciphertext),
            bytes(self.payload_tag),
            str(self.id),
        )

    def __str__(self) -> str:
        return f"{self.module_name} · {self.owner.username}"


class AuditLog(models.Model):
    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL)
    action = models.CharField(max_length=80)
    target = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-id",)

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.action}"
