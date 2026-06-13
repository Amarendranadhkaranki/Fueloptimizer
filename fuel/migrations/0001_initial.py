from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="FuelStation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("opis_id", models.IntegerField(db_index=True)),
                ("name", models.CharField(max_length=255)),
                ("address", models.CharField(blank=True, max_length=255)),
                ("city", models.CharField(db_index=True, max_length=128)),
                ("state", models.CharField(db_index=True, max_length=8)),
                ("rack_id", models.IntegerField(blank=True, null=True)),
                ("retail_price", models.FloatField()),
                ("latitude", models.FloatField(db_index=True)),
                ("longitude", models.FloatField(db_index=True)),
            ],
        ),
        migrations.AddIndex(
            model_name="fuelstation",
            index=models.Index(fields=["latitude", "longitude"], name="fuel_fuelst_latitud_43deee_idx"),
        ),
        migrations.AddIndex(
            model_name="fuelstation",
            index=models.Index(fields=["state", "city"], name="fuel_fuelst_state_1c67d0_idx"),
        ),
    ]