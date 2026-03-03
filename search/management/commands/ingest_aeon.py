from django.core.management.base import BaseCommand, CommandError

from search.aeon_service import DEFAULT_CONVERSATION_TITLE, DEFAULT_SOURCE_FILE, ingest_conversation_title


class Command(BaseCommand):
    help = 'Ingest Aeon corpus from a conversation title in conversations.json'

    def add_arguments(self, parser):
        parser.add_argument('--title', type=str, default=DEFAULT_CONVERSATION_TITLE, help='Conversation title to ingest')
        parser.add_argument('--source-file', type=str, default=DEFAULT_SOURCE_FILE, help='Path to conversations JSON file')

    def handle(self, *args, **options):
        title = options['title']
        source_file = options['source_file']

        self.stdout.write(f'Ingesting Aeon corpus from title: {title}')
        self.stdout.write(f'Source file: {source_file}')

        try:
            result = ingest_conversation_title(title=title, source_file=source_file)
        except Exception as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(self.style.SUCCESS('Aeon ingestion completed'))
        self.stdout.write(str(result))
