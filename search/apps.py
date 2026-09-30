from django.apps import AppConfig
import os


class SearchConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'search'
    
    def ready(self):
        """Start the translation worker when Django starts"""
        # Never let a transaction opened by raw SQL carry over into the next request on
        # a pooled connection (see search.db_utils.end_stray_transaction).
        from django.core.signals import request_finished, request_started
        request_started.connect(_end_stray_transaction, dispatch_uid='search.end_stray_transaction.started')
        request_finished.connect(_end_stray_transaction, dispatch_uid='search.end_stray_transaction.finished')

        # Only start worker in the main process, not in management commands
        # and not during migrations or other special operations
        if os.environ.get('RUN_MAIN') == 'true' or os.environ.get('GUNICORN_WORKER', False):
            # Delay import to avoid circular imports
            from search.translation_worker import ensure_worker_running
            ensure_worker_running()
            print("[APP] Translation worker auto-started")


def _end_stray_transaction(**kwargs):
    from search.db_utils import end_stray_transaction
    end_stray_transaction()
