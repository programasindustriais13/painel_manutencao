from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from bladder import models as bladder_models


class Command(BaseCommand):
    help = "Cria ou atualiza os grupos de permissão 'Liderança Bladder' e 'Operadores Bladder' com as permissões corretas."

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Configurando grupos e permissões do Setor de Bladder..."))

        # 1. Grupo Liderança Bladder
        grupo_lider, created_l = Group.objects.get_or_create(name="Liderança Bladder")
        # 2. Grupo Operadores Bladder
        grupo_op, created_o = Group.objects.get_or_create(name="Operadores Bladder")

        # Obter permissões do app bladder
        content_types = ContentType.objects.filter(app_label="bladder")
        todas_perms_bladder = Permission.objects.filter(content_type__in=content_types)

        # Liderança recebe todas as permissões do módulo
        grupo_lider.permissions.set(todas_perms_bladder)

        # Operadores recebem apenas visualização de OPs e registro de apontamentos
        perms_operador_codenames = [
            "view_ordemproducaobladder",
            "view_processobladder",
            "view_produtobladder",
            "view_recursobladder",
            "add_apontamentoturnobladder",
            "change_apontamentoturnobladder",
            "view_apontamentoturnobladder",
        ]
        perms_op = Permission.objects.filter(
            content_type__in=content_types,
            codename__in=perms_operador_codenames
        )
        grupo_op.permissions.set(perms_op)

        self.stdout.write(self.style.SUCCESS(
            f"Grupos configurados com sucesso!\n"
            f" - 'Liderança Bladder': {grupo_lider.permissions.count()} permissões.\n"
            f" - 'Operadores Bladder': {grupo_op.permissions.count()} permissões."
        ))
