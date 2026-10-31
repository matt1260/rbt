import json
from unittest import mock

from django.contrib.auth.models import User
from django.core import signing
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import Client, RequestFactory, SimpleTestCase, TestCase, override_settings
from django.core.cache import caches

from hebrewtool.human_verification import human_challenge, human_verify
from hebrewtool.middleware import HUMAN_COOKIE_SALT, RateLimitMiddleware, client_ip
from search import aeon_service, translation_worker
from search.db_utils import INTERLINEAR_CACHE_VERSION
from search.models import TranslationJob
from search.views import chapter_views_part1, translation_views
from search.views.chapter_handlers import _usable_translation
from search.views.storehouse_views import INTERLINEAR_CACHE_VERSION as STOREHOUSE_VERSION
from translate import views as translate_views

LOCMEM = {'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'security-tests'}}


class AeonAccessTests(TestCase):
    def test_anonymous_cannot_reach_aeon(self):
        client = Client()
        for path in ('/api/aeon/ingest/', '/api/aeon/ingest-wordpress/', '/api/aeon/query/'):
            response = client.post(path, data='{}', content_type='application/json')
            self.assertEqual(response.status_code, 403, path)
        self.assertEqual(client.get('/api/aeon/status/').status_code, 403)

    def test_non_rbt_urls_are_never_fetched(self):
        with mock.patch.object(aeon_service.urllib.request, 'urlopen') as urlopen:
            for url in ('file:///etc/passwd', 'http://realbible.tech/x', 'https://169.254.169.254/x',
                        'https://realbible.tech.evil.example/x'):
                self.assertIsNone(aeon_service._fetch_wordpress_post_from_web(url), url)
        urlopen.assert_not_called()

    def test_query_top_k_is_capped_and_bad_values_rejected(self):
        client = Client()
        client.force_login(User.objects.create_user('staff', password='x', is_staff=True))
        with mock.patch('search.views.aeon_views.query_aeon', return_value={}) as query:
            client.post('/api/aeon/query/', json.dumps({'question': 'q', 'top_k': 100000}),
                        content_type='application/json')
        self.assertEqual(query.call_args.kwargs['top_k'], 20)
        response = client.post('/api/aeon/query/', json.dumps({'question': 'q', 'top_k': 'x'}),
                               content_type='application/json')
        self.assertEqual(response.status_code, 400)


class HumanChallengeTests(SimpleTestCase):
    def test_challenge_drops_unsafe_next(self):
        factory = RequestFactory()
        for bad in ('javascript:alert(1)', 'https://evil.example/', '//evil.example/'):
            html = human_challenge(factory.get('/__human_challenge/', {'next': bad})).content.decode()
            self.assertNotIn('javascript%3A', html)
            self.assertNotIn('evil.example', html)
            self.assertIn("decodeURIComponent('%2F')", html)

    def test_challenge_keeps_a_relative_next(self):
        html = human_challenge(RequestFactory().get('/__human_challenge/', {'next': '/John/3/'})).content.decode()
        self.assertIn('%2FJohn%2F3%2F', html)


@override_settings(CACHES=LOCMEM, DEBUG=False)
class RateLimitTests(SimpleTestCase):
    def setUp(self):
        from django.core.cache import cache
        cache.clear()
        self.factory = RequestFactory()
        self.middleware = RateLimitMiddleware(lambda request: HttpResponse('ok'))

    def verified_cookie(self, ip):
        request = self.factory.post('/__human_verify/', REMOTE_ADDR=ip)
        return human_verify(request).cookies['human_verified'].value

    def test_client_ip_ignores_junk_forwarded_values(self):
        request = self.factory.get('/', HTTP_X_FORWARDED_FOR='<script>', REMOTE_ADDR='10.0.0.1')
        self.assertEqual(client_ip(request), '10.0.0.1')
        request = self.factory.get('/', HTTP_X_FORWARDED_FOR='8.8.8.8, 10.0.0.2', REMOTE_ADDR='10.0.0.1')
        self.assertEqual(client_ip(request), '8.8.8.8')

    def test_depth_counts_proxy_entries_from_the_right(self):
        # Attacker-supplied entries on the left; what our proxies appended on the right.
        request = self.factory.get('/', HTTP_X_FORWARDED_FOR='1.1.1.1, junk, 2.2.2.2, 8.8.8.8, 35.191.0.9',
                                   REMOTE_ADDR='10.0.0.1')
        with override_settings(TRUSTED_PROXY_DEPTH=1):
            self.assertEqual(client_ip(request), '35.191.0.9')
        with override_settings(TRUSTED_PROXY_DEPTH=2):
            self.assertEqual(client_ip(request), '8.8.8.8')
        with override_settings(TRUSTED_PROXY_DEPTH=0):
            self.assertEqual(client_ip(request), '1.1.1.1')

    def test_depth_falls_back_when_the_header_is_too_short(self):
        request = self.factory.get('/', HTTP_X_FORWARDED_FOR='8.8.8.8', REMOTE_ADDR='10.0.0.1')
        with override_settings(TRUSTED_PROXY_DEPTH=2):
            self.assertEqual(client_ip(request), '10.0.0.1')
        request = self.factory.get('/', REMOTE_ADDR='10.0.0.1')
        with override_settings(TRUSTED_PROXY_DEPTH=1):
            self.assertEqual(client_ip(request), '10.0.0.1')

    def test_with_depth_a_rotating_header_still_hits_one_bucket(self):
        with override_settings(TRUSTED_PROXY_DEPTH=1):
            for i in range(21):
                response = self.middleware(self.factory.get(
                    '/api/live/', {'q': 'x'}, HTTP_X_FORWARDED_FOR=f'10.{i}.{i}.{i}, 8.8.8.8', REMOTE_ADDR='10.0.0.1'))
        self.assertNotEqual(response.status_code, 200)

    @override_settings(CACHES={**LOCMEM, 'ratelimit': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache', 'LOCATION': 'security-tests-counters'}})
    def test_counters_stay_out_of_the_shared_cache_but_strikes_do_not(self):
        caches['ratelimit'].clear()
        for _ in range(21):
            self.middleware(self.factory.get('/api/live/', {'q': 'x'}, REMOTE_ADDR='1.2.3.4'))
        # The request that exceeds the limit is answered before its count is stored
        self.assertEqual(caches['ratelimit'].get('ratelimit:api:1.2.3.4')['count'], 20)
        self.assertIsNone(caches['default'].get('ratelimit:api:1.2.3.4'))
        self.assertEqual(caches['default'].get('strikes:api:1.2.3.4'), 1)

    def test_verified_cookie_does_not_lift_a_ban(self):
        import time
        from django.core.cache import cache
        cache.set('banned:1.2.3.4', {'until': time.time() + 60, 'reason': 'test'}, 60)
        request = self.factory.get('/John/3/', REMOTE_ADDR='1.2.3.4')
        request.COOKIES['human_verified'] = self.verified_cookie('1.2.3.4')
        self.assertEqual(self.middleware(request).status_code, 403)

    def test_cookie_only_counts_from_the_ip_it_was_issued_to(self):
        request = self.factory.get('/', REMOTE_ADDR='1.2.3.4')
        cookie = self.verified_cookie('1.2.3.4')
        request.COOKIES['human_verified'] = cookie
        self.assertTrue(self.middleware.has_human_cookie(request, '1.2.3.4'))
        self.assertFalse(self.middleware.has_human_cookie(request, '5.6.7.8'))

    def test_cookies_signed_without_the_salt_are_refused(self):
        request = self.factory.get('/', REMOTE_ADDR='1.2.3.4')
        request.COOKIES['human_verified'] = signing.dumps({'ts': 1, 'ip': '1.2.3.4'})
        self.assertFalse(self.middleware.has_human_cookie(request, '1.2.3.4'))
        self.assertEqual(HUMAN_COOKIE_SALT, 'hebrewtool.human_verified')

    def test_verified_cookie_stretches_but_does_not_remove_the_limit(self):
        cookie = self.verified_cookie('1.2.3.4')
        statuses = []
        for _ in range(120 * 5 + 1):
            request = self.factory.get('/about/', REMOTE_ADDR='1.2.3.4')
            request.COOKIES['human_verified'] = cookie
            statuses.append(self.middleware(request).status_code)
        self.assertEqual(statuses[-2], 200)
        self.assertNotEqual(statuses[-1], 200)

    def test_password_attempts_have_their_own_tight_limit(self):
        cookie = self.verified_cookie('1.2.3.4')
        statuses = []
        for _ in range(11):
            # Query params and the cookie must not move a login into a looser bucket
            request = self.factory.post('/accounts/login/?verse=1&chapter=1', REMOTE_ADDR='1.2.3.4')
            request.COOKIES['human_verified'] = cookie
            statuses.append(self.middleware(request).status_code)
        self.assertEqual(statuses[:10], [200] * 10)
        self.assertNotEqual(statuses[10], 200)

    def test_public_translation_routes_are_rate_limited_but_status_polls_are_not(self):
        for _ in range(61):
            response = self.middleware(self.factory.get(
                '/api/translation/start/', {'book': 'John', 'chapter': 1, 'lang': 'es'}, REMOTE_ADDR='1.2.3.4'))
        self.assertNotEqual(response.status_code, 200)
        for _ in range(200):
            response = self.middleware(self.factory.get('/api/translation/status/', REMOTE_ADDR='9.9.9.9'))
        self.assertEqual(response.status_code, 200)


class TranslationRouteTests(TestCase):
    def test_translation_routes_reject_unknown_books_and_chapters(self):
        client = Client()
        with mock.patch('search.views.translation_views.invalidate_cached_render') as invalidate:
            for route in ('start', 'clear-cache', 'retry-failed'):
                for book, chapter in (('<img src=x onerror=alert(1)>', 1), ('John', 9999), ('Gospel of Judas', 61)):
                    response = client.get(f'/api/translation/{route}/',
                                          {'book': book, 'chapter': chapter, 'lang': 'es'})
                    self.assertEqual(response.json()['status'], 'error', (route, book))
        invalidate.assert_not_called()
        self.assertFalse(TranslationJob.objects.exists())

    def test_clear_cache_rejects_made_up_languages(self):
        with mock.patch('search.views.translation_views.invalidate_cached_render') as invalidate:
            response = Client().get('/api/translation/clear-cache/', {'book': 'John', 'chapter': 1, 'lang': 'zz1'})
        self.assertEqual(response.json()['status'], 'error')
        invalidate.assert_not_called()

    def test_synchronous_translate_route_is_staff_only(self):
        response = Client().get('/api/translate_chapter/', {'book': 'John', 'chapter': 1, 'lang': 'es'})
        self.assertEqual(response.status_code, 403)

    def test_clean_failed_refuses_get(self):
        client = Client()
        client.force_login(User.objects.create_user('editor', password='x'))
        response = client.get('/api/translation/clean-failed/', {'scope': 'nt', 'lang': 'all'})
        self.assertEqual(response.status_code, 405)

    def test_prompt_config_and_titles_need_a_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(User.objects.create_user('editor', password='x'))
        for path in ('/api/translation/prompt-config/', '/api/translation/titles/', '/api/translation/clean-failed/'):
            self.assertEqual(client.post(path, data='{}', content_type='application/json').status_code, 403, path)

    def test_stats_route_needs_a_login(self):
        self.assertEqual(Client().get('/api/translation/stats/', {'book': 'John', 'chapter': 1}).status_code, 403)


class WorkerTests(TestCase):
    def test_full_queue_refuses_new_jobs(self):
        with mock.patch.object(translation_worker, 'MAX_PENDING_JOBS', 0), \
                mock.patch.object(translation_worker, 'ensure_worker_running'):
            with self.assertRaises(translation_worker.TranslationQueueFull):
                translation_worker.create_translation_job('John', 1, 'es')

    def test_existing_job_revives_a_dead_worker(self):
        job = TranslationJob.objects.create(job_id='a', book='John', chapter=1, language_code='es', status='pending')
        with mock.patch.object(translation_worker, 'ensure_worker_running') as ensure:
            self.assertEqual(translation_worker.create_translation_job('John', 1, 'es').job_id, job.job_id)
        ensure.assert_called_once()

    def test_quota_sentinel_fails_the_job_instead_of_saving_a_junk_row(self):
        from search.models import VerseTranslation
        job = TranslationJob.objects.create(job_id='b', book='John', chapter=1, language_code='es', status='processing')
        worker = translation_worker.get_worker()
        with mock.patch('search.translation_utils.translate_footnotes_batch',
                        return_value={'__quota_exceeded__': True}):
            with self.assertRaises(Exception):
                worker._translate_footnotes(job, {'Joh-1': 'text'}, 'John', 1, 'es')
        self.assertFalse(VerseTranslation.objects.filter(footnote_id='__quota_exceeded__').exists())


class RenderingTests(SimpleTestCase):
    def test_stored_failures_are_not_usable(self):
        self.assertFalse(_usable_translation('[Translation error: 500]'))
        self.assertFalse(_usable_translation('[Translation parsing error]'))
        self.assertFalse(_usable_translation(''))
        self.assertFalse(_usable_translation(None))
        self.assertTrue(_usable_translation('En el principio'))

    def test_one_cache_version_everywhere(self):
        self.assertEqual(chapter_views_part1.INTERLINEAR_CACHE_VERSION, INTERLINEAR_CACHE_VERSION)
        self.assertEqual(translation_views.INTERLINEAR_CACHE_VERSION, INTERLINEAR_CACHE_VERSION)
        self.assertEqual(STOREHOUSE_VERSION, INTERLINEAR_CACHE_VERSION)
        self.assertEqual(translation_views.get_cache_key('1 John', 2, None, 'es'), f'1John_2_None_es_{INTERLINEAR_CACHE_VERSION}')

    def test_search_page_cannot_be_broken_out_of_by_scope(self):
        html = render_to_string('search_results_full.html', {
            'query': 'de', 'scope': '"><img src=x onerror=alert(1)>', 'search_type': '";alert(1);//', 'page': 1,
        })
        self.assertNotIn('const scope = "&quot;', html)
        self.assertIn('const scope = "\\u0022', html)
        self.assertIn('const searchType = "\\u0022', html)
        self.assertNotIn('&scope=${scope}', html)

    def test_hardcoded_openai_key_stays_gone(self):
        with open(translate_views.__file__, encoding='utf-8') as source:
            self.assertNotIn('Bearer sk-', source.read())


class LexiconScrapeTests(TestCase):
    def test_scrape_refuses_other_hosts(self):
        client = Client()
        client.force_login(User.objects.create_user('editor', password='x'))
        with mock.patch('translate.views.requests.get') as get:
            for url in ('http://169.254.169.254/latest/meta-data/', 'file:///etc/passwd',
                        'https://biblehub.com.evil.example/x'):
                self.assertEqual(client.get('/translate/api/scrape-lexicon/', {'url': url}).status_code, 400, url)
        get.assert_not_called()


class NorthflankStatsTests(TestCase):
    def test_closed_without_a_configured_token(self):
        with mock.patch.dict('os.environ', {'NORTHFLANK_STATS_TOKEN': ''}):
            self.assertEqual(Client().get('/api/northflank/stats/').status_code, 401)

    def test_wrong_token_refused(self):
        with mock.patch.dict('os.environ', {'NORTHFLANK_STATS_TOKEN': 'right'}):
            response = Client().get('/api/northflank/stats/', headers={'X-Stats-Token': 'wrong'})
        self.assertEqual(response.status_code, 401)
