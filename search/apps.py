from django.apps import AppConfig
import os


class SearchConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'search'
    
    def ready(self):
        """Start the translation worker when Django starts"""
        # Only start worker in the main process, not in management commands
        # and not during migrations or other special operations
        if os.environ.get('RUN_MAIN') == 'true' or os.environ.get('GUNICORN_WORKER', False):
            # Delay import to avoid circular imports
            from search.translation_worker import ensure_worker_running
            ensure_worker_running()
            print("[APP] Translation worker auto-started")
