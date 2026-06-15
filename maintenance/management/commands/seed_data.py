from django.core.management.base import BaseCommand
from django.contrib.auth.models import User, Group
from django.utils import timezone
from datetime import timedelta
import random

from maintenance.models import Sector, Machine, Technician, Allocation

class Command(BaseCommand):
    help = "Cria grupos, usuários e popula o banco de dados com dados de teste realistas."

    def handle(self, *args, **options):
        self.stdout.write("Iniciando a semeadura de dados de teste...")

        # 1. Criar Grupos
        operador_group, _ = Group.objects.get_or_create(name='Operador')
        visualizador_group, _ = Group.objects.get_or_create(name='Visualizador')
        self.stdout.write("Grupos 'Operador' e 'Visualizador' configurados.")

        # 2. Criar Usuário Administrador (Superuser)
        if not User.objects.filter(username='admin').exists():
            admin_user = User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
            # Add admin to operator group too
            admin_user.groups.add(operador_group)
            self.stdout.write("Usuário Admin criado: Login 'admin', Senha 'admin123'")
        else:
            self.stdout.write("Usuário Admin já existe.")

        # 3. Criar Usuário Operador Padrão
        if not User.objects.filter(username='operador').exists():
            operador_user = User.objects.create_user('operador', 'operador@example.com', 'operador123', is_staff=True)
            operador_user.groups.add(operador_group)
            self.stdout.write("Usuário Operador criado: Login 'operador', Senha 'operador123'")

        # 4. Criar Usuário Visualizador Padrão
        if not User.objects.filter(username='tv').exists():
            tv_user = User.objects.create_user('tv', 'tv@example.com', 'tv123')
            tv_user.groups.add(visualizador_group)
            self.stdout.write("Usuário Visualizador (TV) criado: Login 'tv', Senha 'tv123'")

        # Limpar tabelas existentes para evitar duplicatas nos dados de teste
        Allocation.objects.all().delete()
        Technician.objects.all().delete()
        Machine.objects.all().delete()
        Sector.objects.all().delete()

        # 5. Criar Setores
        setores_nomes = ["Usinagem", "Montagem Mecânica", "Pintura", "Estamparia", "Logística"]
        setores = []
        for nome in setores_nomes:
            s = Sector.objects.create(nome=nome)
            setores.append(s)
        self.stdout.write(f"{len(setores)} setores cadastrados.")

        # 6. Criar Máquinas
        maquinas_dados = [
            ("Prensa Hidráulica 01", "Estamparia", "ALTA"),
            ("Prensa Hidráulica 02", "Estamparia", "ALTA"),
            ("Torno CNC 02", "Usinagem", "MEDIA"),
            ("Centro de Usinagem 05", "Usinagem", "ALTA"),
            ("Esteira Industrial A", "Montagem Mecânica", "BAIXA"),
            ("Linha de Montagem B", "Montagem Mecânica", "MEDIA"),
            ("Cabine de Pintura Eletrostática", "Pintura", "ALTA"),
            ("Robô de Solda 04", "Montagem Mecânica", "ALTA"),
            ("Ponte Rolante 02", "Logística", "ALTA"),
            ("Empilhadeira Elétrica 03", "Logística", "BAIXA"),
        ]
        
        maquinas = {}
        for nome_maq, nome_setor, crit in maquinas_dados:
            setor_obj = next(s for s in setores if s.nome == nome_setor)
            m = Machine.objects.create(nome=nome_maq, setor=setor_obj, criticidade=crit)
            maquinas[nome_maq] = m
        self.stdout.write(f"{len(maquinas)} máquinas cadastradas.")

        # 7. Criar Técnicos
        tecnicos_dados = [
            ("Carlos Souza", "TEC-001"),
            ("Felipe Neto", "TEC-002"),
            ("Juliana Dias", "TEC-003"),
            ("Marcos Santos", "TEC-004"),
            ("Roberto Lima", "TEC-005"),
            ("Amanda Costa", "TEC-006"),
            ("Lucas Mendes", "TEC-007"),
            ("Bruno Alves", "TEC-008"),
        ]

        tecnicos = {}
        for nome, mat in tecnicos_dados:
            t = Technician.objects.create(nome=nome, matricula=mat, status='OCIOSO')
            tecnicos[nome] = t
        self.stdout.write(f"{len(tecnicos)} técnicos cadastrados.")

        # 8. Criar Alocações Ativas (Para popular telas de TV e Dashboard)
        now = timezone.now()

        # Felipe Neto em Atendimento
        t_felipe = tecnicos["Felipe Neto"]
        t_felipe.status = 'EM_ATENDIMENTO'
        t_felipe.save()
        Allocation.objects.create(
            tecnico=t_felipe,
            maquina=maquinas["Torno CNC 02"],
            atividade_observacao="Ajuste na ferramenta de corte e calibração de eixos do carro principal.",
            data_inicio=now - timedelta(minutes=28),
        )

        # Juliana Dias Em Pausa
        t_juliana = tecnicos["Juliana Dias"]
        t_juliana.status = 'EM_PAUSA'
        t_juliana.save()
        Allocation.objects.create(
            tecnico=t_juliana,
            maquina=maquinas["Prensa Hidráulica 01"],
            atividade_observacao="Vazamento de óleo no retentor do pistão principal de prensagem.",
            data_inicio=now - timedelta(hours=1, minutes=45),
            data_pausa=now - timedelta(minutes=15),
            motivo_pausa="Aguardando a chegada da junta de vedação retentora sobressalente solicitada ao estoque central."
        )

        # Roberto Lima em Atendimento
        t_roberto = tecnicos["Roberto Lima"]
        t_roberto.status = 'EM_ATENDIMENTO'
        t_roberto.save()
        Allocation.objects.create(
            tecnico=t_roberto,
            maquina=maquinas["Cabine de Pintura Eletrostática"],
            atividade_observacao="Desobstrução e limpeza química dos bicos pulverizadores de tinta eletrostática.",
            data_inicio=now - timedelta(minutes=55),
        )

        # Lucas Mendes em Atendimento
        t_lucas = tecnicos["Lucas Mendes"]
        t_lucas.status = 'EM_ATENDIMENTO'
        t_lucas.save()
        Allocation.objects.create(
            tecnico=t_lucas,
            maquina=maquinas["Robô de Solda 04"],
            atividade_observacao="Substituição preventiva do servo-motor de acionamento da junta nº 3 da garra de soldagem.",
            data_inicio=now - timedelta(hours=2, minutes=10),
        )

        # Amanda Costa em Pausa
        t_amanda = tecnicos["Amanda Costa"]
        t_amanda.status = 'EM_PAUSA'
        t_amanda.save()
        Allocation.objects.create(
            tecnico=t_amanda,
            maquina=maquinas["Ponte Rolante 02"],
            atividade_observacao="Substituição da botoeira de controle e verificação elétrica dos contatores de carga.",
            data_inicio=now - timedelta(hours=3),
            data_pausa=now - timedelta(minutes=45),
            motivo_pausa="Parada obrigatória do operador para almoço regulamentar."
        )

        # Criar algumas alocações antigas já CONCLUÍDAS para fins de histórico e gráficos
        for i in range(15):
            t_rand = random.choice(list(tecnicos.values()))
            m_rand = random.choice(list(maquinas.values()))
            
            d_ini = now - timedelta(days=random.randint(1, 10), hours=random.randint(1, 23))
            d_fim = d_ini + timedelta(minutes=random.randint(15, 180))
            
            Allocation.objects.create(
                tecnico=t_rand,
                maquina=m_rand,
                atividade_observacao=f"Manutenção corretiva/preventiva geral executada no equipamento. Ordem gerada em simulação {i}.",
                data_inicio=d_ini,
                data_fim=d_fim,
                observacao_conclusao="Substituição de peças desgastadas e testes funcionais operando 100%.",
            )

        self.stdout.write("Dados de teste populados com sucesso!")
        self.stdout.write("Pronto para testar o painel e os dashboards!")
