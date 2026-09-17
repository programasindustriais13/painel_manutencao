from typing import Optional, List, Dict, Any
from datetime import datetime, time, date, timedelta
from django.db import transaction
from django.db.models import F, Q
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from maintenance.models import Machine, Allocation
from production.models import ProductionMatrixCatalog
from .models import (
    TipoServicoMatrizaria,
    MatrizFisica,
    SolicitacaoServicoMatrizaria,
    CicloExecucaoMatrizaria,
    HistoricoTransicaoServicoMatrizaria,
    is_checklist_machine,
)


class MatrizariaService:
    """
    Camada central de serviços de negócio e orquestração do módulo de Matrizaria Industrial.
    Todas as transições de estado, concorrência e auditoria passam exclusivamente por aqui.
    """

    @staticmethod
    def get_user_display_name(user) -> str:
        if not user:
            return "Sistema"
        full = user.get_full_name()
        return full.strip() if full and full.strip() else user.username

    @classmethod
    @transaction.atomic
    def criar_solicitacao(
        cls,
        prensa: Optional[Machine],
        tipo_servico: TipoServicoMatrizaria,
        descricao_solicitacao: str,
        solicitado_por,
        prioridade: str = "NORMAL",
        matriz_fisica: Optional[MatrizFisica] = None,
        destino: str = "MAQUINA",
    ) -> SolicitacaoServicoMatrizaria:
        """
        Abre uma nova solicitação de serviço da Matrizaria com validação e snapshots imediatos.
        """
        if destino == "MATRIZARIA":
            prensa = None
            prensa_nome = "Matrizaria"
        elif destino == "MAQUINA":
            if not prensa:
                raise ValidationError("A prensa é obrigatória.")
            if is_checklist_machine(prensa):
                raise ValidationError("Máquinas de apoio ou CHECK-LIST não são válidas para chamados de Matrizaria.")
            prensa_nome = prensa.nome
        else:
            raise ValidationError("Destino inválido.")

        if not tipo_servico:
            raise ValidationError("O tipo de serviço é obrigatório.")
        if not descricao_solicitacao or not descricao_solicitacao.strip():
            raise ValidationError("A descrição da solicitação é obrigatória.")
        if not solicitado_por or not solicitado_por.is_authenticated:
            raise ValidationError("Usuário solicitante inválido.")

        solicitante_nome = cls.get_user_display_name(solicitado_por)
        tipo_servico_nome = tipo_servico.nome
        exige_matriz = tipo_servico.exige_matriz_fisica

        matriz_snapshot = None
        if matriz_fisica:
            matriz_snapshot = matriz_fisica.nome_exibicao

        solicitacao = SolicitacaoServicoMatrizaria.objects.create(
            destino=destino,
            prensa=prensa,
            prensa_nome_snapshot=prensa_nome,
            matriz_fisica=matriz_fisica,
            matriz_identificador_snapshot=matriz_snapshot,
            tipo_servico=tipo_servico,
            tipo_servico_nome_snapshot=tipo_servico_nome,
            exige_matriz_fisica_snapshot=exige_matriz,
            descricao_solicitacao=descricao_solicitacao.strip(),
            prioridade=prioridade,
            status="SOLICITADO",
            solicitado_por=solicitado_por,
            solicitado_por_nome=solicitante_nome,
            data_solicitacao=timezone.now(),
            versao=1,
        )

        HistoricoTransicaoServicoMatrizaria.objects.create(
            solicitacao=solicitacao,
            status_anterior="INEXISTENTE",
            status_novo="SOLICITADO",
            tipo_evento="CRIACAO",
            usuario=solicitado_por,
            usuario_nome_snapshot=solicitante_nome,
            data_evento=timezone.now(),
            observacao="Abertura da solicitação no sistema.",
            dados_modificados=f"Destino/Prensa: {prensa_nome} | Tipo: {tipo_servico_nome} | Prioridade: {prioridade}",
        )

        return solicitacao

    @classmethod
    @transaction.atomic
    def iniciar_atendimento(
        cls,
        solicitacao_id: int,
        usuario,
        versao_esperada: int,
    ) -> SolicitacaoServicoMatrizaria:
        """
        Assume o chamado (início ou retomada de retrabalho), abrindo um Ciclo individual.
        """
        solicitacao = SolicitacaoServicoMatrizaria.objects.filter(pk=solicitacao_id).first()
        if not solicitacao:
            raise ValidationError("Solicitação não encontrada.")

        if solicitacao.versao != versao_esperada:
            raise ValidationError("Conflito de concorrência: a solicitação foi modificada por outro usuário. Atualize a página e tente novamente.")

        status_permitidos = ["SOLICITADO", "AGUARDANDO_RETRABALHO"]
        if solicitacao.status not in status_permitidos:
            raise ValidationError(f"Não é possível iniciar atendimento a partir do status '{solicitacao.get_status_display()}'.")

        now = timezone.now()
        executor_nome = cls.get_user_display_name(usuario)
        status_anterior = solicitacao.status

        # Verificação de concorrência otimista
        rows_updated = SolicitacaoServicoMatrizaria.objects.filter(
            pk=solicitacao_id,
            status=status_anterior,
            versao=versao_esperada,
        ).update(
            status="EM_EXECUCAO",
            responsavel_atribuido=usuario,
            responsavel_atribuido_nome=executor_nome,
            data_inicio_execucao=now if not solicitacao.data_inicio_execucao else solicitacao.data_inicio_execucao,
            iniciado_por=usuario if not solicitacao.iniciado_por else solicitacao.iniciado_por,
            versao=F("versao") + 1,
        )

        if rows_updated == 0:
            raise ValidationError("Conflito de concorrência: a solicitação foi modificada por outro usuário. Atualize a página e tente novamente.")

        solicitacao.refresh_from_db()

        # Determina o número do novo ciclo
        ultimo_ciclo = solicitacao.ciclos_execucao.order_by("-numero_ciclo").first()
        proximo_numero = (ultimo_ciclo.numero_ciclo + 1) if ultimo_ciclo else 1

        CicloExecucaoMatrizaria.objects.create(
            solicitacao=solicitacao,
            numero_ciclo=proximo_numero,
            usuario_inicio=usuario,
            usuario_inicio_nome=executor_nome,
            data_inicio=now,
            forma_encerramento="EM_ANDAMENTO",
            matriz_fisica_snapshot=solicitacao.matriz_identificador_snapshot,
        )

        HistoricoTransicaoServicoMatrizaria.objects.create(
            solicitacao=solicitacao,
            status_anterior=status_anterior,
            status_novo="EM_EXECUCAO",
            tipo_evento="INICIO",
            usuario=usuario,
            usuario_nome_snapshot=executor_nome,
            data_evento=now,
            observacao=f"Atendimento assumido (Ciclo #{proximo_numero}).",
        )

        return solicitacao

    @classmethod
    @transaction.atomic
    def editar_solicitacao(
        cls,
        solicitacao_id: int,
        usuario,
        versao_esperada: int,
        prensa: Optional[Machine],
        tipo_servico: TipoServicoMatrizaria,
        matriz_fisica: Optional[MatrizFisica],
        prioridade: str,
        descricao_solicitacao: str,
        motivo_edicao: str,
        destino: str = "MAQUINA",
    ) -> SolicitacaoServicoMatrizaria:
        """
        Permite a edição da solicitação antes do primeiro início técnico.
        - Exclusivo para status SOLICITADO e SEM ciclos iniciados;
        - Validação de concorrência com versao;
        - Registro imutável de auditoria com diff antes/depois e motivo.
        """
        solicitacao = SolicitacaoServicoMatrizaria.objects.select_for_update().filter(pk=solicitacao_id).first()
        if not solicitacao:
            raise ValidationError("Solicitação não encontrada.")

        # 0. Permissão de edição
        if usuario:
            from .decorators import _user_can_request_matrizaria, _user_can_inspect_matrizaria
            is_tv = (
                usuario.username.startswith("tv")
                or usuario.groups.filter(name__in=["Visualizador", "Visualizador Matrizaria"]).exists()
            )
            is_gestao = (
                usuario.is_superuser
                or usuario.is_staff
                or _user_can_inspect_matrizaria(usuario)
                or usuario.groups.filter(name__in=["Liderança de Produção", "Lideres", "Tecnicos_Lideres"]).exists()
                or usuario.has_perm("matrizaria.change_solicitacaoservicomatrizaria")
            )
            is_solicitante_proprio = (
                solicitacao.solicitado_por_id == usuario.id
                and _user_can_request_matrizaria(usuario)
            )
            if is_tv or not (is_solicitante_proprio or is_gestao):
                raise PermissionDenied("Apenas o solicitante original ou liderança autorizada podem editar a solicitação pendente.")

        # 1. Regra de estado: somente SOLICITADO e SEM ciclos de atendimento
        if solicitacao.status != "SOLICITADO":
            raise ValidationError(f"Apenas solicitações com status 'SOLICITADO' podem ser editadas (atual: '{solicitacao.get_status_display()}').")
        if solicitacao.ciclos_execucao.exists():
            raise ValidationError("Não é permitido editar uma solicitação cujo atendimento técnico já foi iniciado.")

        # 2. Concorrência otimista
        if solicitacao.versao != versao_esperada:
            raise ValidationError("Conflito de concorrência: a solicitação foi modificada ou seu atendimento foi iniciado por outro usuário. Atualize a página e tente novamente.")

        # 3. Motivo obrigatório
        motivo_edicao = (motivo_edicao or "").strip()
        if not motivo_edicao:
            raise ValidationError("O motivo da correção é obrigatório para auditoria.")

        # 4. Validação de Destino e Prensa
        if destino == "MATRIZARIA":
            prensa = None
            prensa_nome = "Matrizaria"
        elif destino == "MAQUINA":
            if not prensa:
                raise ValidationError("A prensa é obrigatória para serviços vinculados a máquina.")
            if is_checklist_machine(prensa):
                raise ValidationError("A máquina selecionada não é permitida para chamados de Matrizaria.")
            prensa_nome = prensa.nome
        else:
            raise ValidationError("Destino inválido.")

        # 5. Validação de Matriz Física
        if tipo_servico.exige_matriz_fisica and not matriz_fisica:
            raise ValidationError(f"O serviço '{tipo_servico.nome}' exige obrigatoriamente a indicação de uma matriz física.")

        # 6. Comparar alterações
        alteracoes = []
        if solicitacao.destino != destino:
            destino_labels = dict(SolicitacaoServicoMatrizaria.DESTINO_CHOICES)
            alteracoes.append(f"Destino: '{solicitacao.get_destino_display()}' -> '{destino_labels.get(destino, destino)}'")

        antigo_prensa_id = solicitacao.prensa_id
        novo_prensa_id = prensa.id if prensa else None
        if antigo_prensa_id != novo_prensa_id:
            antigo_nome = solicitacao.prensa.nome if solicitacao.prensa else (solicitacao.prensa_nome_snapshot or "Matrizaria")
            novo_nome = prensa.nome if prensa else "Matrizaria"
            alteracoes.append(f"Prensa: '{antigo_nome}' -> '{novo_nome}'")

        if solicitacao.tipo_servico_id != tipo_servico.id:
            alteracoes.append(f"Tipo: '{solicitacao.tipo_servico.nome}' -> '{tipo_servico.nome}'")

        old_matriz_nome = solicitacao.matriz_fisica.nome_exibicao if solicitacao.matriz_fisica else "N/A"
        new_matriz_nome = matriz_fisica.nome_exibicao if matriz_fisica else "N/A"
        if (solicitacao.matriz_fisica_id or None) != (matriz_fisica.id if matriz_fisica else None):
            alteracoes.append(f"Matriz: '{old_matriz_nome}' -> '{new_matriz_nome}'")

        if solicitacao.prioridade != prioridade:
            alteracoes.append(f"Prioridade: '{solicitacao.prioridade}' -> '{prioridade}'")

        if solicitacao.descricao_solicitacao.strip() != descricao_solicitacao.strip():
            alteracoes.append("Descrição da necessidade atualizada")

        # Se nenhuma informação foi modificada, não gera evento duplicado
        if not alteracoes:
            return solicitacao

        now = timezone.now()
        autor_nome = cls.get_user_display_name(usuario)

        # Salva dados atualizados
        solicitacao.destino = destino
        solicitacao.prensa = prensa
        if not solicitacao.prensa_nome_snapshot:
            solicitacao.prensa_nome_snapshot = prensa_nome
        solicitacao.tipo_servico = tipo_servico
        solicitacao.matriz_fisica = matriz_fisica
        solicitacao.prioridade = prioridade
        solicitacao.descricao_solicitacao = descricao_solicitacao.strip()
        solicitacao.versao += 1
        solicitacao.save()

        # Registra auditoria imutável
        HistoricoTransicaoServicoMatrizaria.objects.create(
            solicitacao=solicitacao,
            status_anterior="SOLICITADO",
            status_novo="SOLICITADO",
            tipo_evento="ALTERACAO_DADO",
            usuario=usuario,
            usuario_nome_snapshot=autor_nome,
            data_evento=now,
            observacao=f"Correção de solicitação: {motivo_edicao}",
            dados_modificados="; ".join(alteracoes),
        )

        return solicitacao

    @classmethod
    def get_matrizeiros_habilitados(cls, solicitacao=None):
        """
        Retorna QuerySet centralizado contendo apenas:
        - Usuários ativos (is_active=True);
        - Explicitamente vinculados ao grupo operacional 'Matrizaria';
        - Não sejam contas exclusivas de TV (tv, tv_matrizaria, grupos Visualizador/Visualizador Matrizaria);
        - Diferente do responsável atual atribuído na solicitação (se informada).
        """
        from django.contrib.auth import get_user_model
        User = get_user_model()

        qs = User.objects.filter(
            is_active=True,
            groups__name="Matrizaria",
        ).exclude(
            Q(username__in=["tv", "tv_matrizaria"])
            | Q(groups__name__in=["Visualizador", "Visualizador Matrizaria"])
        ).distinct()

        if solicitacao and solicitacao.responsavel_atribuido_id:
            qs = qs.exclude(pk=solicitacao.responsavel_atribuido_id)

        return qs.order_by("first_name", "last_name", "username")

    @classmethod
    def is_matrizeiro_habilitado(cls, usuario, solicitacao=None) -> bool:
        """
        Valida se o usuário é um colaborador operacional elegível da Matrizaria.
        """
        if not usuario or not usuario.is_active:
            return False
        return cls.get_matrizeiros_habilitados(solicitacao=solicitacao).filter(pk=usuario.pk).exists()

    @classmethod
    @transaction.atomic
    def transferir_responsabilidade(
        cls,
        solicitacao_id: int,
        usuario_autor=None,
        novo_responsavel=None,
        versao_esperada: int = 1,
        justificativa: str = "",
        usuario_origem=None,
        motivo: str = "",
    ) -> SolicitacaoServicoMatrizaria:
        """
        Transfere explicitamente a responsabilidade do atendimento para outro colaborador habilitado da Matrizaria.
        """
        usuario_autor = usuario_autor or usuario_origem
        justificativa = (justificativa or motivo or "").strip()

        solicitacao = SolicitacaoServicoMatrizaria.objects.filter(pk=solicitacao_id).first()
        if not solicitacao:
            raise ValidationError("Solicitação não encontrada.")

        if solicitacao.versao != versao_esperada:
            raise ValidationError("Conflito de concorrência: a solicitação foi modificada por outro usuário. Atualize a página e tente novamente.")

        if solicitacao.status != "EM_EXECUCAO":
            raise ValidationError("Apenas chamados com status 'Em Execução' podem ter sua responsabilidade transferida.")

        if not novo_responsavel or not novo_responsavel.is_authenticated:
            raise ValidationError("Novo responsável inválido.")

        if not cls.is_matrizeiro_habilitado(novo_responsavel, solicitacao=solicitacao):
            raise ValidationError("O colaborador selecionado não está habilitado para receber serviços da Matrizaria.")

        if not justificativa:
            raise ValidationError("A justificativa para a transferência é obrigatória.")

        autor_nome = cls.get_user_display_name(usuario_autor)
        novo_nome = cls.get_user_display_name(novo_responsavel)

        rows_updated = SolicitacaoServicoMatrizaria.objects.filter(
            pk=solicitacao_id,
            status="EM_EXECUCAO",
            versao=versao_esperada,
        ).update(
            responsavel_atribuido=novo_responsavel,
            responsavel_atribuido_nome=novo_nome,
            versao=F("versao") + 1,
        )

        if rows_updated == 0:
            raise ValidationError("Conflito de concorrência: a solicitação foi modificada por outro usuário. Atualize a página e tente novamente.")

        solicitacao.refresh_from_db()

        HistoricoTransicaoServicoMatrizaria.objects.create(
            solicitacao=solicitacao,
            status_anterior="EM_EXECUCAO",
            status_novo="EM_EXECUCAO",
            tipo_evento="TRANSFERENCIA",
            usuario=usuario_autor,
            usuario_nome_snapshot=autor_nome,
            data_evento=timezone.now(),
            observacao=f"Transferência de responsabilidade para {novo_nome}. Justificativa: {justificativa}",
        )

        return solicitacao

    @classmethod
    @transaction.atomic
    def finalizar_execucao(
        cls,
        solicitacao_id: int,
        usuario,
        descricao_servico_executado: str = "",
        matriz_fisica: Optional[MatrizFisica] = None,
        versao_esperada: int = 1,
        descricao_servico_realizado: str = "",
        **kwargs,
    ) -> SolicitacaoServicoMatrizaria:
        """
        Encerra a execução técnica do ciclo atual e transiciona para AGUARDANDO_CONFERENCIA.
        Exige descrição curta obrigatória e valida se a matriz física foi identificada quando o tipo de serviço exigir.
        """
        # Suporte a kwarg alternativa ou kwargs adicionais
        descricao = (descricao_servico_executado or descricao_servico_realizado or kwargs.get("descricao", "")).strip()

        solicitacao = SolicitacaoServicoMatrizaria.objects.filter(pk=solicitacao_id).first()
        if not solicitacao:
            raise ValidationError("Solicitação não encontrada.")

        if solicitacao.versao != versao_esperada:
            raise ValidationError("Conflito de concorrência: a solicitação foi modificada por outro usuário. Atualize a página e tente novamente.")

        if solicitacao.status != "EM_EXECUCAO":
            raise ValidationError(f"Não é possível finalizar execução a partir do status '{solicitacao.get_status_display()}'.")

        if not descricao or len(descricao) < 5:
            raise ValidationError("A descrição do serviço executado é obrigatória (mínimo 5 caracteres).")

        # Se foi enviada uma matriz física para associação
        if matriz_fisica:
            solicitacao.matriz_fisica = matriz_fisica
            solicitacao.matriz_identificador_snapshot = matriz_fisica.nome_exibicao
            solicitacao.save(update_fields=["matriz_fisica", "matriz_identificador_snapshot"])

        # Validação da exigência de matriz física
        if solicitacao.exige_matriz_fisica_snapshot and not solicitacao.matriz_fisica_id:
            raise ValidationError(
                "Este tipo de serviço exige a identificação da Matriz Física (exemplar) antes de liberar para conferência."
            )

        now = timezone.now()
        executor_nome = cls.get_user_display_name(usuario)

        # Encerra o ciclo de execução ativo
        ciclo_ativo = solicitacao.ciclos_execucao.filter(forma_encerramento="EM_ANDAMENTO").order_by("-numero_ciclo").first()
        if ciclo_ativo:
            ciclo_ativo.usuario_fim = usuario
            ciclo_ativo.usuario_fim_nome = executor_nome
            ciclo_ativo.data_fim = now
            ciclo_ativo.descricao_servico_executado = descricao
            ciclo_ativo.forma_encerramento = "FINALIZADO_TECNICO"
            ciclo_ativo.matriz_fisica_snapshot = solicitacao.matriz_identificador_snapshot
            ciclo_ativo.save()

        # Atualiza a solicitação
        rows_updated = SolicitacaoServicoMatrizaria.objects.filter(
            pk=solicitacao_id,
            status="EM_EXECUCAO",
            versao=versao_esperada,
        ).update(
            status="AGUARDANDO_CONFERENCIA",
            finalizado_por=usuario,
            data_fim_execucao=now,
            descricao_servico_executado=descricao,
            versao=F("versao") + 1,
        )

        if rows_updated == 0:
            raise ValidationError("Conflito de concorrência: a solicitação foi modificada por outro usuário. Atualize a página e tente novamente.")

        solicitacao.refresh_from_db()

        HistoricoTransicaoServicoMatrizaria.objects.create(
            solicitacao=solicitacao,
            status_anterior="EM_EXECUCAO",
            status_novo="AGUARDANDO_CONFERENCIA",
            tipo_evento="FINALIZACAO_EXECUCAO",
            usuario=usuario,
            usuario_nome_snapshot=executor_nome,
            data_evento=now,
            observacao=f"Execução técnica finalizada: {descricao_servico_executado.strip()}",
        )

        return solicitacao

    @classmethod
    @transaction.atomic
    def conferir_solicitacao(
        cls,
        solicitacao_id: int,
        usuario_conferente=None,
        aprovado: bool = True,
        versao_esperada: int = 1,
        observacao: str = "",
        **kwargs,
    ) -> SolicitacaoServicoMatrizaria:
        """
        Realiza a conferência do serviço.
        - Se aprovado: transiciona para CONCLUIDO (estado terminal).
        - Se reprovado: transiciona para AGUARDANDO_RETRABALHO (motivo obrigatório).
        Aplica regra estrita de anti-autoconferência (Segregação de Funções).
        """
        # Suporte a inversão posicional (versao_esperada como 3º argumento)
        if isinstance(aprovado, int) and not isinstance(aprovado, bool):
            aprovado, versao_esperada = bool(versao_esperada), aprovado

        solicitacao = SolicitacaoServicoMatrizaria.objects.filter(pk=solicitacao_id).first()
        if not solicitacao:
            raise ValidationError("Solicitação não encontrada.")

        if solicitacao.versao != versao_esperada:
            raise ValidationError("Conflito de concorrência: a solicitação foi modificada por outro usuário. Atualize a página e tente novamente.")

        if solicitacao.status != "AGUARDANDO_CONFERENCIA":
            raise ValidationError(f"Não é possível conferir chamado no status '{solicitacao.get_status_display()}'.")

        if not usuario_conferente or not usuario_conferente.is_authenticated:
            raise ValidationError("Usuário conferente inválido.")

        # REGRA DE SEGURANÇA: Impedir autoconferência
        # Nenhum usuário que tenha iniciado, finalizado ou participado como responsável dos ciclos pode aprovar/conferir
        conferente_id = usuario_conferente.id
        participou_da_execucao = (
            solicitacao.iniciado_por_id == conferente_id
            or solicitacao.finalizado_por_id == conferente_id
            or solicitacao.ciclos_execucao.filter(
                Q(usuario_inicio_id=conferente_id) | Q(usuario_fim_id=conferente_id)
            ).exists()
        )

        if participou_da_execucao:
            raise ValidationError(
                "Autoconferência bloqueada: você participou da execução técnica desta solicitação e não possui permissão para avaliá-la (Regra de Segregação de Funções)."
            )

        now = timezone.now()
        conferente_nome = cls.get_user_display_name(usuario_conferente)

        if aprovado:
            rows_updated = SolicitacaoServicoMatrizaria.objects.filter(
                pk=solicitacao_id,
                status="AGUARDANDO_CONFERENCIA",
                versao=versao_esperada,
            ).update(
                status="CONCLUIDO",
                conferido_por=usuario_conferente,
                conferido_por_nome=conferente_nome,
                data_conferencia=now,
                observacao_conferencia=observacao.strip() if observacao else "",
                versao=F("versao") + 1,
            )

            if rows_updated == 0:
                raise ValidationError("Conflito de concorrência: a solicitação foi alterada por outro usuário. Atualize a página e tente novamente.")

            solicitacao.refresh_from_db()

            HistoricoTransicaoServicoMatrizaria.objects.create(
                solicitacao=solicitacao,
                status_anterior="AGUARDANDO_CONFERENCIA",
                status_novo="CONCLUIDO",
                tipo_evento="CONFERENCIA_APROVADA",
                usuario=usuario_conferente,
                usuario_nome_snapshot=conferente_nome,
                data_evento=now,
                observacao=f"Serviço conferido e aprovado. {observacao.strip() if observacao else ''}".strip(),
            )
        else:
            # Reprovação / Retrabalho
            if not observacao or not observacao.strip():
                raise ValidationError("O motivo da devolução para retrabalho é obrigatório.")

            rows_updated = SolicitacaoServicoMatrizaria.objects.filter(
                pk=solicitacao_id,
                status="AGUARDANDO_CONFERENCIA",
                versao=versao_esperada,
            ).update(
                status="AGUARDANDO_RETRABALHO",
                conferido_por=usuario_conferente,
                conferido_por_nome=conferente_nome,
                data_conferencia=now,
                observacao_conferencia=observacao.strip(),
                quantidade_retrabalhos=F("quantidade_retrabalhos") + 1,
                versao=F("versao") + 1,
            )

            if rows_updated == 0:
                raise ValidationError("Conflito de concorrência: a solicitação foi alterada por outro usuário. Atualize a página e tente novamente.")

            solicitacao.refresh_from_db()

            HistoricoTransicaoServicoMatrizaria.objects.create(
                solicitacao=solicitacao,
                status_anterior="AGUARDANDO_CONFERENCIA",
                status_novo="AGUARDANDO_RETRABALHO",
                tipo_evento="REJEICAO_RETRABALHO",
                usuario=usuario_conferente,
                usuario_nome_snapshot=conferente_nome,
                data_evento=now,
                observacao=f"Devolvido para retrabalho: {observacao.strip()}",
            )

        return solicitacao

    @classmethod
    @transaction.atomic
    def cancelar_solicitacao(
        cls,
        solicitacao_id: int,
        usuario,
        versao_esperada: int,
        motivo_cancelamento: str,
    ) -> SolicitacaoServicoMatrizaria:
        """
        Cancela justificadamente a solicitação em aberto, interrompendo qualquer ciclo em andamento.
        """
        solicitacao = SolicitacaoServicoMatrizaria.objects.filter(pk=solicitacao_id).first()
        if not solicitacao:
            raise ValidationError("Solicitação não encontrada.")

        status_cancelaveis = ["SOLICITADO", "AGUARDANDO_RETRABALHO", "EM_EXECUCAO", "AGUARDANDO_CONFERENCIA"]
        if solicitacao.status not in status_cancelaveis:
            raise ValidationError(f"Não é possível cancelar uma solicitação com status '{solicitacao.get_status_display()}'.")

        if not motivo_cancelamento or not motivo_cancelamento.strip():
            raise ValidationError("O motivo do cancelamento é obrigatório.")

        now = timezone.now()
        autor_nome = cls.get_user_display_name(usuario)
        status_anterior = solicitacao.status

        # Se havia um ciclo em andamento, encerra como interrompido
        ciclo_ativo = solicitacao.ciclos_execucao.filter(forma_encerramento="EM_ANDAMENTO").order_by("-numero_ciclo").first()
        if ciclo_ativo:
            ciclo_ativo.usuario_fim = usuario
            ciclo_ativo.usuario_fim_nome = autor_nome
            ciclo_ativo.data_fim = now
            ciclo_ativo.forma_encerramento = "INTERROMPIDO_CANCELAMENTO"
            ciclo_ativo.descricao_servico_executado = f"Interrompido por cancelamento da solicitação: {motivo_cancelamento.strip()}"
            ciclo_ativo.save()

        rows_updated = SolicitacaoServicoMatrizaria.objects.filter(
            pk=solicitacao_id,
            status=status_anterior,
            versao=versao_esperada,
        ).update(
            status="CANCELADO",
            cancelado_por=usuario,
            cancelado_por_nome=autor_nome,
            data_cancelamento=now,
            motivo_cancelamento=motivo_cancelamento.strip(),
            versao=F("versao") + 1,
        )

        if rows_updated == 0:
            raise ValidationError("Conflito de concorrência: a solicitação foi modificada por outro usuário. Atualize a página e tente novamente.")

        solicitacao.refresh_from_db()

        HistoricoTransicaoServicoMatrizaria.objects.create(
            solicitacao=solicitacao,
            status_anterior=status_anterior,
            status_novo="CANCELADO",
            tipo_evento="CANCELAMENTO",
            usuario=usuario,
            usuario_nome_snapshot=autor_nome,
            data_evento=now,
            observacao=f"Cancelamento registrado: {motivo_cancelamento.strip()}",
        )

        return solicitacao

    @classmethod
    def get_timeline_status_at_date(cls, solicitacao: SolicitacaoServicoMatrizaria, target_dt: datetime) -> str:
        """
        Reconstitui o status histórico que a solicitação possuía em uma data/hora específica,
        consultando o último evento do HistoricoTransicao com data_evento <= target_dt.
        """
        ultimo_evento = (
            solicitacao.historico_transicoes.filter(data_evento__lte=target_dt)
            .order_by("-data_evento", "-id")
            .first()
        )
        if ultimo_evento:
            return ultimo_evento.status_novo
        return solicitacao.status

    @classmethod
    def get_unified_press_timeline(
        cls,
        machine_id: int,
        can_view_maintenance: bool = True,
        can_view_matrizaria: bool = True,
        origem_filtro: str = "TODOS",
    ) -> List[Dict[str, Any]]:
        """
        Combina de forma eficiente e desacoplada as ordens de Manutenção e os serviços de Matrizaria
        para exibição na tela da prensa, respeitando as permissões do usuário logado.
        """
        items: List[Dict[str, Any]] = []

        # 1. Serviços da Matrizaria
        if can_view_matrizaria and origem_filtro in ["TODOS", "MATRIZARIA"]:
            solicitacoes = (
                SolicitacaoServicoMatrizaria.objects.filter(prensa_id=machine_id)
                .select_related("tipo_servico", "matriz_fisica", "solicitado_por")
                .prefetch_related("ciclos_execucao")
                .order_by("-data_solicitacao")[:50]
            )
            for s in solicitacoes:
                matriz_txt = s.matriz_identificador_snapshot or (s.matriz_fisica.nome_exibicao if s.matriz_fisica else "Matriz não informada")
                items.append({
                    "id": s.id,
                    "origem": "MATRIZARIA",
                    "origem_label": "Matrizaria",
                    "badge_origem_classe": "warning text-dark border border-warning",
                    "protocolo": f"SM #{s.id}",
                    "titulo": s.tipo_servico_nome_snapshot or s.tipo_servico.nome,
                    "subtitulo": f"Matriz: {matriz_txt}",
                    "status": s.get_status_display(),
                    "status_code": s.status,
                    "badge_status_classe": s.badge_status_classe,
                    "responsavel": s.responsavel_atribuido_nome or s.solicitado_por_nome,
                    "data_referencia": s.data_solicitacao,
                    "data_inicio": s.data_inicio_execucao,
                    "data_fim": s.data_fim_execucao or s.data_conferencia or s.data_cancelamento,
                    "duracao_str": s.duracao_total_intervencao_str,
                    "descricao": s.descricao_solicitacao,
                    "url_detalhe": f"/matrizaria/servicos/{s.id}/",
                })

        # 2. Ordens da Manutenção
        if can_view_maintenance and origem_filtro in ["TODOS", "MANUTENCAO"]:
            allocations = (
                Allocation.objects.filter(maquina_id=machine_id)
                .select_related("tecnico", "usuario_operador", "ordem_servico")
                .prefetch_related("pausas")
                .order_by("-data_inicio")[:50]
            )
            for a in allocations:
                os_str = f"OS #{a.ordem_servico.numero_os}" if a.ordem_servico else f"Alocação #{a.id}"
                items.append({
                    "id": a.id,
                    "origem": "MANUTENCAO",
                    "origem_label": "Manutenção",
                    "badge_origem_classe": "primary border border-primary",
                    "protocolo": os_str,
                    "titulo": a.atividade_observacao[:60] if a.atividade_observacao else "Atendimento Mecânico/Elétrico",
                    "subtitulo": f"Técnico: {a.tecnico.nome if a.tecnico else 'N/A'}",
                    "status": a.get_status_display(),
                    "status_code": a.status,
                    "badge_status_classe": "success" if a.status == "CONCLUIDO" else ("warning text-dark" if a.status == "EM_PAUSA" else "danger"),
                    "responsavel": a.tecnico.nome if a.tecnico else "Técnico",
                    "data_referencia": a.data_inicio,
                    "data_inicio": a.data_inicio,
                    "data_fim": a.data_fim,
                    "duracao_str": a.tempo_decorrido_str,
                    "descricao": a.atividade_observacao,
                    "url_detalhe": f"/ordens-servico/{a.ordem_servico_id}/" if a.ordem_servico_id else None,
                })

        # Ordena a mescla de forma decrescente pela data de referência
        items.sort(key=lambda x: x["data_referencia"], reverse=True)
        return items

    @classmethod
    def get_tv_dashboard_context(cls) -> Dict[str, Any]:
        """
        Monta o contexto completo para a TV da Matrizaria:
        1. Fila de serviços operacionais
        2. Alertas preventivos de limite de bladder (consumindo BladderTrackingService)
        """
        now = timezone.localtime(timezone.now())

        # 1. Serviços da Matrizaria
        solicitados = SolicitacaoServicoMatrizaria.objects.filter(status="SOLICITADO").select_related("prensa", "tipo_servico", "matriz_fisica").order_by("-prioridade", "data_solicitacao")
        retrabalhos = SolicitacaoServicoMatrizaria.objects.filter(status="AGUARDANDO_RETRABALHO").select_related("prensa", "tipo_servico", "matriz_fisica").order_by("-prioridade", "data_solicitacao")
        em_execucao = SolicitacaoServicoMatrizaria.objects.filter(status="EM_EXECUCAO").select_related("prensa", "tipo_servico", "matriz_fisica", "responsavel_atribuido").order_by("data_inicio_execucao")
        aguardando_conf = SolicitacaoServicoMatrizaria.objects.filter(status="AGUARDANDO_CONFERENCIA").select_related("prensa", "tipo_servico", "matriz_fisica").order_by("data_fim_execucao")

        list_retrabalhos = list(retrabalhos)
        list_solicitados = list(solicitados)
        fila_solicitados = list_retrabalhos + list_solicitados

        servicos_data = {
            "total_solicitados": solicitados.count(),
            "total_retrabalhos": retrabalhos.count(),
            "total_em_execucao": em_execucao.count(),
            "total_aguardando_conferencia": aguardando_conf.count(),
            "fila_solicitados": fila_solicitados,
            "solicitados": list_solicitados,
            "retrabalhos": list_retrabalhos,
            "em_execucao": list(em_execucao),
            "aguardando_conferencia": list(aguardando_conf),
        }

        # 2. Alertas de Bladder (Consumo canônico do BladderTrackingService da Produção)
        bladder_alerts = []
        scada_status = "ONLINE"
        scada_mensagem = ""

        try:
            from production.services import BladderTrackingService
            active_context = BladderTrackingService.get_active_bladders_context(filters={"near_limit": "1"})
            # Filtra os bladders que estão em estado de ATENCAO (>=80%) ou CRITICO (>=95%)
            for b in active_context.get("bladders", []):
                if b.get("vida_status") in ["ATENCAO", "CRITICO"]:
                    bladder_alerts.append({
                        "prensa_nome": b.get("prensa_nome"),
                        "cavidade_nome": b.get("cavidade_nome"),
                        "codigo_bla": b.get("codigo_bla"),
                        "lote_completo": b.get("lote_completo"),
                        "matriz_nome": b.get("matriz_nome"),
                        "passadas": b.get("passadas"),
                        "limite": b.get("limite"),
                        "limite_str": b.get("limite_str"),
                        "pct_vida": b.get("pct_vida"),
                        "pct_bar": b.get("pct_bar", 0),
                        "vida_badge": b.get("vida_badge"),
                        "vida_label": b.get("vida_label"),
                        "vida_status": b.get("vida_status"),
                    })
        except Exception as e:
            scada_status = "OFFLINE"
            scada_mensagem = f"Telemetria SCADA temporariamente indisponível ({str(e)[:60]})."

        return {
            "servicos": servicos_data,
            "bladder_alerts": bladder_alerts,
            "total_bladder_alerts": len(bladder_alerts),
            "scada_status": scada_status,
            "scada_mensagem": scada_mensagem,
            "timestamp": now.strftime("%d/%m/%Y %H:%M:%S"),
            "hora_atual": now.strftime("%H:%M"),
        }

    @classmethod
    def consultar_relatorio(
        cls,
        criterio_temporal: str,
        data_inicio: date,
        data_fim: date,
        prensa_id: Optional[int] = None,
        tipo_servico_id: Optional[int] = None,
        status: Optional[str] = None,
        solicitante_id: Optional[int] = None,
        executante_id: Optional[int] = None,
        destino: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Executa consulta canônica de relatórios da Matrizaria respeitando os 4 critérios temporais:
        1. COM_EXECUCAO (Padrão): Solicitações com algum ciclo de execução no período (inclui retrabalhos e ciclos iniciados antes).
        2. ABERTAS: Solicitações abertas no período.
        3. FINALIZADAS: Execuções técnicas finalizadas no período.
        4. CONCLUIDAS: Serviços conferidos e concluídos no período.
        """
        tz = timezone.get_current_timezone()
        dt_inicio_aware = timezone.make_aware(datetime.combine(data_inicio, time.min), tz)
        dt_fim_exclusive = timezone.make_aware(datetime.combine(data_fim + timedelta(days=1), time.min), tz)
        now = timezone.now()

        # Base QuerySet
        qs = SolicitacaoServicoMatrizaria.objects.all()

        if criterio_temporal == "COM_EXECUCAO":
            # Ciclo que começou antes do fim exclusivo E (terminou após o início OU está em andamento)
            filtro_ciclo = (
                Q(ciclos_execucao__data_inicio__lt=dt_fim_exclusive)
                & (
                    Q(ciclos_execucao__data_fim__gte=dt_inicio_aware)
                    | (
                        Q(ciclos_execucao__data_fim__isnull=True)
                        & Q(ciclos_execucao__forma_encerramento="EM_ANDAMENTO")
                    )
                )
            )
            qs = qs.filter(filtro_ciclo)
        elif criterio_temporal == "ABERTAS":
            qs = qs.filter(data_solicitacao__gte=dt_inicio_aware, data_solicitacao__lt=dt_fim_exclusive)
        elif criterio_temporal == "FINALIZADAS":
            qs = qs.filter(
                ciclos_execucao__data_fim__gte=dt_inicio_aware,
                ciclos_execucao__data_fim__lt=dt_fim_exclusive,
                ciclos_execucao__forma_encerramento="FINALIZADO_TECNICO",
            )
        elif criterio_temporal == "CONCLUIDAS":
            qs = qs.filter(
                data_conferencia__gte=dt_inicio_aware,
                data_conferencia__lt=dt_fim_exclusive,
                status="CONCLUIDO",
            )
        elif criterio_temporal == "CANCELADAS":
            qs = qs.filter(
                data_cancelamento__gte=dt_inicio_aware,
                data_cancelamento__lt=dt_fim_exclusive,
                status="CANCELADO",
            )
        else:
            # Fallback seguro
            qs = qs.filter(data_solicitacao__gte=dt_inicio_aware, data_solicitacao__lt=dt_fim_exclusive)

        # Filtros adicionais
        if destino:
            qs = qs.filter(destino=destino)
        if prensa_id:
            qs = qs.filter(prensa_id=prensa_id)
        if tipo_servico_id:
            qs = qs.filter(tipo_servico_id=tipo_servico_id)
        if status:
            qs = qs.filter(status=status)
        if solicitante_id:
            qs = qs.filter(solicitado_por_id=solicitante_id)
        if executante_id:
            qs = qs.filter(
                Q(ciclos_execucao__usuario_inicio_id=executante_id)
                | Q(ciclos_execucao__usuario_fim_id=executante_id)
            )

        qs = (
            qs.distinct()
            .select_related(
                "prensa",
                "tipo_servico",
                "matriz_fisica",
                "solicitado_por",
                "responsavel_atribuido",
                "conferido_por",
                "cancelado_por",
            )
            .prefetch_related("ciclos_execucao", "historico_transicoes")
            .order_by("-data_solicitacao")
        )

        resultados = []
        status_map = dict(SolicitacaoServicoMatrizaria.STATUS_CHOICES)

        for s in qs:
            # Reconstituição do status histórico no final do período filtrado
            target_status_dt = dt_fim_exclusive - timedelta(microseconds=1)
            status_fim_periodo_cod = cls.get_timeline_status_at_date(s, target_status_dt)
            status_fim_periodo_label = status_map.get(status_fim_periodo_cod, status_fim_periodo_cod)

            # Cálculo da Duração da Intervenção Técnica (total e dentro do período)
            duracao_total_segundos = 0
            duracao_periodo_segundos = 0
            ciclos_list = list(s.ciclos_execucao.all().order_by("numero_ciclo"))

            for c in ciclos_list:
                c_inicio = c.data_inicio
                c_fim = c.data_fim or (now if c.forma_encerramento == "EM_ANDAMENTO" else c.data_inicio)

                # Total do ciclo
                duracao_ciclo = max(0, int((c_fim - c_inicio).total_seconds()))
                duracao_total_segundos += duracao_ciclo

                # Interseção com o período [dt_inicio_aware, dt_fim_exclusive)
                clamp_start = max(c_inicio, dt_inicio_aware)
                clamp_end = min(c_fim, dt_fim_exclusive)
                if clamp_end > clamp_start:
                    duracao_periodo_segundos += max(0, int((clamp_end - clamp_start).total_seconds()))

            def format_duracao(seconds: int) -> str:
                if seconds <= 0:
                    return "0m"
                h = seconds // 3600
                m = (seconds % 3600) // 60
                if h > 0:
                    return f"{h}h {m:02d}m"
                return f"{m}m"

            matriz_ident = (
                s.matriz_identificador_snapshot
                or (s.matriz_fisica.nome_exibicao if s.matriz_fisica else "N/A")
            )

            # Todos os executantes envolvidos
            executantes = set()
            for c in ciclos_list:
                if c.usuario_inicio_nome:
                    executantes.add(c.usuario_inicio_nome)
                if c.usuario_fim_nome:
                    executantes.add(c.usuario_fim_nome)
            executantes_str = ", ".join(sorted(executantes)) if executantes else (s.responsavel_atribuido_nome or "Não atribuído")

            resultados.append({
                "solicitacao": s,
                "id": s.id,
                "protocolo": f"SM #{s.id}",
                "prensa_nome": s.prensa_nome_snapshot or (s.prensa.nome if s.prensa else "Matrizaria"),
                "tipo_servico_nome": s.tipo_servico_nome_snapshot or s.tipo_servico.nome,
                "matriz_identificador": matriz_ident,
                "status_atual": s.status,
                "status_atual_label": s.get_status_display(),
                "status_fim_periodo": status_fim_periodo_cod,
                "status_fim_periodo_label": status_fim_periodo_label,
                "solicitante_nome": s.solicitado_por_nome,
                "data_solicitacao": s.data_solicitacao,
                "executantes_str": executantes_str,
                "data_inicio_execucao": s.data_inicio_execucao,
                "data_fim_execucao": s.data_fim_execucao,
                "conferente_nome": s.conferido_por_nome,
                "data_conferencia": s.data_conferencia,
                "cancelado_por_nome": s.cancelado_por_nome,
                "data_cancelamento": s.data_cancelamento,
                "motivo_cancelamento": s.motivo_cancelamento,
                "motivo_devolucao_retrabalho": s.motivo_devolucao_retrabalho,
                "quantidade_retrabalhos": s.quantidade_retrabalhos,
                "quantidade_ciclos": len(ciclos_list),
                "duracao_total_intervencao_str": format_duracao(duracao_total_segundos),
                "duracao_periodo_intervencao_str": format_duracao(duracao_periodo_segundos),
                "duracao_total_segundos": duracao_total_segundos,
                "duracao_periodo_segundos": duracao_periodo_segundos,
                "descricao_solicitacao": s.descricao_solicitacao,
                "descricao_servico_executado": s.descricao_servico_executado or "",
                "ciclos": ciclos_list,
            })

        return resultados

    @classmethod
    @transaction.atomic(using="default")
    def excluir_solicitacao_operacional(cls, solicitacao_id: int, usuario) -> None:
        """
        Permite a exclusão definitiva de uma solicitação no fluxo operacional.
        Regras:
        - Status deve ser estritamente 'SOLICITADO'
        - Não pode ter ciclos de execução iniciados (ciclos_execucao.count() == 0)
        - Usuário deve ter permissão (solicitante original ou gestão/liderança autorizada)
        """
        solicitacao = SolicitacaoServicoMatrizaria.objects.select_for_update().filter(pk=solicitacao_id).first()
        if not solicitacao:
            raise ValidationError("Solicitação não encontrada.")

        # 1. Permissão
        if usuario:
            from .decorators import _user_can_request_matrizaria, _user_can_inspect_matrizaria
            is_tv = (
                usuario.username.startswith("tv")
                or usuario.groups.filter(name__in=["Visualizador", "Visualizador Matrizaria"]).exists()
            )
            is_gestao = (
                usuario.is_superuser
                or usuario.is_staff
                or _user_can_inspect_matrizaria(usuario)
                or usuario.groups.filter(name__in=["Liderança de Produção", "Lideres", "Tecnicos_Lideres"]).exists()
                or usuario.has_perm("matrizaria.delete_solicitacaoservicomatrizaria")
            )
            is_solicitante_proprio = (
                solicitacao.solicitado_por_id == usuario.id
                and _user_can_request_matrizaria(usuario)
            )
            if is_tv or not (is_solicitante_proprio or is_gestao):
                raise PermissionDenied("Apenas o solicitante original ou liderança autorizada podem excluir uma solicitação pendente.")

        # 2. Status e ciclos
        if solicitacao.status != "SOLICITADO":
            raise ValidationError(
                f"Não é permitido excluir uma solicitação com status '{solicitacao.get_status_display()}'. Apenas chamados pendentes podem ser excluídos."
            )
        if solicitacao.ciclos_execucao.exists():
            raise ValidationError("Não é permitido excluir uma solicitação cujo atendimento técnico já foi iniciado. Utilize o cancelamento.")

        # 3. Remove histórico inicial e o objeto
        solicitacao.historico_transicoes.all().delete()
        solicitacao.delete()


class AdminCascadeDeletionService:
    """
    Serviço administrativo exclusivo para superusuários realizarem exclusão forçada
    de registros com relacionamentos dependentes (PROTECT) sem alterar as garantias
    globais do modelo nem afetar o alias scada.
    """

    @classmethod
    def validar_permissao_superuser(cls, user):
        if not user or not user.is_authenticated or not user.is_superuser:
            raise PermissionDenied("Apenas superusuários têm permissão para exclusão administrativa forçada.")

    @classmethod
    def coletar_dependentes(cls, queryset_ou_obj) -> List[Dict[str, Any]]:
        """
        Inspeciona e retorna um resumo estruturado dos registros e seus dependentes que seriam afetados.
        """
        from django.db.models import QuerySet
        if isinstance(queryset_ou_obj, QuerySet):
            objs = list(queryset_ou_obj)
        elif isinstance(queryset_ou_obj, list):
            objs = queryset_ou_obj
        else:
            objs = [queryset_ou_obj]

        preview = []
        for obj in objs:
            if getattr(obj._meta, "managed", True) is False:
                raise ValidationError(f"O modelo '{obj._meta.verbose_name}' não é gerenciado (SCADA) e não pode ser excluído.")

            item = {
                "objeto": str(obj),
                "model": str(obj._meta.verbose_name),
                "id": obj.pk,
                "dependentes": [],
            }
            if isinstance(obj, SolicitacaoServicoMatrizaria):
                n_ciclos = obj.ciclos_execucao.count()
                if n_ciclos:
                    item["dependentes"].append(f"{n_ciclos} Ciclo(s) de Execução")
                n_hist = obj.historico_transicoes.count()
                if n_hist:
                    item["dependentes"].append(f"{n_hist} Histórico(s) de Transição")
            elif isinstance(obj, TipoServicoMatrizaria):
                n_sol = obj.solicitacoes.count()
                if n_sol:
                    item["dependentes"].append(f"{n_sol} Solicitação(ões) de Serviço vinculada(s)")
            elif isinstance(obj, MatrizFisica):
                n_sol = obj.solicitacoes_servico.count()
                if n_sol:
                    item["dependentes"].append(f"{n_sol} Solicitação(ões) de Serviço vinculada(s)")

            preview.append(item)
        return preview

    @classmethod
    def excluir_objeto(cls, obj, user) -> Dict[str, Any]:
        cls.validar_permissao_superuser(user)
        return cls.excluir_objetos([obj], user)

    @classmethod
    def excluir_objetos(cls, queryset_ou_lista, user) -> Dict[str, Any]:
        cls.validar_permissao_superuser(user)
        from django.db.models import QuerySet
        objs = list(queryset_ou_lista) if isinstance(queryset_ou_lista, QuerySet) else list(queryset_ou_lista)

        total_deletados = 0
        detalhes = {}

        with transaction.atomic(using="default"):
            for obj in objs:
                if getattr(obj._meta, "managed", True) is False:
                    raise ValidationError(f"O modelo '{obj._meta.verbose_name}' é não-gerenciado (SCADA) e protegido contra exclusão.")

                if isinstance(obj, SolicitacaoServicoMatrizaria):
                    c_cnt, _ = obj.ciclos_execucao.all().delete()
                    h_cnt, _ = obj.historico_transicoes.all().delete()
                    detalhes["CicloExecucaoMatrizaria"] = detalhes.get("CicloExecucaoMatrizaria", 0) + c_cnt
                    detalhes["HistoricoTransicaoServicoMatrizaria"] = detalhes.get("HistoricoTransicaoServicoMatrizaria", 0) + h_cnt
                    total_deletados += c_cnt + h_cnt
                elif isinstance(obj, TipoServicoMatrizaria):
                    for sol in list(obj.solicitacoes.all()):
                        c_cnt, _ = sol.ciclos_execucao.all().delete()
                        h_cnt, _ = sol.historico_transicoes.all().delete()
                        total_deletados += c_cnt + h_cnt
                        s_cnt, _ = sol.delete()
                        total_deletados += s_cnt
                elif isinstance(obj, MatrizFisica):
                    for sol in list(obj.solicitacoes_servico.all()):
                        c_cnt, _ = sol.ciclos_execucao.all().delete()
                        h_cnt, _ = sol.historico_transicoes.all().delete()
                        total_deletados += c_cnt + h_cnt
                        s_cnt, _ = sol.delete()
                        total_deletados += s_cnt

                m_name = obj._meta.object_name
                cnt, _ = obj.delete()
                detalhes[m_name] = detalhes.get(m_name, 0) + cnt
                total_deletados += cnt

        return {"total_deletados": total_deletados, "detalhes": detalhes}
