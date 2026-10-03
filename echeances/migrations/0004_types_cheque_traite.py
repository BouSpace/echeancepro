from django.db import migrations, models

TYPES = [("CHEQUE", "Chèque"), ("TRAITE", "Traite")]


def vers_traite(apps, schema_editor):
    for nom in ("Echeance", "HistoricalEcheance"):
        apps.get_model("echeances", nom).objects.filter(
            type__in=["TRAITE_AVALISEE", "TRAITE_SIMPLE", "REGLEMENT"]
        ).update(type="TRAITE")


class Migration(migrations.Migration):

    dependencies = [("echeances", "0003_banque_numero_compte_unique")]

    operations = [
        migrations.RunPython(vers_traite, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="echeance", name="type",
            field=models.CharField(choices=TYPES, max_length=20, verbose_name="type"),
        ),
        migrations.AlterField(
            model_name="historicalecheance", name="type",
            field=models.CharField(choices=TYPES, max_length=20, verbose_name="type"),
        ),
        migrations.AlterField(
            model_name="echeance", name="cout_aval",
            field=models.DecimalField(decimal_places=0, default=0, help_text="Uniquement pour les traites (aval, frais bancaires).", max_digits=15, verbose_name="coût d'aval et frais (F CFA)"),
        ),
        migrations.AlterField(
            model_name="historicalecheance", name="cout_aval",
            field=models.DecimalField(decimal_places=0, default=0, help_text="Uniquement pour les traites (aval, frais bancaires).", max_digits=15, verbose_name="coût d'aval et frais (F CFA)"),
        ),
    ]
