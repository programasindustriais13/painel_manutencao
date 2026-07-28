# 🧠 SPEC — MÍDIA PROTEGIDA E ALINHAMENTO DE RUNTIME DJANGO 4.2.30

---

## 📌 1. CONTEXTO

- **Ambiente:** Servidor de produção em Windows Server 2019 executando Python 3.11.6 e Django 4.2.30 (desenvolvimento local em Windows com Python 3.11.3).
- **URLs envolvidas:**
  - `/anexos/alocacoes/<int:allocation_id>/` (Nova rota protegida por autenticação e autorização).
  - `/media/...` (Permanecerá fechada/retornando HTTP 404 em produção com `DEBUG=False`).
- **Arquitetura de Produção:**
  ```text
  Cloudflare Tunnel -> Waitress 127.0.0.1:8900
                           ├── Django WSGI
                           ├── WhiteNoise (somente para /static/)
                           └── View Autenticada (para anexos privados de alocações)
  ```
- **Contextos afetados:** Controle de Técnicos, Histórico de Atendimentos, Anexos Internos de Fábrica.
- **Perfis afetados:** Operador/Administrador, Técnico Líder, Técnico Comum, Usuário de Produção (bloqueado), Anônimos (bloqueado).

---

## ❗ 2. PROBLEMA ATUAL

1. O modelo `Allocation` possui o campo de upload `foto_anexo = models.ImageField(upload_to="alocacoes/", null=True, blank=True)`.
2. Em produção com `DEBUG=False`, a URL `/media/` retorna HTTP 404. Os arquivos de mídia guardados em `MEDIA_ROOT` são registros internos de fábrica e não podem ser servidos de forma anônima ou pública.
3. Atualmente não existe uma rota protegida por autenticação/autorização para servir de forma segura esses anexos a usuários autenticados e autorizados.
4. O `requirements.txt` local define `Django>=4.2.0,<5.0`, enquanto a auditoria do servidor confirmou o uso do `Django 4.2.30`.
5. O manual de implantação `DEPLOY_WINDOWS_SERVER.md` continha menções e bloqueios pendentes relativos ao IIS/ARR para mídias, incompatíveis com a decisão arquitetural atual (Waitress + View Autenticada Django + WhiteNoise estático).

---

## 🎯 3. OBJETIVO

1. **Servir Anexos de Forma Protegida:** Criar a view `serve_allocation_attachment` protegida por login e regras de autorização do sistema, acessível pela rota `/anexos/alocacoes/<int:allocation_id>/`.
2. **Segurança de Acesso:** Impedir acesso anônimo; restringir acesso conforme o perfil e relação do usuário com a alocação; impedir path traversal ao identificar o arquivo unicamente pelo ID do banco (ORM).
3. **Resiliência e Tratamento de Erros:** Retornar HTTP 404 limpo para IDs inexistentes, alocações sem foto ou arquivos fisicamente ausentes no armazenamento (sem erros 500).
4. **Cabeçalhos de Segurança:** Configurar `Content-Type` seguro, `Content-Disposition`, `Cache-Control: private, no-store` e `X-Content-Type-Options: nosniff`.
5. **Preservação do Fechamento de `/media/`:** Manter a URL `/media/` inacessível (HTTP 404) quando `DEBUG=False` em produção.
6. **Alinhamento do Runtime:** Atualizar o `requirements.txt` para `Django==4.2.30` e instalar a versão exata no `.venv`.
7. **Atualização do Manual de Implantação:** Atualizar `DEPLOY_WINDOWS_SERVER.md` eliminando dependência do IIS/ARR e documentando a arquitetura simplificada `Cloudflare Tunnel -> Waitress 127.0.0.1:8900`.
8. **Validação Completa (QA):** Adicionar suíte de testes robusta cobrindo 100% dos cenários de autorização, mídia e segurança.

---

## 🧩 4. ESCOPO DA ALTERAÇÃO

### Possíveis arquivos a alterar:
- `requirements.txt` (fixar `Django==4.2.30`)
- `maintenance/views.py` (implementar `serve_allocation_attachment`)
- `maintenance/urls.py` (registrar rota `/anexos/alocacoes/<int:allocation_id>/`)
- `maintenance/tests.py` (adicionar suíte de testes da mídia protegida e segurança)
- `DEPLOY_WINDOWS_SERVER.md` (atualizar arquitetura e remover dependência IIS/ARR)
- `Instrucoes.txt` (registrar as alterações efetuadas)

---

## 🚫 5. FORA DE ESCOPO

- Não criar novo projeto ou app.
- Não criar outro `.venv`.
- Não instalar IIS, URL Rewrite ou ARR.
- Não configurar Cloudflare Tunnel remotamente ou alterar o servidor.
- Não alterar modelos em `models.py`.
- Não criar migrations nem executar `migrate`.
- Não mover ou apagar a pasta de mídia `media/`.
- Não expor `MEDIA_ROOT` via WhiteNoise ou `django.views.static.serve` em produção.
- Não aceitar caminhos de arquivos arbitrários ou strings fornecidas pela URL (`/media/<caminho>`).
- Não atualizar o Django para linha major 5 ou 6.
- Não executar `git commit` ou `git push`.
- Não alterar regras do banco SCADA ou do app de Produção.

---

## 🔐 6. REGRAS OBRIGATÓRIAS DE AUTORIZAÇÃO

### Mapeamento de Autorização por Perfil:
1. **Usuário não autenticado:** Redirecionamento para login (`/login/?next=...`).
2. **Técnico comum (`TECNICO`):** Pode acessar o anexo APENAS se for o técnico vinculado à alocação (`allocation.tecnico == _get_technician_proprio(user)`). Caso contrário, retorna HTTP 403 (Acesso Negado).
3. **Técnico Líder (`TECNICO_LIDER`):** Pode acessar anexos de qualquer alocação de manutenção legítima (possui permissão de monitorar e gerenciar alocações).
4. **Operador / Administrador (`OPERADOR`, superuser, staff, grupo Operadores):** Acesso total aos anexos das alocações.
5. **Usuário de Produção (grupo 'Liderança de Produção' sem perfil de manutenção):** Bloqueado com HTTP 403.
6. **Alocação Inexistente:** HTTP 404.
7. **Alocação sem foto (`foto_anexo` nulo/vazio):** HTTP 404.
8. **Arquivo ausente no armazenamento em disco:** HTTP 404 limpo (tratamento de `FileNotFoundError` / check `storage.exists()`), evitando HTTP 500.

---

## 🛠️ 7. ROTA E IMPLEMENTAÇÃO DA VIEW PROTEGIDA

### Rota:
```python
path('anexos/alocacoes/<int:allocation_id>/', views.serve_allocation_attachment, name='serve_allocation_attachment')
```

### Comportamento da View:
1. Recebe `allocation_id` (inteiro).
2. Executa `get_object_or_404(Allocation, id=allocation_id)`.
3. Valida permissões do usuário logado conforme as regras da Seção 6.
4. Verifica se `allocation.foto_anexo` possui arquivo associado (`bool(allocation.foto_anexo)`).
5. Valida a existência física do arquivo via `storage.exists(allocation.foto_anexo.name)` ou `try/except FileNotFoundError`.
6. Abre o arquivo via `allocation.foto_anexo.open('rb')`.
7. Retorna `FileResponse(file_handle)`.
8. Configura os cabeçalhos HTTP na resposta:
   - `Content-Type`: detectado de forma segura pelo nome/extensão do arquivo (ex: `image/jpeg`, `image/png`).
   - `Content-Disposition`: `inline; filename="alocacao_<id>_<basename>"` (para permitir visualização em navegadores).
   - `Cache-Control`: `private, no-store` (impede cache intermediário/público).
   - `X-Content-Type-Options`: `nosniff` (impede sniffing de MIME type pelo navegador).

---

## 🎨 8. TEMPLATES E AUDITORIA DE USO

### Auditoria de Templates Existentes:
- NENHUM template atual exibe a imagem ou o link `.url` do `foto_anexo`.
- Em `technician_management.html`, existe apenas o input `<input type="file" name="foto_anexo">` no modal de conclusão.
- **Diretriz:** Conforme especificado, não inventar nova galeria ou interface fora do escopo. A rota protegida `{% url 'serve_allocation_attachment' allocation.id %}` é disponibilizada para consumo seguro backend/frontend e pronta para uso futuro.

---

## ⚠️ 9. RISCOS E AUDITORIA DE UPLOAD PENDENTE

### Validação Atual do Upload:
- O `FinishServiceForm` utiliza `FileInput` com `accept="image/*"`.
- O modelo `Allocation` utiliza `ImageField(upload_to='alocacoes/', null=True, blank=True)`.
- O Django/Pillow valida se o arquivo enviado é uma imagem válida no momento da submissão do formulário.

### Lacunas e Riscos Identificados (Para Futuras SPECs):
1. **Limite de Tamanho de Arquivo:** Atualmente não há trava explícita no backend para limitar o tamanho máximo em MB do upload de foto.
2. **Sanitização do Nome do Arquivo:** O upload confia na sanitização padrão do storage do Django, sem renomear o arquivo para UUID/hash.
3. **Verificação de Conteúdo Malicioso / Antivírus:** Não há checagem de steganografia ou malware no upload.
4. **Resolução / Compressão de Imagens:** Fotos enviadas em alta resolução por celulares não são redimensionadas no servidor, podendo ocupar espaço excessivo em disco.

*Estes riscos foram catalogados e devem ser objeto de uma SPEC dedicada de Endurecimento de Uploads.*

---

## 🧪 10. TESTES E CRITÉRIOS DE ACEITAÇÃO

A suíte de testes em `maintenance/tests.py` incluirá o caso de teste `ProtectedMediaTests` cobrindo:
1. Acesso anônimo à rota `/anexos/alocacoes/<id>/` (redireciona para login).
2. Técnico autorizado (técnico dono da alocação) acessa o anexo (HTTP 200).
3. Técnico não autorizado (técnico tentando acessar alocação de outro) recebe HTTP 403.
4. Operador autorizado acessa o anexo de qualquer alocação (HTTP 200).
5. Usuário de produção tenta acessar o anexo e recebe HTTP 403.
6. Objeto inexistente (`allocation_id` inválido) retorna HTTP 404.
7. Alocação sem foto (`foto_anexo` nulo) retorna HTTP 404.
8. Arquivo registrado no banco mas fisicamente ausente no armazenamento em disco retorna HTTP 404 (sem 500).
9. Verificação dos cabeçalhos `Cache-Control: private, no-store` e `X-Content-Type-Options: nosniff`.
10. Verificação de que `/media/...` retorna HTTP 404 em ambiente com `DEBUG=False`.
11. Impossibilidade de Path Traversal (rota só aceita ID inteiro numérico do ORM).
12. Confirmação de que o banco SCADA de teste permanece intocado e isolado.

---

## 🔍 11. PLANO DE IMPLEMENTAÇÃO SEQUENCIAL

1. **Auditoria & Fixação do Django:** Atualizar `requirements.txt` para `Django==4.2.30` e executar `pip install -r requirements.txt`.
2. **Backend (View e Rota):** Implementar `serve_allocation_attachment` em `maintenance/views.py` e registrar a rota `anexos/alocacoes/<int:allocation_id>/` em `maintenance/urls.py`.
3. **Manual de Implantação:** Atualizar `DEPLOY_WINDOWS_SERVER.md` removendo dependência do IIS/ARR para mídias e consolidando a arquitetura Waitress.
4. **Testes Unitários:** Escrever e executar os testes automatizados em `maintenance/tests.py`.
5. **QA & Validação:** Executar `manage.py check`, `makemigrations --check --dry-run`, `test`, `collectstatic`, `check --deploy`, e smoke test local com Waitress e `DEBUG=False`.
6. **Registro:** Atualizar `Instrucoes.txt` com todas as modificações efetuadas.
