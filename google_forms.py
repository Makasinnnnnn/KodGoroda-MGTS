import json
import logging
import os
from pathlib import Path
from threading import Thread
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials


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
    if not (forms_file.is_file() and token_file.is_file()):
        return None
    interval = max(5, int(os.getenv("GOOGLE_POLL_SECONDS", "15")))
    forms = json.loads(forms_file.read_text(encoding="utf-8"))
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
