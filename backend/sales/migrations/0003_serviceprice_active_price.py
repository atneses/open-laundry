from django.db import migrations, models


class Migration(migrations.Migration):
    """Prices are no longer dated: the last one added is the active one."""

    dependencies = [
        ("core", "0003_create_roles"),
        ("sales", "0002_grant_role_permissions"),
    ]

    operations = [
        # No prices were stored yet, so removing the column and adding the new ones is safe.
        migrations.RemoveConstraint(
            model_name="serviceprice",
            name="unique_service_price_per_day",
        ),
        migrations.RemoveField(
            model_name="serviceprice",
            name="valid_from",
        ),
        migrations.AlterModelOptions(
            name="serviceprice",
            options={
                "ordering": ["service", "mode", "-created_at"],
                "verbose_name": "service price",
                "verbose_name_plural": "service prices",
            },
        ),
        migrations.AddField(
            model_name="serviceprice",
            name="is_active",
            field=models.BooleanField(default=True, verbose_name="active"),
        ),
        migrations.AddField(
            model_name="serviceprice",
            name="created_at",
            field=models.DateTimeField(auto_now_add=True, verbose_name="date"),
            preserve_default=False,
        ),
        migrations.AddConstraint(
            model_name="serviceprice",
            constraint=models.UniqueConstraint(
                condition=models.Q(("is_active", True)),
                fields=("service", "mode", "program", "branch"),
                name="one_active_price_per_service_mode",
            ),
        ),
    ]
