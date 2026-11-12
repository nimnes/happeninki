import unittest
from unittest.mock import patch
from urllib.request import Request

from happeninki.config import load_config
from happeninki.http import RemoteError, SafeRedirects
from happeninki.translator import Translator, TranslationUnavailable
from happeninki.classifier import Classifier
from test_translator import Responses, GOOD_JSON
import test_translator


def google_response(text, reason='STOP'):
    return {'candidates': [{'finishReason': reason, 'content': {'parts': [{'text': text}]}}]}


class GoogleProviderTests(unittest.TestCase):
    def setUp(self):
        fixture = test_translator.TranslationTests()
        fixture.setUp()
        self.event = fixture.event
        self.settings = load_config()['llm']

    def test_google_is_default_and_ollama_is_configuration_only(self):
        self.assertEqual(self.settings['provider'], 'google')
        self.assertEqual(self.settings['model'], 'gemini-3.5-flash-lite')
        with patch.dict('os.environ', {'LLM_PROVIDER': 'ollama', 'OLLAMA_MODEL': 'test-model'}):
            settings = load_config()['llm']
        self.assertEqual(settings['provider'], 'ollama')
        self.assertEqual(settings['model'], 'test-model')
        with patch.dict('os.environ', {'LLM_PROVIDER': 'invalid'}):
            with self.assertRaises(ValueError):
                load_config()

    def test_google_translation_preserves_prompt_and_uses_native_format(self):
        http = Responses(google_response(GOOD_JSON))
        result = Translator(http, self.settings, 'fake').translate(self.event, 'ru')
        self.assertEqual(result['summary'], 'Выступит местная группа.')
        self.assertIn('Russian', http.calls[0]['systemInstruction']['parts'][0]['text'])
        self.assertIn('Konsertti', http.calls[0]['contents'][0]['parts'][0]['text'])
        self.assertNotIn('model', http.calls[0])

    def test_truncation_regenerates_with_larger_budget(self):
        http = Responses(google_response(GOOD_JSON, 'MAX_TOKENS'), google_response(GOOD_JSON))
        with self.assertLogs('happeninki.translator'):
            result = Translator(http, self.settings, 'fake').translate(self.event, 'en')
        self.assertTrue(result['title'])
        self.assertEqual(http.calls[1]['generationConfig']['maxOutputTokens'], 1100)
        self.assertGreater(http.calls[1]['generationConfig']['maxOutputTokens'], http.calls[0]['generationConfig']['maxOutputTokens'])

    def test_quota_failure_keeps_events_queued(self):
        http = Responses(RemoteError('google', 429))
        with self.assertRaises(TranslationUnavailable):
            Translator(http, self.settings, 'fake').translate(self.event, 'ru')
        self.assertEqual(len(http.calls), 1)

    def test_google_classifier_uses_same_provider(self):
        import json
        facts = {name: {'value': 'unknown', 'field': '', 'quote': ''}
                 for name in ('audience', 'format', 'performance_language')}
        http = Responses(google_response(json.dumps(facts)))
        class Store:
            def classification(self, key): return None
            def cache_classification(self, key, result): self.result = result
        store = Store()
        self.assertEqual(Classifier(http, self.settings, 'fake').classify(self.event, store), facts)
        self.assertEqual(store.result, facts)
        self.assertIn('contents', http.calls[0])

    def test_google_header_removed_on_cross_host_redirect(self):
        request = Request('https://example.org', headers={'X-Goog-Api-Key': 'secret', 'Authorization': 'Bearer secret'})
        redirected = SafeRedirects().redirect_request(request, None, 302, '', {}, 'https://other.example.org')
        self.assertFalse(any(k.lower() in {'authorization', 'x-goog-api-key'} for k in redirected.headers))
