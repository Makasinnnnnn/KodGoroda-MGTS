"""Convert both organizer workbooks to a local JSON file for the dashboard."""

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from openpyxl import load_workbook


INTERN_ID = "ID стажера"
MENTOR_ID = "ID наставника"
DEPARTMENT = "Подразделение / направление стажировки"
PERIOD = "Контрольный период"
FIELDS = {
    "intern": {
        "scores": {
            "Понятность задач": "task_clarity",
            "Поддержка и обратная связь наставника": "mentor_support",
            "Комфортность нагрузки": "workload",
            "Интерес к задачам": "interest",
            "Профессиональное развитие": "development",
            "Взаимодействие с командой": "team_interaction",
            "Общая удовлетворенность стажировкой": "satisfaction",
        },
        "comments": {
            "Сложности за период": "difficulties",
            "Что мешает работать и развиваться": "blockers",
        },
    },
    "mentor": {
        "scores": {
            "Понимание задач и ожиданий": "task_understanding",
            "Качество выполнения задач": "quality",
            "Самостоятельность": "independence",
            "Соблюдение сроков и организация работы": "deadlines",
            "Вовлеченность и инициативность": "initiative",
            "Взаимодействие с наставником и командой": "mentor_team_interaction",
        },
        "comments": {
            "Комментарий о работе за период": "work_comment",
            "Сложности / ситуации для внимания": "attention",
        },
    },
}


def required_text(value, field):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"пустое или некорректное поле «{field}»")
    return value.strip()


def parse_period(value):
    match = re.fullmatch(r"(?:Месяц\s+)?([1-6])", str(value).strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f"неверный контрольный период: {value!r}")
    return int(match[1])


def parse_score(value, field):
    if type(value) not in (int, float) or value not in range(1, 6):
        raise ValueError(f"оценка «{field}» должна быть целым числом от 1 до 5")
    return int(value)


def parse_row(role, cells):
    intern_id = required_text(cells[INTERN_ID], INTERN_ID)
    mentor_id = required_text(cells[MENTOR_ID], MENTOR_ID) if role == "mentor" else None
    period = parse_period(cells[PERIOD])
    return {
        "source": "historical_xlsx",
        "form_id": role,
        "submission_id": f"{role}:{intern_id}:{period}",
        "role": role,
        "intern_id": intern_id,
        "mentor_id": mentor_id,
        "department": required_text(cells[DEPARTMENT], DEPARTMENT),
        "period": period,
        "submitted_at": None,
        "scores": {
            key: parse_score(cells[header], header)
            for header, key in FIELDS[role]["scores"].items()
        },
        "comments": {
            key: "" if cells[header] is None else str(cells[header]).strip()
            for header, key in FIELDS[role]["comments"].items()
        },
    }


def read_workbook(path, role):
    required = {INTERN_ID, DEPARTMENT, PERIOD, *FIELDS[role]["scores"], *FIELDS[role]["comments"]}
    if role == "mentor":
        required.add(MENTOR_ID)
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        rows = sheet.iter_rows(values_only=True)
        headers = [str(value).strip() if value is not None else "" for value in next(rows, ())]
        missing = required.difference(headers)
        if missing:
            raise ValueError(f"{path.name}: нет столбцов: {', '.join(sorted(missing))}")
        duplicates = {header for header, count in Counter(headers).items() if count > 1}
        if duplicates & required:
            raise ValueError(f"{path.name}: повторяются обязательные заголовки")
        records = []
        seen = set()
        for row_number, row in enumerate(rows, 2):
            if all(value is None for value in row):
                continue
            try:
                record = parse_row(role, dict(zip(headers, row)))
                key = (record["intern_id"], record["period"])
                if key in seen:
                    raise ValueError("дублируется пара стажёр × контрольный период")
            except ValueError as exc:
                raise ValueError(f"{path.name}:{sheet.title}:{row_number}: {exc}") from exc
            seen.add(key)
            records.append(record)
        if not records:
            raise ValueError(f"{path.name}: нет ответов")
        return records
    finally:
        workbook.close()


def verify_case(intern, mentor):
    """Check the organizer's reference figures against the supplied books."""
    intern_index = {(row["intern_id"], row["period"]): row for row in intern}
    mentor_index = {(row["intern_id"], row["period"]): row for row in mentor}
    pairs = len(intern_index.keys() & mentor_index.keys())
    cover = [Counter(row["period"] for row in records) for records in (intern, mentor)]

    def monthly_average(field):
        result = []
        for period in range(1, 7):
            scores = [row["scores"][field] for row in intern if row["period"] == period]
            result.append(round(sum(scores) / len(scores), 1) if scores else None)
        return result

    def series(index, intern_id, periods, field):
        return [index.get((intern_id, period), {}).get("scores", {}).get(field) for period in periods]

    checks = [
        ("Стажёры / наставники / пары", (len(intern), len(mentor), pairs), (30, 30, 30)),
        ("Охват обеих ролей по месяцам", [[count[period] for period in range(1, 7)] for count in cover],
         [[5] * 6, [5] * 6]),
        ("Средняя удовлетворённость", monthly_average("satisfaction"), [4, 4, 4, 4.4, 4.8, 5]),
        ("Средняя комфортность нагрузки", monthly_average("workload"), [4, 4, 3.8, 3.6, 4.4, 4.8]),
        ("СТ-003, удовлетворённость", series(intern_index, "СТ-003", range(1, 7), "satisfaction"),
         [3, 3, 2, 4, 4, 5]),
        ("СТ-005, стажёр / наставник, месяцы 1–2",
         [series(intern_index, "СТ-005", (1, 2), "task_clarity"),
          series(mentor_index, "СТ-005", (1, 2), "task_understanding")], [[2, 2], [4, 4]]),
    ]
    mismatches = []
    for label, actual, expected in checks:
        print(f"{label}: {actual}")
        if actual != expected:
            mismatches.append(f"{label}: ожидалось {expected}")
    if mismatches:
        raise ValueError("\n".join(mismatches))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--intern", required=True, type=Path)
    parser.add_argument("--mentor", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path("data/history.json"))
    parser.add_argument("--verify-case", action="store_true", help="check the organizer's reference figures")
    args = parser.parse_args()
    intern = read_workbook(args.intern, "intern")
    mentor = read_workbook(args.mentor, "mentor")
    if args.verify_case:
        try:
            verify_case(intern, mentor)
        except ValueError as exc:
            parser.exit(1, f"{exc}\n")
    records = sorted(intern + mentor, key=lambda row: (row["intern_id"], row["period"], row["role"]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps({"schema_version": 1, "submissions": records},
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported intern={len(intern)} mentor={len(mentor)} total={len(records)}")


if __name__ == "__main__":
    main()
