class ScadaRouter:
    """
    A router to control all database operations on models in the
    production application, routing them to the 'scada' database
    and preventing migrations from running on the 'scada' database.
    """
    def db_for_read(self, model, **hints):
        if model._meta.app_label == "production":
            return "scada"
        return "default"

    def db_for_write(self, model, **hints):
        if model._meta.app_label == "production":
            return "scada"
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        if obj1._meta.app_label == "production" or obj2._meta.app_label == "production":
            return False
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        # Prevent any migrations from running on the scada database
        if db == "scada":
            return False
        # Do not run production app migrations on any database
        if app_label == "production":
            return False
        return True
