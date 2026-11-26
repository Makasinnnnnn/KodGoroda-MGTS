import json
import logging
import os
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from scripts.import_history import FIELDS


API = "https://forms.googleapis.com/v1/forms"
SCOPES = ["https://www.googleapis.com/auth/forms.body",
          "https://www.googleapis.com/auth/forms.responses.readonly"]


def call(credentials, suffix, body=None):
    if not credentials.valid:
        credentials.refresh(GoogleAuthRequest())
    req = Request(API + suffix, data=json.dumps(body).encode() if body is not None else None,
                  headers={"Authorization": f"Bearer {credentials.token}", "Content-Type": "application/json"})
    with urlopen(req, timeout=15) as response:
        return json.load(response)


def list_responses(credentials, form_id):
    params = {"pageSize": 100}
    while True:
        page = call(credentials, "/" + quote(form_id, safe="") + "/responses?" + urlencode(params))
        yield from page.get("responses", [])
        if not page.get("nextPageToken"):
            return
        params["pageToken"] = page["nextPageToken"]


def extract_response(form, response):
    body = {"form_id": form["form_id"], "submitted_at": response["lastSubmittedTime"],
            "submission_id": f"{response['responseId']}:{response['lastSubmittedTime']}"}
    for name, question_id in form["questions"].items():
        choices = response.get("answers", {}).get(question_id, {}).get("textAnswers", {}).get("answers", [])
        if choices:
            body[name] = choices[0]["value"]
    return body


def start_polling(accept, stop, status, logger=None):
    logger = logger or logging.getLogger(__name__)
    forms_file = Path(os.getenv("GOOGLE_FORMS_CONFIG", "data/google-forms.json"))
    token_file = Path(os.getenv("GOOGLE_FORMS_TOKEN", "data/google-token.json"))
    if not forms_file.exists() and not token_file.exists():
        return None
    interval = max(5, int(os.getenv("GOOGLE_POLL_SECONDS", "15")))
    forms = json.loads(forms_file.read_text(encoding="utf-8"))
    if not isinstance(forms, dict) or forms.keys() != FIELDS.keys():
        raise ValueError("Нужны настройки обеих форм")
    for role, form in forms.items():
        required = {"intern_id", "period", "department", *FIELDS[role]["scores"].values(),
                    *FIELDS[role]["comments"].values()}
        if role == "mentor":
            required.add("mentor_id")
        if not isinstance(form, dict):
            raise ValueError(f"Неверные настройки формы для {role}")
        ids = form.get("questions")
        if (not isinstance(form.get("form_id"), str) or not form["form_id"]
                or not isinstance(ids, dict) or required != ids.keys()
                or not all(isinstance(q, str) and q for q in ids.values())
                or len(set(ids.values())) != len(ids)):
            raise ValueError(f"Неверные настройки question ID для {role}")
    if forms["intern"]["form_id"] == forms["mentor"]["form_id"]:
        raise ValueError("Нужны две разные формы")
    credentials = Credentials.from_authorized_user_file(str(token_file), SCOPES)

    def poll():
        from datetime import datetime, timezone

        while not stop.is_set():
            errors = 0
            for role, form in forms.items():
                try:
                    for response in list_responses(credentials, form["form_id"]):
                        try:
                            accept(role, extract_response(form, response), "google_forms")
                        except (ValueError, KeyError, TypeError):
                            errors += 1
                except Exception as exc:
                    errors += 1
                    logger.warning("Google Forms %s: %s", role, type(exc).__name__)
            status.update(state="error" if errors else "ready", errors=errors,
                          checked_at=datetime.now(timezone.utc).strftime("%H:%M:%S UTC"))
            stop.wait(interval if not errors else max(interval, 30))

    status["state"] = "pending"
    worker = Thread(target=poll, name="Google Forms poller", daemon=True)
    worker.start()
    return worker
