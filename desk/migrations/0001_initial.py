import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = [("auth", "0012_alter_user_first_name_max_length")]

    operations = [
        migrations.CreateModel(
            name="ModuleControl",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("module_key", models.CharField(max_length=80, unique=True)),
                ("enabled", models.BooleanField(default=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="SiteSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("school_name", models.CharField(max_length=180)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={"verbose_name_plural": "site settings"},
        ),
        migrations.CreateModel(
            name="Profile",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("display_name", models.CharField(max_length=160)),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("administrator", "Administrator"),
                            ("class_teacher", "Class Teacher"),
                            ("catalyst_member", "Catalyst Member"),
                            ("office", "Office"),
                            ("academic_supervisor", "Academic Supervisor"),
                        ],
                        max_length=32,
                    ),
                ),
                ("must_change_password", models.BooleanField(default=True)),
                ("failed_attempts", models.PositiveSmallIntegerField(default=0)),
                ("locked_until", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("user", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="desk_profile", to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name="AuditLog",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("action", models.CharField(max_length=80)),
                ("target", models.CharField(blank=True, max_length=255)),
                ("created_at", models.DateTimeField(auto_now_add=True, db_index=True)),
                ("user", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ("-id",)},
        ),
        migrations.CreateModel(
            name="ActivityRecord",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("module_key", models.CharField(db_index=True, max_length=80)),
                ("module_name", models.CharField(max_length=160)),
                (
                    "role",
                    models.CharField(
                        choices=[
                            ("administrator", "Administrator"),
                            ("class_teacher", "Class Teacher"),
                            ("catalyst_member", "Catalyst Member"),
                            ("office", "Office"),
                            ("academic_supervisor", "Academic Supervisor"),
                        ],
                        max_length=32,
                    ),
                ),
                ("status", models.CharField(choices=[("draft", "Draft"), ("submitted", "Submitted")], db_index=True, max_length=12)),
                ("event_date", models.DateField(blank=True, db_index=True, null=True)),
                ("payload_nonce", models.BinaryField()),
                ("payload_ciphertext", models.BinaryField()),
                ("payload_tag", models.BinaryField()),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("owner", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="activity_records", to=settings.AUTH_USER_MODEL)),
            ],
            options={
                "ordering": ("-updated_at",),
                "indexes": [models.Index(fields=["module_key", "status"], name="desk_activi_module__6b4011_idx")],
            },
        ),
    ]
