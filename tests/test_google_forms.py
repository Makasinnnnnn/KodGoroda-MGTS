"""Offline tests: only the Google transport and the OAuth loader are replaced."""

import json
import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from copy import deepcopy
from pathlib import Path
from threading import Event
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from app import create_app
from google_forms import start_polling
from scripts.import_history import FIELDS
from scripts.setup_google_forms import create_requests, question_specs, verify_questions


ROSTER = {"intern_id": ["DEMO-1"], "mentor_id": ["MENTOR-1"], "department": ["IT"]}


def mock_form(role):
    specs = list(question_specs(role, ROSTER))
    items = [deepcopy(req["createItem"]["item"]) for req in create_requests(specs)]
    for i, item in enumerate(items):
        item["questionItem"]["question"]["questionId"] = format(90 - i, "08x")
    return items, specs


def google_response(role, ids, minute, comment):
    values = {key: choices[0] for key, choices in ROSTER.items() if key in ids}
    values.update(period="Месяц 6")
    values.update(dict.fromkeys(FIELDS[role]["scores"].values(), "4"))
    if role == "intern":
        values["task_clarity"] = "2" if minute == 0 else "5"
    comment_key = next(iter(FIELDS[role]["comments"].values()))
    values[comment_key] = comment
    return {"responseId": role + "-response", "lastSubmittedTime": f"2026-01-02T10:{minute:02}:00.000Z",
            "answers": {ids[key]: {"textAnswers": {"answers": [{"value": value}]}}
                        for key, value in values.items()}}


class GoogleFormsTest(unittest.TestCase):
    def test_schema_and_changed_scale(self):
        for role in FIELDS:
            items, specs = mock_form(role)
            self.assertEqual(len(verify_questions(items, specs)), 12)
            scales = [item for item in items if "scaleQuestion" in item["questionItem"]["question"]]
            self.assertEqual(len(scales), 7 if role == "intern" else 6)
            question = scales[-1]["questionItem"]["question"]
            question["scaleQuestion"]["high"] = 4
            with self.assertRaises(ValueError):
                verify_questions(items, specs)

    def test_automatic_poll_replay_edit_and_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            history = []
            forms = {}
            responses = {}
            for role, fields in FIELDS.items():
                history.append(dict(source="synthetic_demo", form_id=role, submission_id="seed",
                                    intern_id="DEMO-1", role=role, department="IT", period=1,
                                    mentor_id="MENTOR-1" if role == "mentor" else None,
                                    scores=dict.fromkeys(fields["scores"].values(), 4),
                                    comments=dict.fromkeys(fields["comments"].values(), ""), submitted_at=None))
                ids = verify_questions(*mock_form(role))
                forms[role] = {"form_id": role, "questions": ids}
                responses[role] = google_response(role, ids, 0, "SIMULATED-" + role)
            (folder / "history").write_text(json.dumps({"submissions": history}))
            config = folder / "forms"
            config.write_text(json.dumps(forms))
            token = folder / "token"
            token.touch()
            db = folder / "db.sqlite"
            app = create_app({"TESTING": True, "DATABASE": str(db), "HISTORY": str(folder / "history"),
                              "DEEPSEEK_API_KEY": ""})
            client = app.test_client()
            detail = "/interns/DEMO-1?month=6"
            self.assertNotIn(b"SIMULATED-", client.get(detail).data)
            edited = google_response("intern", forms["intern"]["questions"], 1, "SIMULATED-revision")
            include_edit = False

            def fake_api(credentials, suffix):
                path = urlsplit(suffix)
                role = path.path.split("/")[1]
                if role == "intern" and include_edit:
                    if "pageToken" not in parse_qs(path.query):
                        return {"responses": [edited], "nextPageToken": "older"}
                return {"responses": [responses[role]]}

            def poll_once():
                stop = Event()
                # Poll both forms once; end immediately when the production worker would sleep.
                stop.wait = lambda timeout: stop.set()
                status = {}
                worker = start_polling(app.extensions["accept_survey"], stop, status)
                worker.join(5)
                self.assertFalse(worker.is_alive())
                self.assertEqual(status["state"], "ready")

            def count():
                with closing(sqlite3.connect(db)) as conn:
                    return conn.execute("SELECT COUNT(*) FROM submissions WHERE source='google_forms'").fetchone()[0]

            env = {"GOOGLE_FORMS_CONFIG": str(config), "GOOGLE_FORMS_TOKEN": str(token)}
            with patch.dict(os.environ, env), patch("google_forms.Credentials.from_authorized_user_file"), \
                    patch("google_forms.call", side_effect=fake_api):
                poll_once()
                self.assertEqual(count(), 2)
                page = client.get(detail)
                self.assertEqual(page.status_code, 200)
                self.assertIn(b"SIMULATED-intern", page.data)
                self.assertIn(b"SIMULATED-mentor", page.data)
                poll_once()
                self.assertEqual(count(), 2)
                include_edit = True
                poll_once()
                self.assertEqual(count(), 3)
                page = client.get(detail)
                self.assertIn(b"SIMULATED-revision", page.data)
                self.assertNotIn(b"SIMULATED-intern", page.data)
                self.assertIn(b"SIMULATED-mentor", page.data)
