from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("desk", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="session_version",
            field=models.PositiveIntegerField(default=1),
        )
    ]
