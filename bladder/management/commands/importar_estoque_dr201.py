from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from bladder.models import ProdutoBladder, MovimentacaoEstoqueBladder
from bladder.services import auditar_planilha_dr201


class Command(BaseCommand):
    help = "Audita e permite importar estoques de referência da planilha DR-201 para o Django."

    def add_arguments(self, parser):
        parser.add_argument(
            '--audit-only',
            action='store_true',
            help='Apenas executa a auditoria e imprime o relatório de reconciliação sem alterar nada.',
        )
        parser.add_argument(
            '--aplicar-saldos-positivos',
            action='store_true',
            help='Aplica os saldos calculados positivos como carga inicial no Django (bloqueia negativos).',
        )

    def handle(self, *args, **options):
        audit_only = options.get('audit_only', False)
        aplicar = options.get('aplicar_saldos_positivos', False)

        self.stdout.write(self.style.NOTICE("Iniciando auditoria da planilha DR-201 (Google Sheets)..."))
        resultado = auditar_planilha_dr201()

        if not resultado.get('sucesso'):
            self.stdout.write(self.style.ERROR(f"Falha na auditoria: {resultado.get('erro')}"))
            return

        self.stdout.write(self.style.SUCCESS(f"Linhas totais: {resultado['total_linhas']} | Válidas: {resultado['linhas_validas']}"))
        self.stdout.write(f"Total Entradas: {resultado['total_entradas']} | Total Saídas: {resultado['total_saidas']}")
        self.stdout.write(f"Saldo Geral Bruto: {resultado['saldo_geral_calculado']} un")
        self.stdout.write("\n" + "="*80)
        self.stdout.write(f"{'CÓDIGO':<10} | {'DESCRIÇÃO':<30} | {'ENTRADAS':<9} | {'SAÍDAS':<7} | {'SALDO DR-201':<12} | {'SITUAÇÃO'}")
        self.stdout.write("="*80)

        for row in resultado['tabela_reconciliacao']:
            saldo_str = f"{row['saldo_calculado']:>4} un"
            if row['saldo_calculado'] < 0:
                saldo_str = self.style.ERROR(saldo_str)
            else:
                saldo_str = self.style.SUCCESS(saldo_str)

            self.stdout.write(
                f"{row['codigo']:<10} | {row['produto_nome'][:30]:<30} | {row['entradas']:>9} | {row['saidas']:>7} | {saldo_str:<21} | {row['situacao']}"
            )

        self.stdout.write("="*80)
        self.stdout.write(self.style.WARNING(resultado['alerta_consistencia']))

        if not aplicar:
            self.stdout.write(self.style.NOTICE("\nModo auditoria. Para aplicar saldos confirmados no banco local use --aplicar-saldos-positivos."))
            return

        # Aplicação dos saldos positivos confirmados
        usuario = User.objects.filter(is_superuser=True).first()
        if not usuario:
            usuario = User.objects.first()

        self.stdout.write(self.style.NOTICE(f"\nAplicando carga inicial de estoque no Django com usuário '{usuario.username}'..."))
        hoje = timezone.localdate()
        com_sucesso = 0

        with transaction.atomic(using='default'):
            for row in resultado['tabela_reconciliacao']:
                saldo = row['saldo_calculado']
                if saldo <= 0:
                    self.stdout.write(self.style.WARNING(f"Pulando {row['codigo']}: saldo {saldo} <= 0 (aguarda validação manual de inventário)."))
                    continue

                prod = ProdutoBladder.objects.get(codigo=row['codigo'])
                if prod.estoque_atual > 0:
                    self.stdout.write(self.style.NOTICE(f"Produto {prod.codigo} já possui estoque {prod.estoque_atual} un. Carga não duplicada."))
                    continue

                saldo_ant = prod.estoque_atual
                prod.estoque_atual = saldo
                prod.save(update_fields=['estoque_atual', 'updated_at'])

                MovimentacaoEstoqueBladder.objects.create(
                    produto=prod,
                    tipo='CARGA_INICIAL',
                    quantidade=saldo,
                    saldo_anterior=saldo_ant,
                    saldo_posterior=saldo,
                    usuario=usuario,
                    turma='LIDERANCA',
                    data_turno=hoje,
                    destino="Estoque Central Bladder",
                    justificativa=f"Carga inicial auditada da planilha DR-201 ({row['entradas']} entradas - {row['saidas']} saídas no histórico)",
                    idempotency_key=f"CARGA_INICIAL_DR201_{prod.codigo}",
                )
                com_sucesso += 1
                self.stdout.write(self.style.SUCCESS(f"Produto {prod.codigo}: estoque inicial definido para {saldo} un."))

        self.stdout.write(self.style.SUCCESS(f"\nCarga inicial concluída: {com_sucesso} produtos inicializados com sucesso no Django."))

