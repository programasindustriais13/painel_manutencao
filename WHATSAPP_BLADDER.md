# WhatsApp Bladder — instalação e uso

## Publicar no servidor

1. Na pasta `C:\03_PYTHON\11_Painel Manutencao\painel_manutencao`, faça o deploy habitual (`git pull` e `scripts\deploy_production.ps1`). Ele aplica as migrações `bladder.0009` e `bladder.0010`, que acrescentam o histórico, os controles e o acompanhamento de confirmações, preservando os dados existentes.
2. Reinicie **manualmente** o processo Node.js do WhatsApp, como já faz normalmente, para carregar o código atualizado. Confira a conexão. O Bladder verifica a versão do serviço e recusa enviar se ele ainda estiver executando o código antigo.
3. Dê dois cliques em **`INSTALAR_AGENDAMENTO_BLADDER.bat`**, na raiz. Aceite a solicitação do Windows para cadastrar a tarefa. O instalador não inicia o WhatsApp, não altera o `.env`, não aplica migrações e não realiza envio de teste.
4. No administrador, abra **Bladder → Configurações de WhatsApp Bladder**. Confira o número, grupo, horário e dias permitidos. O envio automático utiliza o primeiro cadastro; novos cadastros adicionais ficam bloqueados na interface.

O instalador verifica o caminho de produção, o `.venv`, a configuração de produção (`DEBUG=False`, `WHATSAPP_DRY_RUN=False`) e a ausência de migrações pendentes. Ele pode ser executado novamente para atualizar a mesma tarefa, sem criar cópias. Não pode ser instalado por engano na pasta de desenvolvimento.

Se a tarefa já foi instalada, não é necessário reinstalá-la para a correção das confirmações: basta publicar, aplicar as migrações pelo deploy e reiniciar o Node manualmente.

## Testar pelo administrador

Clique em **Salvar e enviar teste ao número individual**. A configuração será salva antes do envio. O teste utiliza o número individual, mesmo se houver um grupo selecionado, e inclui os dados reais do estoque com um cabeçalho identificando o teste. Informe `55 + DDD + número`, somente dígitos.

O teste é explícito: funciona fora do horário/dia do automático e com o automático desabilitado, inclusive no desenvolvimento. `WHATSAPP_DRY_RUN=True` impede também o teste real. Não há envio ao simplesmente abrir a tela.

Depois de alguns segundos, clique em **Salvar e atualizar status dos envios**. Consulte também o histórico completo em **Histórico de envios WhatsApp Bladder**. Os registros são somente leitura e identificam quem solicitou o teste.

- **Na fila:** o serviço aceitou a solicitação e aguarda a fila compartilhada.
- **Aguardando confirmação:** `sendMessage()` retornou, mas ainda não há confirmação do WhatsApp. Isso não comprova envio.
- **Aceito pelo servidor WhatsApp:** um ACK do protocolo confirmou aceitação. A entrega ainda não foi comprovada.
- **Entrega confirmada:** houve confirmação de recebimento no dispositivo do destinatário.
- **Leitura confirmada:** houve confirmação de leitura. Depende das confirmações disponíveis na conta do destinatário.
- **Falha:** consulte o detalhe. Se a solicitação foi recusada antes de entrar na fila, o automático pode tentar novamente.
- **Resultado incerto:** pode ter havido transmissão. Confira o WhatsApp; o sistema não repete automaticamente.
- **Aceito pelo serviço anterior:** registro legado, sem comprovação de aceitação pelo WhatsApp. A migração conserva o histórico e a proteção contra repetição.

Nos grupos, entrega ou leitura significam confirmação de **pelo menos um participante**, conforme o detalhe; não afirmam recebimento por todo o grupo. O histórico também guarda o ID da mensagem no WhatsApp e o endereço de destino confirmado pelo serviço.

## Regras para reduzir disparos repetidos

- Um resumo automático por configuração e data, com uma chave persistida antes de chamar o serviço e controle de concorrência no banco.
- Testes manuais sem limite diário, com intervalo mínimo de dez minutos entre tentativas do Bladder.
- O serviço WhatsApp também mantém o intervalo de dez minutos, sem o antigo teto de quatro mensagens diárias. O automático continua limitado a um resumo por configuração e data.
- A fila, o intervalo de dois a cinco segundos, o limite compartilhado de cinco requisições por minuto e a proteção contra falhas dos outros módulos continuam ativos. Seus formatos de solicitação e resposta de envio foram preservados.
- Nenhum reenvio automático após aceitação na fila, falha durante a transmissão ou resultado incerto. Rejeições anteriores à fila têm no máximo três tentativas de transmissão, com intervalo de quinze minutos.
- Se o WhatsApp estiver desligado, o sistema apenas verifica a disponibilidade a cada quinze minutos dentro da janela de quatro horas após o horário configurado. Essas verificações não consomem tentativas de transmissão.
- Antes de transmitir a um número individual, o Bladder consulta `onWhatsApp()` uma única vez e utiliza o endereço confirmado pela resposta. Se o contato não for confirmado, registra falha sem enviar. Não tenta combinações com ou sem o nono dígito.

Essas medidas reduzem volume e duplicações; não garantem que o WhatsApp nunca restrinja o número. Use destinatários que esperam receber os relatórios.

## Operação

A tarefa **Painel Manutencao - WhatsApp Bladder** verifica o sistema a cada minuto, com a conta local SYSTEM, mesmo sem usuário conectado. Ela não inicia o Node.js. O horário é interpretado no `TIME_ZONE` do Django. Exemplo: 07:30 permite tentativas até antes de 11:30, somente nos dias configurados. A atualização dos status também ocorre pela tarefa.

Registros operacionais: `logs\whatsapp_bladder_YYYY-MM-DD.log`. Instalação: `logs\instalacao_agendamento_bladder.log`. A fila e o acompanhamento no Node ficam em memória por até 48 horas; após um reinício, registros sem confirmação ficam incertos no Django e não são reenviados.

Para suspender apenas o automático, desmarque **Envio Automático Habilitado**. Para desligar a tarefa por completo, desabilite-a no Agendador de Tarefas do Windows. Os outros módulos de WhatsApp não dependem dessa tarefa.

Uma queda `428 / Connection Closed` é perda de conexão, não comprovação de bloqueio. O serviço tenta reconectar, evita timers concorrentes e ignora eventos de sockets anteriores. Falhas de inicialização são tratadas sem apagar a sessão. A consulta de disponibilidade libera a proteção contra falhas após o intervalo, mesmo se não houver novo POST de outros módulos.

`MessageCounterError` em `status@broadcast` refere-se à recepção de atualizações de Status. O serviço ignora essas atualizações pessoais, que não são utilizadas pelo painel. Mensagens diretas, grupos e confirmações continuam sendo processados. Não é necessário apagar `auth_info_baileys` para esse diagnóstico.

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

Correção posterior em 13/11/2026: 46 testes Python (45 do Bladder e regressão do envio da Manutenção), 15 testes Node e ensaio Edge aprovados. Inclui retorno sem ACK, contato não confirmado, confirmação anterior ao retorno, entrega/leitura, preservação de registros legados e proteção contra regressão de status. Evidências em `logs/whatsapp_bladder_ack_testes.log` e `logs/whatsapp_bladder_ack_navegador.log`. A entrega real ao número de produção precisa ser conferida após atualizar e reiniciar o serviço no servidor.

Referências do protocolo: [resolução de contatos e consulta de identidade](https://github.com/WhiskeySockets/Baileys/blob/master/src/Signal/lid-mapping.ts), [eventos de confirmação e falhas de mensagens](https://github.com/WhiskeySockets/Baileys/blob/master/src/Socket/messages-recv.ts). O retorno isolado de `sendMessage()` não foi tratado como recibo de entrega.

Atualização de 13/11/2026 para validação manual: removidos os tetos diários de três testes no Django e quatro mensagens no Node. Reinicie o Node manualmente após atualizar para que o processo em execução também deixe de usar o teto antigo. Os intervalos, confirmações reais e bloqueios de duplicação permanecem. Validação: 46 testes Python, 15 testes Node e seis testes isolados do lançador de deploy aprovados, sem transmissão real ou deploy local.
