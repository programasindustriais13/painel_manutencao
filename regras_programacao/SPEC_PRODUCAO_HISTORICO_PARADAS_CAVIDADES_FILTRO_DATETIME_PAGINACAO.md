# 🧠 SPEC — HISTÓRICO DE PARADAS POR CAVIDADE, FILTRO POR DATA/HORA E PAGINAÇÃO

---

## 📌 1. CONTEXTO

- **URL:** `/producao/maquinas/<machine_id>/`
- **Contexto:** Módulo de Produção Industrial — Página de Detalhes da Máquina, Seção "Histórico de Eventos de Parada".
- **Perfis afetados:** Líder de Produção (`@lider_producao_required`), Líder/PCP, Administradores.

---

## ❗ 2. PROBLEMA ATUAL

1. A coluna **Status** exibe os badges "Aberto" / "Fechado" e "Em andamento", mas não agrega valor analítico útil e polui a interface.
2. A tabela apresenta apenas os **motivos gerais de parada** da imprensa, ocultando quais cavidades pararam e por quais motivos específicos (ex: Ajuste de Matriz na Cavidade 1, Elétrica na Cavidade 2).
3. O código geral `0` (ou ausente) é exibido cruamente ou como "Motivo da prensa não informado" sem uma mensagem amigável padronizada indicando ausência de parada geral.
4. Os filtros temporais atuais aceitam apenas datas simples (`data_inicio` e `data_final`), impedindo filtragens precisas por turno ou intervalo de horas especifico.
5. Não existe **paginação no backend** (`Paginator` Django), carregando todos os eventos do período na memória, tornando a página longa e lenta quando a quantidade de registros históricos cresce.
6. A troca de páginas poderia perder os filtros aplicados se a query string não for preservada adequadamente.

---

## 🎯 3. OBJETIVO

1. Remover a coluna **Status** da interface da tabela.
2. Traduzir o motivo geral `0` para a mensagem amigável **"Sem parada geral"** (ou descrição mapeada para códigos conhecidos e fallback seguro `Motivo desconhecido (código X)` para códigos não mapeados).
3. Incluir a coluna **"Motivos por Cavidade"** exibindo de forma compacta (badges/linhas resumidas com expansão Bootstrap/JS para múltiplos registros) os motivos de parada por cavidade registrados durante o intervalo histórico sobreposto.
4. Adicionar filtro por **data e horário** (`<input type="datetime-local">`) via parâmetros GET `inicio` e `fim`.
5. Implementar a regra conceitual de **sobreposição temporal** no Django ORM:
   `evento.inicio <= fim_do_filtro AND (evento.fim >= inicio_do_filtro OR evento.fim IS NULL)`.
6. Recortar o cálculo da **"Duração no Período"** exclusivamente ao intervalo filtrado `[inicio_efetivo, fim_efetivo]`.
7. Adicionar **paginação no backend** (10 eventos por página) preservando a query string (filtros `inicio`, `fim`, etc.) ao navegar.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Arquivos afetados:
- `production/views.py`: Recepção e validação dos parâmetros `inicio` e `fim` (`datetime-local`), gerenciamento do `Paginator`.
- `production/services.py`: Lógica de busca de `ProductionDowntimeEvent` com sobreposição temporal, cálculo da duração recortada, prefetch e busca dos eventos de cavidade `ProductionCavityDowntimeEvent` sobrepostos, paginação e formatação amigável dos motivos.
- `production/templates/production/machine_detail.html`: Remoção da coluna Status, adição dos inputs `<input type="datetime-local">`, inclusão da coluna "Motivos por Cavidade", componente de detalhes expansíveis e controles de paginação mantendo a query string.
- `production/models.py`: Nenhuma alteração estrutural nos models existentes; criação de índices de performance em `ProductionDowntimeEvent` (`machine_config`, `inicio`) via migration aditiva se justificável.
- `production/migrations/`: Migration aditiva apenas para novos índices no banco `default`.
- `production/tests.py`: Testes automatizados cobrindo remoção da coluna Status, tradução do motivo geral, motivos por cavidade históricos, filtro temporal por horário, sobreposição, duração recortada no período, paginação e preservação dos parâmetros GET.
- `Instrucoes.txt`: Documentação das alterações e comandos.

---

## 🚫 5. FORA DE ESCOPO

- **PROIBIDO** criar novo projeto, app Django ou ambiente virtual (.venv).
- **PROIBIDO** criar histórico paralelo ou modelo duplicado (reutilizar `ProductionDowntimeEvent` e `ProductionCavityDowntimeEvent`).
- **PROIBIDO** realizar consultas históricas amplas à tabela `pointvalues` do Scada dentro da requisição HTTP.
- **PROIBIDO** qualquer escrita ou execução de migração no banco de dados `scada`.
- **PROIBIDO** usar SQL direto ou métodos descontinuados.
- **PROIBIDO** realizar `git commit`, `git push` ou deploy.

---

## 🔐 6. REGRAS OBRIGATÓRIAS (CONSTITUTION & DATABASE ROUTER)

- Mantida rigorosamente a compatibilidade SQLite e MySQL.
- Respeitado o `DatabaseRouter`: todas as leituras e gravações de estado/histórico são locais no banco `default`. O banco `scada` permanece 100% somente leitura.
- Mantidas as permissões `@lider_producao_required` na rota `/producao/maquinas/<id>/`.

---

## ⚙️ 7. REGRAS DE NEGÓCIO

### 7.1. Colunas da Tabela Final
1. **Início da Parada** (`d/m/Y H:i:s`)
2. **Fim da Parada** (exibe `d/m/Y H:i:s` ou `<span class="text-danger fw-semibold">Em andamento</span>` para eventos abertos)
3. **Duração no Período** (ex: `20m`, `50s`, `1m 46s`)
4. **Motivo Geral de Parada** ("Sem parada geral", descrição amigável ou `Motivo desconhecido (código X)`)
5. **Motivos por Cavidade** (ex: `Cav. 1: Ajuste de matriz`, `Cav. 2: Elétrica` ou `Nenhuma parada por cavidade`)

### 7.2. Motivos por Cavidade (Histórico Real)
- O motivo de cavidade exibido reflete os registros da tabela `ProductionCavityDowntimeEvent` que se sobrepõem ao intervalo do filtro/evento.
- Omite cavidades com código `0`, "Normal" ou sem parada.
- Caso ocorram múltiplas transições de motivo na mesma cavidade durante o período, todas são preservadas e apresentadas resumidamente, permitindo expansão visual via Bootstrap collapse.
- Caso nenhuma cavidade apresente parada no período, exibe: **"Nenhuma parada por cavidade"**.

### 7.3. Validação do Filtro Temporal (`inicio` / `fim`)
- Aceita formato ISO `YYYY-MM-DDTHH:MM` via `<input type="datetime-local">`.
- Converte para datetimes timezone-aware via `timezone.make_aware()`.
- Garante que `inicio <= fim`. Em caso de formato ou intervalo inválido, exibe mensagem amigável sem erro 500 e preserva os dados informados.
- Período padrão caso nenhum filtro seja especificado: últimos 7 dias.

### 7.4. Regra de Sobreposição Temporal
```python
Q(inicio__lte=end_dt) & (Q(fim__isnull=True) | Q(fim__gte=start_dt))
```

### 7.5. Cálculo da Duração no Período
```python
eff_start = max(ev.inicio, start_dt)
eff_end = min(ev.fim or timezone.now(), end_dt)
duracao_segundos = max(0, int((eff_end - eff_start).total_seconds()))
```

### 7.6. Paginação (10 registros por página)
- Utiliza `django.core.paginator.Paginator`.
- Ordenação: `-inicio`.
- Preserva parâmetros GET (`inicio`, `fim`, etc.) nos links de navegação.

---

## 🧪 8. CRITÉRIOS DE ACEITAÇÃO

- [ ] Cabeçalho "Status" e badges exclusivas da coluna Status removidas da interface.
- [ ] Eventos abertos mostram "Em andamento" na coluna "Fim da Parada".
- [ ] Código geral `0` exibido como "Sem parada geral". Códigos desconhecidos com fallback "Motivo desconhecido (código X)".
- [ ] Coluna "Motivos por Cavidade" apresenta histórico real dos eventos de cavidades sobrepostos ao período.
- [ ] Filtro por data e hora funcionando via GET (`inicio` e `fim`).
- [ ] Consulta ORM traz sobreposição temporal completa de eventos.
- [ ] Duração calculada estritamente dentro do recorte do período filtrado.
- [ ] Paginação de 10 itens por página com preservação da query string.
- [ ] 100% dos testes da aplicação `production` executando com sucesso (OK).
- [ ] Zero escrita ou alteração de esquema no banco `scada`.

---

## ⚠️ 9. RISCOS E MITIGAÇÕES

- **Risco:** Consulta N+1 ao buscar motivos por cavidade para cada evento de parada.
  - **Mitigação:** Filtrar e paginar os `ProductionDowntimeEvent` primeiro; depois, realizar `prefetch_related` ou query agrupada por `cavity_config__in` apenas para os eventos da página atual.
- **Risco:** Perda de timezone na conversão dos parâmetros `datetime-local`.
  - **Mitigação:** Utilizar `django.utils.timezone.make_aware()` com o fuso horário configurado no Django (`America/Sao_Paulo`).

---

## 🔍 10. PLANO DE IMPLEMENTAÇÃO E SUBAGENTES

### Ordem Obrigatória:
1. **Subagente Arquiteto:** Valida a arquitetura relacional, reutilização do model `ProductionCavityDowntimeEvent`, indexação e ausência de SQL direto/acesso indevido ao Scada.
2. **Subagente Backend:** Implementa as alterações em `production/services.py`, `production/views.py`, `production/templates/production/machine_detail.html` e migrations aditivas.
3. **Subagente QA:** Executa os testes automatizados, valida todos os critérios de aceitação e audita a ausência de regressão.

---

## 🧪 11. EVIDÊNCIAS DE TESTE

- Testes automatizados executados via `python manage.py test production`.
- Validação visual em telas pequenas (layout responsivo e rolável).
