import io
import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Event
from unittest.mock import patch

from app import DEEPSEEK_DIRECT_URL, DEEPSEEK_ROUTER_URL, FIELDS, ask_deepseek, create_app, validated_analysis


def model_reply(observations):
    return {"summary": "Стажёр указал на сложность.", "action": "Уточнить задачу.",
            "insufficient_data": False, "themes": [{"topic": "задачи", "observations": observations}]}


class AnalysisContractTest(unittest.TestCase):
    evidence = [
        {"id": "a", "month": 1, "role": "intern", "text": "Неясны критерии."},
        {"id": "b", "month": 2, "role": "mentor", "text": "Всё ещё неясны критерии."},
        {"id": "c", "month": 3, "role": "intern", "text": "Критерии пояснили, вопрос закрыт."},
        {"id": "d", "month": 4, "role": "intern", "text": "Опять непонятно задание."},
    ]

    def theme(self, *kinds):
        observations = [{"id": item["id"], "kind": kind} for item, kind in zip(self.evidence, kinds)]
        return validated_analysis(model_reply(observations), self.evidence)["themes"][0]

    def test_repetition_resolution_reopening(self):
        open_theme = self.theme("issue", "issue", "positive")
        self.assertTrue(open_theme["repeated"])
        self.assertEqual(open_theme["repeat_periods"], [2])
        resolved = self.theme("issue", "issue", "resolution")
        self.assertEqual(resolved["status"], "resolved")
        self.assertFalse(resolved["repeated"])
        self.assertEqual(resolved["evidence"][1]["role"], "mentor")
        reopened = self.theme("issue", "issue", "resolution", "issue")
        self.assertEqual(reopened["status"], "open")
        self.assertFalse(reopened["repeated"])

    def test_foreign_id_bad_kind_or_duplicate_rejected(self):
        issue = {"id": "a", "kind": "issue"}
        for observations in ([{"id": "x", "kind": "issue"}], [{"id": "a", "kind": "unknown"}], [issue, issue]):
            with self.subTest(observations=observations), self.assertRaises(ValueError):
                validated_analysis(model_reply(observations), self.evidence)

    def test_insufficient(self):
        payload = dict(model_reply([]), insufficient_data=True, themes=[])
        self.assertTrue(validated_analysis(payload, self.evidence)["insufficient_data"])
        with self.assertRaises(ValueError):
            validated_analysis(dict(payload, themes=model_reply([])["themes"]), self.evidence)

    def test_json_adapter(self):
        content = json.dumps(model_reply([{"id": "a", "kind": "issue"}]))
        response = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        providers = [(DEEPSEEK_DIRECT_URL, "deepseek-flash"),
                     (DEEPSEEK_ROUTER_URL, "deepseek/deepseek-v4-flash-free")]
        for base_url, model in providers:
            with self.subTest(base_url=base_url), patch("app.urlopen", return_value=io.BytesIO(response)) as server:
                result = ask_deepseek(self.evidence, "synthetic-key", model, base_url + "/")
                request = server.call_args.args[0]
                sent = json.loads(request.data)
                self.assertEqual(request.full_url, base_url + "/chat/completions")
                self.assertEqual(request.get_header("Authorization"), "Bearer synthetic-key")
                self.assertNotIn("Authorization", request.headers)
                self.assertEqual(sent["model"], model)
                self.assertEqual(json.loads(sent["messages"][1]["content"]), self.evidence)
                self.assertEqual(sent["response_format"], {"type": "json_object"})
                self.assertGreater(server.call_args.kwargs["timeout"], 0)
                self.assertEqual(result["themes"][0]["evidence"][0]["text"], self.evidence[0]["text"])

    def test_unrecognized_provider_never_receives_key(self):
        with patch("app.urlopen") as server, self.assertRaises(ValueError):
            ask_deepseek(self.evidence, "synthetic-key", "deepseek-flash", "https://example.invalid")
        server.assert_not_called()


class AnalysisWorkflowTest(unittest.TestCase):
    def test_timeout_duplicate_and_edit_while_model_pending(self):
        entered, release = Event(), Event()
        requests = []

        def provider(evidence, key, model, base_url):
            requests.append(evidence)
            if len(requests) == 1:
                entered.set()
                release.wait(4)
                raise TimeoutError()
            if len(requests) == 3:
                raise TimeoutError()
            return validated_analysis(model_reply([{"id": evidence[0]["id"], "kind": "issue"}]), evidence)

        with tempfile.TemporaryDirectory() as temp, ThreadPoolExecutor(max_workers=2) as pool:
            history = Path(temp, "history.json")
            database = Path(temp, "test.sqlite")
            row = {"source": "synthetic_demo", "form_id": "intern", "role": "intern", "submission_id": "seed",
                   "intern_id": "TEST-1", "mentor_id": None, "period": 1, "department": "IT",
                   "submitted_at": None, "scores": dict.fromkeys(FIELDS["intern"]["scores"].values(), 4),
                   "comments": dict.fromkeys(FIELDS["intern"]["comments"].values(), "")}
            history.write_text(json.dumps({"submissions": [row]}))
            config = {"DATABASE": str(database), "HISTORY": str(history), "TESTING": True,
                      "DEEPSEEK_API_KEY": "synthetic-key", "DEEPSEEK_SEND_COMMENTS": True, "WEBHOOK_TOKEN": "test"}

            def wait_state(expected):
                end = time.monotonic() + 4
                while time.monotonic() < end:
                    with closing(sqlite3.connect(database)) as db:
                        state, result = db.execute("SELECT state, result FROM analyses").fetchone()
                    if state == expected:
                        return json.loads(result or "{}")
                    time.sleep(.01)
                self.fail(f"Expected {expected}, got {state}")

            submitted = []
            submit = pool.submit

            def track_submit(*args):
                future = submit(*args)
                submitted.append(future)
                return future

            with (patch("app.ThreadPoolExecutor", return_value=pool),
                  patch.object(pool, "submit", side_effect=track_submit),
                  patch("app.ask_deepseek", side_effect=provider)):
                client = create_app(config).test_client()

                def post(body):
                    return client.post("/webhooks/yandex/intern", json=body, headers={"X-Webhook-Token": "test"})

                wait_state("no_comments")
                first = dict(row, submission_id="live:v1", submitted_at="2026-01-01T00:00:00Z",
                             comments={"difficulties": "Синтетика: критерии неясны."})
                second = dict(first, submission_id="live:v2", submitted_at="2026-01-02T00:00:00Z",
                              comments={"difficulties": "Синтетика: критерии уточнены."})
                self.assertEqual(client.post("/webhooks/yandex/intern", json=first).status_code, 401)
                for change in ({"submitted_at": "0001-01-01T00:00:00+01:00"}, {"period": 7}):
                    invalid = post(dict(first, **change))
                    self.assertEqual(invalid.status_code, 422)
                    self.assertIn("error", invalid.get_json())
                try:
                    self.assertEqual(post(first).status_code, 202)
                    self.assertTrue(entered.wait(2))
                    wait_state("pending")
                    self.assertEqual(post(first).status_code, 200)
                    self.assertEqual(post(second).status_code, 202)
                    evidence = wait_state("ready")["themes"][0]["evidence"]
                    self.assertEqual([x["text"] for x in evidence], [second["comments"]["difficulties"]])
                finally:
                    release.set()
                submitted[0].result(timeout=3)
                wait_state("ready")
                self.assertEqual(post(second).status_code, 200)
                third = dict(second, submission_id="live:v3", submitted_at="2026-01-03T00:00:00Z")
                self.assertEqual(post(third).status_code, 202)
                wait_state("error")
                self.assertEqual(client.get("/interns/TEST-1").status_code, 200)
                pool.shutdown(wait=True)
                self.assertEqual(len(requests), 3)
