import sys
import copy
import pymysql

pymysql.install_as_MySQLdb()

# Python 3.14 compatibility patch for Django BaseContext.__copy__
if sys.version_info >= (3, 14):
    import django.template.context
    def _base_context_copy(self):
        duplicate = self.__class__.__new__(self.__class__)
        duplicate.dicts = self.dicts[:]
        return duplicate

    def _context_copy(self):
        duplicate = self.__class__.__new__(self.__class__)
        duplicate.dicts = self.dicts[:]
        if hasattr(self, 'render_context'):
            duplicate.render_context = copy.copy(self.render_context)
        return duplicate

    django.template.context.BaseContext.__copy__ = _base_context_copy
    django.template.context.Context.__copy__ = _context_copy

