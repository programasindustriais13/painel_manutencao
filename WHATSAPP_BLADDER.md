# WhatsApp Bladder — instalação e uso

## Publicar no servidor

1. Na pasta `C:\03_PYTHON\11_Painel Manutencao\painel_manutencao`, faça o deploy habitual (`git pull` e `scripts\deploy_production.ps1`). Ele aplica a migração `bladder.0009`, que acrescenta o histórico e os campos de controle, preservando os dados existentes.
2. Reinicie **manualmente** o processo Node.js do WhatsApp, como já faz normalmente, para carregar o código atualizado. Confira a conexão. O Bladder verifica a versão do serviço e recusa enviar se ele ainda estiver executando o código antigo.
3. Dê dois cliques em **`INSTALAR_AGENDAMENTO_BLADDER.bat`**, na raiz. Aceite a solicitação do Windows para cadastrar a tarefa. O instalador não inicia o WhatsApp, não altera o `.env`, não aplica migrações e não realiza envio de teste.
4. No administrador, abra **Bladder → Configurações de WhatsApp Bladder**. Confira o número, grupo, horário e dias permitidos. O envio automático utiliza o primeiro cadastro; novos cadastros adicionais ficam bloqueados na interface.

O instalador verifica o caminho de produção, o `.venv`, a configuração de produção (`DEBUG=False`, `WHATSAPP_DRY_RUN=False`) e a ausência de migrações pendentes. Ele pode ser executado novamente para atualizar a mesma tarefa, sem criar cópias. Não pode ser instalado por engano na pasta de desenvolvimento.

## Testar pelo administrador

Clique em **Salvar e enviar teste ao número individual**. A configuração será salva antes do envio. O teste utiliza o número individual, mesmo se houver um grupo selecionado, e inclui os dados reais do estoque com um cabeçalho identificando o teste. Informe `55 + DDD + número`, somente dígitos.

O teste é explícito: funciona fora do horário/dia do automático e com o automático desabilitado, inclusive no desenvolvimento. `WHATSAPP_DRY_RUN=True` impede também o teste real. Não há envio ao simplesmente abrir a tela.

Depois de alguns segundos, clique em **Salvar e atualizar status dos envios**. Consulte também o histórico completo em **Histórico de envios WhatsApp Bladder**. Os registros são somente leitura e identificam quem solicitou o teste.

- **Na fila:** o serviço aceitou a solicitação e aguarda a fila compartilhada.
- **Enviado ao WhatsApp:** o serviço confirmou a transmissão pelo Baileys; não confirma entrega nem leitura pelo destinatário.
- **Falha:** consulte o detalhe. Se a solicitação foi recusada antes de entrar na fila, o automático pode tentar novamente.
- **Resultado incerto:** pode ter havido transmissão. Confira o WhatsApp; o sistema não repete automaticamente.

## Regras para reduzir disparos repetidos

- Um resumo automático por configuração e data, com uma chave persistida antes de chamar o serviço e controle de concorrência no banco.
- Até três testes por dia e intervalo mínimo de dez minutos entre tentativas do Bladder. Testes sem transmissão também contam no limite do administrador.
- No serviço compartilhado, limite adicional para **todo o Bladder**: quatro mensagens aceitas por dia, separadas por pelo menos dez minutos. A contagem do serviço utiliza o fuso de Fortaleza.
- A fila, o intervalo de dois a cinco segundos, o limite compartilhado de cinco requisições por minuto e a proteção contra falhas dos outros módulos continuam ativos. Seus formatos de solicitação e resposta de envio foram preservados.
- Nenhum reenvio automático após aceitação na fila, falha durante a transmissão ou resultado incerto. Rejeições anteriores à fila têm no máximo três tentativas de transmissão, com intervalo de quinze minutos.
- Se o WhatsApp estiver desligado, o sistema apenas verifica a disponibilidade a cada quinze minutos dentro da janela de quatro horas após o horário configurado. Essas verificações não consomem tentativas de transmissão.

Essas medidas reduzem volume e duplicações; não garantem que o WhatsApp nunca restrinja o número. Use destinatários que esperam receber os relatórios.

## Operação

A tarefa **Painel Manutencao - WhatsApp Bladder** verifica o sistema a cada minuto, com a conta local SYSTEM, mesmo sem usuário conectado. Ela não inicia o Node.js. O horário é interpretado no `TIME_ZONE` do Django. Exemplo: 07:30 permite tentativas até antes de 11:30, somente nos dias configurados. A atualização dos status também ocorre pela tarefa.

Registros operacionais: `logs\whatsapp_bladder_YYYY-MM-DD.log`. Instalação: `logs\instalacao_agendamento_bladder.log`. A fila e o acompanhamento no Node ficam em memória por até 48 horas; após um reinício, registros sem confirmação ficam incertos no Django e não são reenviados.

Para suspender apenas o automático, desmarque **Envio Automático Habilitado**. Para desligar a tarefa por completo, desabilite-a no Agendador de Tarefas do Windows. Os outros módulos de WhatsApp não dependem dessa tarefa.

## Validação sem enviar mensagens reais

```powershell
.\.venv\Scripts\python.exe manage.py test bladder.test_whatsapp --noinput
cd whatsapp_service
npm test
```

Os testes Python simulam o transporte; os testes Node iniciam um processo isolado com socket simulado e porta temporária. `manage.py enviar_resumo_estoque_bladder --preview` mostra o texto; `--dry-run` simula sem HTTP nem gravação de histórico.

Ensaio opcional com Edge e Playwright já disponíveis no desenvolvimento: `.\.venv\Scripts\python.exe scripts\validar_whatsapp_bladder.py`. Usa banco temporário, simula o transporte e salva uma captura em `logs\whatsapp_bladder\admin-envio-confirmado.png`.

Validação em 13/11/2026: 39 testes Python aprovados (37 do Bladder e dois de regressão da Manutenção), cinco testes Node aprovados e ensaio no navegador aprovado, incluindo `/management/` e `/dashboard/`. A execução ampliada inicial teve 245 testes, com 228 aprovados e 17 falhas preexistentes; as mesmas 17 foram reproduzidas carregando os fontes anteriores de `HEAD` somente em memória. As falhas estão em telas/perfis operacionais do Bladder e no redirecionamento do líder de Produção. Evidências em `logs/whatsapp_bladder_validacao.log` e `logs/whatsapp_bladder_baseline.log`.

A migração local foi aplicada após backup em `backups/db_pre_whatsapp_bladder_20261113_100619.sqlite3`. Nenhuma tarefa foi instalada no PC local e nenhum envio real foi executado. Publicação e teste real permanecem para o servidor.
