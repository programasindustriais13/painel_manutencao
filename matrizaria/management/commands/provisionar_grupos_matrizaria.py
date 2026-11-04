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

    def add_arguments(self, parser):
        parser.add_argument(
            "--database",
            default="default",
            help="Especifica o banco de dados de destino para o provisionamento (padrão: default).",
        )

    def handle(self, *args, **options):
        db = options.get("database") or "default"
        self.stdout.write(f"Provisionando grupos e permissões da Matrizaria no banco '{db}'...")

        # 1. Grupo Operadores Vulcanização (Chão de Fábrica)
        grupo_vulc, created_vulc = Group.objects.using(db).get_or_create(name="Operadores Vulcanização")
        if created_vulc:
            self.stdout.write(self.style.SUCCESS("Grupo 'Operadores Vulcanização' criado."))
        else:
            self.stdout.write("Grupo 'Operadores Vulcanização' já existente.")

        # 2. Grupo Matrizaria (Oficina Técnica)
        grupo_matz, created_matz = Group.objects.using(db).get_or_create(name="Matrizaria")
        if created_matz:
            self.stdout.write(self.style.SUCCESS("Grupo 'Matrizaria' criado."))
        else:
            self.stdout.write("Grupo 'Matrizaria' já existente.")

        # ContentTypes dos modelos de Matrizaria
        solicitacao_ct = ContentType.objects.db_manager(db).get_for_model(SolicitacaoServicoMatrizaria)
        ciclo_ct = ContentType.objects.db_manager(db).get_for_model(CicloExecucaoMatrizaria)
        matriz_ct = ContentType.objects.db_manager(db).get_for_model(MatrizFisica)
        tipo_ct = ContentType.objects.db_manager(db).get_for_model(TipoServicoMatrizaria)

        # Permissões estritas para Operadores de Vulcanização:
        # Apenas visualização e inclusão de chamados, visualização de ferramentais e tipos
        perms_vulc = list(Permission.objects.using(db).filter(
            content_type=solicitacao_ct,
            codename__in=["view_solicitacaoservicomatrizaria", "add_solicitacaoservicomatrizaria"]
        )) + list(Permission.objects.using(db).filter(
            content_type=matriz_ct,
            codename__in=["view_matrizfisica"]
        )) + list(Permission.objects.using(db).filter(
            content_type=tipo_ct,
            codename__in=["view_tiposervicomatrizaria"]
        ))

        # Higienização e sincronização idempotente via .set()
        grupo_vulc.permissions.set(perms_vulc)

        # Permissões operacionais da equipe da Matrizaria
        perms_matz = list(Permission.objects.using(db).filter(
            content_type=solicitacao_ct,
            codename__in=["view_solicitacaoservicomatrizaria", "change_solicitacaoservicomatrizaria"]
        )) + list(Permission.objects.using(db).filter(
            content_type=ciclo_ct,
            codename__in=["view_cicloexecucaomatrizaria", "add_cicloexecucaomatrizaria", "change_cicloexecucaomatrizaria"]
        )) + list(Permission.objects.using(db).filter(
            content_type=matriz_ct,
            codename__in=["view_matrizfisica"]
        )) + list(Permission.objects.using(db).filter(
            content_type=tipo_ct,
            codename__in=["view_tiposervicomatrizaria"]
        ))

        grupo_matz.permissions.set(perms_matz)

        self.stdout.write(self.style.SUCCESS(f"Grupos e permissões provisionados com sucesso no banco '{db}'."))
