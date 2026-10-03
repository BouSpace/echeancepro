from django.db import migrations


def periodes_par_defaut(apps, schema_editor):
    Periode = apps.get_model("echeances", "Periode")
    for libelle, jours in [("7 prochains jours", 7), ("30 prochains jours", 30), ("3 prochains mois", 90)]:
        Periode.objects.get_or_create(jours=jours, defaults={"libelle": libelle, "tableau_de_bord": True})


class Migration(migrations.Migration):

    dependencies = [("echeances", "0006_periode")]

    operations = [migrations.RunPython(periodes_par_defaut, migrations.RunPython.noop)]
