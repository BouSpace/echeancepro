from django.db import migrations, models


def vides_en_null(apps, schema_editor):
    apps.get_model("echeances", "Banque").objects.filter(numero_compte="").update(numero_compte=None)


class Migration(migrations.Migration):

    dependencies = [("echeances", "0002_banque_numero_compte")]

    operations = [
        migrations.AlterField(
            model_name="banque", name="numero_compte",
            field=models.CharField(blank=True, max_length=50, null=True, verbose_name="numéro de compte"),
        ),
        migrations.RunPython(vides_en_null, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="banque", name="numero_compte",
            field=models.CharField(blank=True, max_length=50, null=True, unique=True, verbose_name="numéro de compte"),
        ),
    ]
