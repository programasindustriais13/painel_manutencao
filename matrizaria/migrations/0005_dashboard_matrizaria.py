from django.db import migrations


def provisionar_lideres(apps, schema_editor):
    db = schema_editor.connection.alias
    if db != "default":
        return
    content_type, _ = apps.get_model("contenttypes", "ContentType").objects.using(db).get_or_create(
        app_label="matrizaria", model="solicitacaoservicomatrizaria",
    )
    permission, _ = apps.get_model("auth", "Permission").objects.using(db).get_or_create(
        content_type=content_type, codename="view_dashboard_matrizaria",
        defaults={"name": "Pode visualizar o dashboard gerencial da Matrizaria"},
    )
    for name in ("Liderança de Produção", "Tecnicos_Lideres"):
        group, _ = apps.get_model("auth", "Group").objects.using(db).get_or_create(name=name)
        group.permissions.add(permission)


class Migration(migrations.Migration):
    dependencies = [
        ("matrizaria", "0004_provisionar_grupo_operadores_vulcanizacao"),
        ("auth", "0012_alter_user_first_name_max_length"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="solicitacaoservicomatrizaria",
            options={
                "ordering": ["-data_solicitacao"],
                "verbose_name": "Solicitação de Serviço da Matrizaria",
                "verbose_name_plural": "Solicitações de Serviço da Matrizaria",
                "permissions": [("view_dashboard_matrizaria", "Pode visualizar o dashboard gerencial da Matrizaria")],
            },
        ),
        # Reversão preserva atribuições administrativas; não exclui usuários ou grupos.
        migrations.RunPython(provisionar_lideres, migrations.RunPython.noop),
    ]
