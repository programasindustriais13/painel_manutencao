# 📋 Walkthrough — Revisão Pontual da Importação em Lote de Matrizes Físicas

## 🎯 Objetivo Cumprido
Realizar a revisão técnica pontual do importador e simulador de matrizes físicas (`MatrizFisica`), separando rigorosamente as dimensões de **Correspondência de Catálogo**, **Conferência da Fonte** e **Autorização de Carga**, sem efetuar nenhuma alteração no banco de produção e sem aplicar o inventário real.

---

## 🛠️ 1. Correções Implementadas no Importador

1. **Separação das Três Dimensões:**
   - `status_cat`: Avalia existência no catálogo (`UNICA`, `AMBIGUA`, `AUSENTE`, `ID_INCOMPATIVEL`, `INCONSISTENTE_MATEMATICA`).
   - `status_fonte`: Avalia a qualidade da anotação da folha (`CONFERIDO` vs `PENDENTE_CONFERENCIA`).
   - `aprovado`: Decisão de carga controlada. O parâmetro `--aprovar-linhas-seguras` agora aprova **estritamente** linhas onde `status_cat == "UNICA"` e `status_fonte == "CONFERIDO"`.
2. **Bloqueio Rigoroso de P2-23 (HOPPER 4.80/400-8):**
   - A linha possui correspondência com o código SCADA 15 (`4.80/4.00-8`), mas sua anotação na planilha possui a ressalva explícita `CONFERIR MEDIDA`. Permanece **BLOQUEADA**.
3. **Rejeição de IDs Incompatíveis:**
   - Se o usuário informar na planilha um `id_catalogo` de produto/medida divergente da linha, o importador marca `ID_INCOMPATIVEL` e bloqueia a carga.
4. **Idempotência Independente de SHA-256:**
   - Prevenção de duplicidade baseada na chave unívoca de cada exemplar (`chave_unidade_origem` e tupla `modelo + numero_sequencial`). Arquivos regravados pelo Excel preservam as unidades sem duplicar.
5. **Proteção Contra Alteração de Quantidade:**
   - Se uma linha já importada tiver sua quantidade alterada em planilha futura, o sistema bloqueia a execução por `Divergência de inventário`, impedindo corrupção de histórico.
6. **Planilha de Reconciliação Gerada sem Alterar o Original:**
   - Geração automática do arquivo `relatorio_reconciliacao_inventario.xlsx` com duas abas formatadas.

---

## 📊 2. Resultado Recalculado da Simulação

| Classificação | Linhas | Unidades | Situação para Carga |
| :--- | :---: | :---: | :--- |
| **Catálogo Único + Fonte 100% Conferida (Seguras)** | **13** | **18** | **ELEGÍVEIS** (via `--aprovar-linhas-seguras`) |
| **Catálogo Único + Fonte com Ressalva/Pendência** | **4** | **7** | **BLOQUEADAS** (`P2-23`, `P2-12`, `P2-13`, `P2-14`) |
| **Catálogo Ambíguo (Variantes com câmara vs S/C)** | **18** | **36** | **BLOQUEADAS** (aguardam decisão Cenário A vs B) |
| **Modelos Ausentes no Catálogo SCADA** | **17** | **17** | **BLOQUEADAS** (proposta técnica preparada) |
| **Inconsistências Matemáticas** | **0** | **0** | **OK** (todas as somas conferem) |
| **Total do Inventário** | **52** | **78** | **0 gravadas no banco real** |

---

## 🧪 3. Evidências dos Testes Automatizados

Os testes foram executados exclusivamente em banco SQLite isolado de testes criado pelo Django (`test_db.sqlite3`), com total isolamento do banco local e do banco SCADA.

- **Suíte Específica (`matrizaria.test_importacao_matrizes`):** 19 testes (100% aprovados).
- **Suíte Completa da Matrizaria (`matrizaria`):** 38 testes (100% aprovados).

### Verificação de Estado do Banco de Dados:
- Contagem de `MatrizFisica` antes da simulação: **0**
- Contagem de `MatrizFisica` após a simulação: **0**
- Contagem de `LoteImportacaoMatrizFisica`: **0**
- **Confirmação:** Nenhuma unidade foi gravada no banco real.
