class ScadaRouter:
    """
    Database router for the production app:
    
    ESTRUTURA DE MODELOS E ROTAS:
    - Modelos locais gerenciados (productionmachineconfig, productioncavityconfig,
      productionglobalparameter, productionglobalalarm):
      Roteiam leitura, escrita e migrações exclusivamente para o banco 'default'.
    - Modelos não gerenciados do Scada-LTS (managed=False):
      Roteiam leitura para o banco 'scada'.
      Tentativas de escrita via ORM são categoricamente BLOQUEADAS com PermissionError.
      Migrações (allow_migrate) são categoricamente BLOQUEADAS em qualquer banco.
      
    AVISO DE SEGURANÇA E ARQUITETURA:
    O ScadaRouter é uma camada de defesa em nível de aplicação (Django ORM).
    A proteção definitiva contra escrita no MySQL do Scada-LTS DEVE utilizar
    credenciais de banco de dados com permissão estrita de apenas SELECT (somente leitura),
    pois chamadas explícitas como Model.objects.using('scada').create(...) ou SQL puro
    podem contornar o roteador de banco do Django.
    """

    LOCAL_MANAGED_MODELS = {
        "productionshift",
        "productionmachineconfig",
        "productioncavityconfig",
        "productionglobalparameter",
        "productionglobalalarm",
        "productionmachinestate",
        "productiondowntimeevent",
        "productioncavitystate",
        "productioncavitydowntimeevent",
        "productioncavitymatrixhistory",
        "productionmachinestateinterval",
        "productionrateaggregate",
        "productionparameterconfig",
        "productionparameteranomalyevent",
        "productioncycle",
        "productionshiftaccumulated",
        "productionmatrixcatalog",
        "productiontarget",
        "productionmatrixsize",
        "productionbladder",
        "productionpcpsetting",
        "productionpcpplan",
        "productionpcpplanshifttarget",
    }

    def db_for_read(self, model, **hints):
        if model._meta.app_label == "production":
            model_name = getattr(model._meta, "model_name", "").lower()
            managed = getattr(model._meta, "managed", True)
            if model_name in self.LOCAL_MANAGED_MODELS or managed:
                return "default"
            return "scada"
        return None

    def db_for_write(self, model, **hints):
        if model._meta.app_label == "production":
            model_name = getattr(model._meta, "model_name", "").lower()
            managed = getattr(model._meta, "managed", True)
            if model_name in self.LOCAL_MANAGED_MODELS or managed:
                return "default"
            raise PermissionError(
                f"Escrita bloqueada: O modelo '{model._meta.label}' do Scada-LTS é somente leitura."
            )
        return None

    def allow_relation(self, obj1, obj2, **hints):
        obj1_unmanaged = not getattr(obj1._meta, "managed", True)
        obj2_unmanaged = not getattr(obj2._meta, "managed", True)
        if obj1_unmanaged or obj2_unmanaged:
            return False

        # Permitir explicitamente o relacionamento local entre maintenance.Machine e ProductionMachineConfig
        app1, model1 = obj1._meta.app_label, obj1._meta.model_name
        app2, model2 = obj2._meta.app_label, obj2._meta.model_name
        if (app1 == "maintenance" and model1 == "machine" and app2 == "production" and model2 == "productionmachineconfig") or \
           (app2 == "maintenance" and model2 == "machine" and app1 == "production" and model1 == "productionmachineconfig"):
            return True

        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Nenhuma migração é permitida no banco 'scada' sob qualquer hipótese
        if db == "scada":
            return False

        if app_label == "production":
            # Tratar caso em que um dicionário de hints é passado como 3º argumento posicional
            if isinstance(model_name, dict):
                hints = {**model_name, **hints}
                model_name = None

            # Desempacotar 'hints' se tiver sido passado como kwarg explícito hints={...}
            if "hints" in hints and isinstance(hints["hints"], dict):
                hints = {**hints["hints"], **hints}

            m_name = ""
            if isinstance(model_name, str):
                m_name = model_name.lower()

            # Se m_name não veio por string explícita, tenta resgatar o modelo de hints
            if not m_name:
                model_obj = hints.get("model")
                if model_obj is not None:
                    m_name = getattr(getattr(model_obj, "_meta", None), "model_name", "").lower()

            if m_name in self.LOCAL_MANAGED_MODELS:
                return db == "default"
            elif m_name:
                # model_name explícito ou resgatado de hint que não pertença aos locais gerenciados
                return False
            else:
                # Migration genérica do app production (ex: RunPython/RunSQL sem modelo específico) roda apenas no default
                return db == "default"

        return None
