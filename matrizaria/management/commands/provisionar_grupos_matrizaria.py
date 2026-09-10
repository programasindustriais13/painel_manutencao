from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from matrizaria.models import (
    TipoServicoMatrizaria,
    MatrizFisica,
    SolicitacaoServicoMatrizaria,
    CicloExecucaoMatrizaria,
    HistoricoTransicaoServicoMatrizaria,
)


class Command(BaseCommand):
    help = "Provisiona de forma idempotente os grupos de usuários do módulo de Matrizaria (Operadores Vulcanização e Matrizaria)."

    def handle(self, *args, **options):
        self.stdout.write("Provisionando grupos e permissões da Matrizaria...")

        # 1. Grupo Operadores Vulcanização
        grupo_vulc, created_vulc = Group.objects.get_or_create(name="Operadores Vulcanização")
        if created_vulc:
            self.stdout.write(self.style.SUCCESS("Grupo 'Operadores Vulcanização' criado."))
        else:
            self.stdout.write("Grupo 'Operadores Vulcanização' já existente.")

        # 2. Grupo Matrizaria
        grupo_matz, created_matz = Group.objects.get_or_create(name="Matrizaria")
        if created_matz:
            self.stdout.write(self.style.SUCCESS("Grupo 'Matrizaria' criado."))
        else:
            self.stdout.write("Grupo 'Matrizaria' já existente.")

        # Permissões do ContentType da Matrizaria
        solicitacao_ct = ContentType.objects.get_for_model(SolicitacaoServicoMatrizaria)
        ciclo_ct = ContentType.objects.get_for_model(CicloExecucaoMatrizaria)
        matriz_ct = ContentType.objects.get_for_model(MatrizFisica)
        tipo_ct = ContentType.objects.get_for_model(TipoServicoMatrizaria)
        historico_ct = ContentType.objects.get_for_model(HistoricoTransicaoServicoMatrizaria)

        # Atribuições ao grupo Operadores Vulcanização: pode visualizar e adicionar solicitações
        perms_vulc = Permission.objects.filter(
            content_type=solicitacao_ct,
            codename__in=["view_solicitacaoservicomatrizaria", "add_solicitacaoservicomatrizaria"]
        ) | Permission.objects.filter(
            content_type=matriz_ct,
            codename__in=["view_matrizfisica"]
        ) | Permission.objects.filter(
            content_type=tipo_ct,
            codename__in=["view_tiposervicomatrizaria"]
        )
        grupo_vulc.permissions.add(*perms_vulc)

        # Atribuições ao grupo Matrizaria: pode visualizar, alterar solicitações e ciclos
        perms_matz = Permission.objects.filter(
            content_type=solicitacao_ct,
            codename__in=["view_solicitacaoservicomatrizaria", "change_solicitacaoservicomatrizaria"]
        ) | Permission.objects.filter(
            content_type=ciclo_ct,
            codename__in=["view_cicloexecucaomatrizaria", "add_cicloexecucaomatrizaria", "change_cicloexecucaomatrizaria"]
        ) | Permission.objects.filter(
            content_type=matriz_ct,
            codename__in=["view_matrizfisica"]
        ) | Permission.objects.filter(
            content_type=tipo_ct,
            codename__in=["view_tiposervicomatrizaria"]
        )
        grupo_matz.permissions.add(*perms_matz)

        self.stdout.write(self.style.SUCCESS("Grupos e permissões provisionados com sucesso."))
