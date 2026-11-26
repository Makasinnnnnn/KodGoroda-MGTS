"""Create a clearly marked synthetic history for a fresh clone."""

import json
from pathlib import Path

from scripts.import_history import FIELDS


def main():
    path = Path("data/history.json")
    if path.exists() or any(Path("data").glob("*.xlsx")) or Path("data/dashboard.sqlite").exists():
        raise SystemExit("Use an empty data directory for the synthetic demo.")
    departments = ["Технический блок", "IT", "HR-блок"]
    records = []
    for person, department in enumerate(departments, 1):
        for month in range(1, 7):
            for role, form in FIELDS.items():
                if (person, month, role) == (3, 6, "mentor"):
                    continue
                scores = {key: 4 + (month >= 5) for key in form["scores"].values()}
                comments = dict.fromkeys(form["comments"].values(), "Демонстрационный отзыв: период прошёл по плану.")
                if person == 2 and role == "intern" and month in (5, 6):
                    scores.update(task_clarity=2, satisfaction=3)
                    comments["difficulties"] = "Демонстрационный отзыв: неясны критерии готовности задачи."
                records.append({
                    "source": "synthetic_demo", "form_id": role,
                    "submission_id": f"demo:{role}:{person}:{month}", "role": role,
                    "intern_id": f"DEMO-{person}", "mentor_id": f"MENTOR-{person}" if role == "mentor" else None,
                    "department": department, "period": month, "submitted_at": None,
                    "scores": scores, "comments": comments,
                })
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as output:
        json.dump({"schema_version": 1, "submissions": records}, output, ensure_ascii=False, indent=2)
    print(f"Created {len(records)} synthetic responses at {path}")


if __name__ == "__main__":
    main()
