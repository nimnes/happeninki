import copy
import json
import unittest

from happeninki.config import load_config
from happeninki.http import RemoteError
from happeninki.models import Event
from happeninki.translator import TranslationUnavailable, Translator, parse_translation


GOOD_JSON = '{"title":"Концерт в Tampere","summary":"Выступит местная группа."}'


class Responses:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, url, **kwargs):
        self.calls.append(copy.deepcopy(kwargs["body"]))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class TranslationTests(unittest.TestCase):
    def setUp(self):
        self.event = Event(source="tampere", source_id="test", title="Konsertti",
            description="Paikallinen yhtye esiintyy.", url="https://example.org",
            municipality="Tampere", venue="Venue", address="", category="music",
            start="2026-10-20", end="2026-10-20", dates=[])

    def translator(self, http):
        return Translator(http, load_config()["ollama"], "fake-key")

    def test_wrapped_json_uses_one_request(self):
        http = Responses({"message": {"content": "Here is the translation:\n```json\n" + GOOD_JSON + "\n```"}})
        self.assertEqual(self.translator(http).translate(self.event, "ru")["title"], "Концерт в Tampere")
        self.assertEqual(len(http.calls), 1)
        self.assertNotIn("format", http.calls[0])

    def test_escaped_quotes_braces_and_newlines_preserved(self):
        content = json.dumps({"title": 'Группа "Test"', "summary": "Первая строка\nВторая {строка}."}, ensure_ascii=False)
        result = parse_translation("```JSON\n" + content + "\n```")
        self.assertEqual(result["title"], 'Группа "Test"')
        self.assertEqual(result["summary"], "Первая строка\nВторая {строка}.")

    def test_truncated_response_regenerated_once_with_more_room(self):
        http = Responses(
            {"message": {"content": '{"title":"Концерт","summary":"Оборвано'}, "done_reason": "length"},
            {"message": {"content": GOOD_JSON}, "done_reason": "stop"})
        with self.assertLogs("happeninki.translator", level="WARNING") as logs:
            result = self.translator(http).translate(self.event, "ru")
        self.assertEqual(result["summary"], "Выступит местная группа.")
        self.assertEqual(len(http.calls), 2)
        self.assertGreater(http.calls[1]["options"]["num_predict"], http.calls[0]["options"]["num_predict"])
        self.assertIn("finish=length", logs.output[0])
        self.assertNotIn("Оборвано", logs.output[0])
        self.assertEqual(http.calls[1]["messages"][1], http.calls[0]["messages"][1])

    def test_invalid_field_type_retried(self):
        http = Responses({"message": {"content": '{"title":"Title","summary":42}'}},
                         {"message": {"content": GOOD_JSON}})
        with self.assertLogs("happeninki.translator", level="WARNING"):
            self.assertTrue(self.translator(http).translate(self.event, "ru")["summary"])
        self.assertEqual(len(http.calls), 2)

    def test_repeated_malformed_json_fails_without_guessing_text(self):
        http = Responses(*[{"message": {"content": '{"title":"Title","summary":"SECRET_SOURCE'} ,
                            "done_reason": "length"}] * 2)
        with self.assertLogs("happeninki.translator", level="WARNING") as logs:
            with self.assertRaisesRegex(ValueError, "failed after 2 attempts") as error:
                self.translator(http).translate(self.event, "ru")
        self.assertEqual(len(http.calls), 2)
        self.assertNotIn("SECRET_SOURCE", str(error.exception) + str(logs.output))

    def test_empty_content_is_retried_and_has_clear_error(self):
        http = Responses({"message": {"content": None}}, {"message": {"content": ""}})
        with self.assertLogs("happeninki.translator", level="WARNING"):
            with self.assertRaisesRegex(ValueError, "empty translation content"):
                self.translator(http).translate(self.event, "ru")

    def test_quota_failure_has_no_format_retry(self):
        http = Responses(RemoteError("Ollama", 429))
        with self.assertRaises(TranslationUnavailable):
            self.translator(http).translate(self.event, "ru")
        self.assertEqual(len(http.calls), 1)

    def test_quota_failure_during_retry_stops_regeneration(self):
        http = Responses({"message": {"content": "Not JSON"}}, RemoteError("Ollama", 429))
        with self.assertLogs("happeninki.translator", level="WARNING"):
            with self.assertRaises(TranslationUnavailable):
                self.translator(http).translate(self.event, "ru")
        self.assertEqual(len(http.calls), 2)


if __name__ == "__main__":
    unittest.main()
