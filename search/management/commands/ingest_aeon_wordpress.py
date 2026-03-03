from django.core.management.base import BaseCommand, CommandError

from search.aeon_service import ingest_wordpress_urls


class Command(BaseCommand):
    help = 'Ingest Aeon corpus documents from WordPress post/page URLs'

    def add_arguments(self, parser):
        parser.add_argument('urls', nargs='+', type=str, help='WordPress URLs to ingest')

    def handle(self, *args, **options):
        urls = options['urls']
        self.stdout.write(f'Ingesting {len(urls)} WordPress URLs into Aeon corpus...')

        try:
            result = ingest_wordpress_urls(urls)
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS('Aeon WordPress ingestion completed'))
        self.stdout.write(str(result))
