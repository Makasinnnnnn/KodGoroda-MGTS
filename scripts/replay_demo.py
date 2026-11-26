"""Deliver two synthetic answers through the dashboard's local webhook."""

import json
import os
from urllib.request import Request, urlopen

from scripts.import_history import FIELDS


def main():
    token = os.getenv("MGTS_WEBHOOK_TOKEN")
    if not token:
        raise SystemExit("Set MGTS_WEBHOOK_TOKEN to the value used by the running demo.")
    for role, person, department in [("intern", 2, "IT"), ("mentor", 3, "HR-блок")]:
        scores = dict.fromkeys(FIELDS[role]["scores"].values(), 4)
        payload = {
            "form_id": f"local-demo-{role}", "submission_id": f"local-demo-{role}-01",
            "intern_id": f"DEMO-{person}", "department": department, "period": 6,
            "scores": scores,
        }
        if role == "intern":
            scores.update(task_clarity=1, satisfaction=3)
            payload["comments"] = {
                "difficulties": "Синтетический ответ: критерии приёмки всё ещё неясны."
            }
        else:
            payload["mentor_id"] = "MENTOR-3"
            payload["comments"] = {"work_comment": "Синтетический ответ: задачи выполнены в срок."}
        request = Request(
            f"http://127.0.0.1:8080/webhooks/yandex/{role}",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json", "X-Webhook-Token": token},
        )
        with urlopen(request, timeout=10) as response:
            print(f"{role}: {response.status} {json.load(response)['status']}")


if __name__ == "__main__":
    main()
