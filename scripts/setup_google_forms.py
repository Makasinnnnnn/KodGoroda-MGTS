"""Create both Google Forms and store their question IDs and OAuth token locally."""

import argparse
import json
import os
from tempfile import NamedTemporaryFile
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

from google_forms import SCOPES, call
from scripts.import_history import DEPARTMENT, FIELDS, INTERN_ID, MENTOR_ID, PERIOD, read_workbook


TITLES = {"intern": "Пульс-опрос стажёра МГТС", "mentor": "Оценка стажёра наставником МГТС"}
PROMPTS = {
    "task_clarity": "Мне понятно, каких результатов от меня ожидают по текущим задачам.",
    "mentor_support": "Я получаю достаточно поддержки и обратной связи от наставника.",
    "workload": "Моя текущая загрузка комфортна и позволяет качественно выполнять задачи.",
    "interest": "Мне интересны задачи, над которыми я работаю.",
    "development": "Я чувствую, что в процессе стажировки развиваю полезные для себя навыки.",
    "team_interaction": "Мне комфортно взаимодействовать с командой.",
    "satisfaction": "В целом я доволен тем, как проходит моя стажировка.",
    "difficulties": "С какими сложностями вы столкнулись за последний период стажировки?",
    "blockers": "Есть ли что-то в задачах, взаимодействии с наставником или командой, что сейчас мешает вам эффективно работать и развиваться?",
    "task_understanding": "Насколько стажер понимает поставленные задачи и ожидаемый результат?",
    "quality": "Насколько качественно стажер выполняет поставленные задачи?",
    "independence": "Насколько самостоятельно стажер выполняет поставленные задачи?",
    "deadlines": "Насколько стажер соблюдает сроки и организует свою работу?",
    "initiative": "Насколько стажер вовлечен в работу и проявляет инициативу?",
    "mentor_team_interaction": "Насколько эффективно стажер взаимодействует с наставником и командой?",
    "work_comment": "Опишите, как стажер проявил себя за последний период: что получилось хорошо и с какими сложностями он столкнулся?",
    "attention": "Есть ли сложности или ситуации, на которые, по вашему мнению, стоит обратить внимание? Если да, кратко опишите."
}
MENTOR_ANCHORS = {
    "task_understanding": [
        "Часто не понимает задачу и ожидаемый результат даже после пояснений",
        "Понимает типовые задачи; по новым или сложным задачам требуются уточнения",
        "Быстро понимает цель и ожидаемый результат, задает необходимые уточняющие вопросы"
    ],
    "quality": [
        "Результат регулярно требует существенной доработки",
        "Результат в целом соответствует требованиям, возможны отдельные доработки",
        "Стабильно выполняет задачи качественно, результат требует минимальных корректировок"
    ],
    "independence": [
        "Требуется постоянное сопровождение и контроль",
        "Самостоятельно выполняет типовые задачи, обращается за помощью в сложных ситуациях",
        "Самостоятельно организует работу и решает задачи в рамках своей зоны ответственности"
    ],
    "deadlines": [
        "Регулярно нарушает сроки или не сообщает о рисках",
        "В основном соблюдает сроки и сообщает о возникающих сложностях",
        "Стабильно соблюдает сроки, заранее обозначает риски и организует свою работу"
    ],
    "initiative": [
        "Включается в работу преимущественно после напоминаний",
        "Вовлечен в поставленные задачи и выполняет необходимый объем работы",
        "Проявляет инициативу, предлагает идеи и дополнительные способы решения задач"
    ],
    "mentor_team_interaction": [
        "Возникают регулярные сложности в коммуникации и работе с обратной связью",
        "Корректно взаимодействует с коллегами и воспринимает обратную связь",
        "Конструктивно взаимодействует с командой и использует обратную связь в работе"
    ]
}


def technical_list(values):
    return {"choiceQuestion": {"type": "DROP_DOWN", "options": [{"value": value} for value in values]}}


def load_roster():
    history = Path(os.getenv("MGTS_HISTORY", "data/history.json"))
    if history.is_file():
        records = json.loads(history.read_text(encoding="utf-8"))["submissions"]
    else:
        records = []
        for role in TITLES:
            path = Path(os.getenv(f"MGTS_{role.upper()}_XLSX", f"data/{role}.xlsx"))
            if not path.is_file():
                raise SystemExit("Сначала загрузите книги или выполните python -m scripts.seed_demo")
            records.extend(read_workbook(path, role))
    roster = {key: sorted({row[key] for row in records if row.get(key)})
              for key in ("intern_id", "mentor_id", "department")}
    if not all(roster.values()):
        raise ValueError("В истории отсутствуют ID участников или подразделения")
    return roster


def question_specs(role, roster):
    yield "intern_id", INTERN_ID, "", True, technical_list(roster["intern_id"])
    if role == "mentor":
        yield "mentor_id", MENTOR_ID, "", True, technical_list(roster["mentor_id"])
    yield "department", DEPARTMENT, "", True, technical_list(roster["department"])
    yield "period", PERIOD, "", True, technical_list([f"Месяц {n}" for n in range(1, 7)])
    for label, field in FIELDS[role]["scores"].items():
        if role == "intern":
            scale = "1 — совсем не согласен; 2 — скорее не согласен; 3 — частично согласен / частично не согласен; 4 — скорее согласен; 5 — полностью согласен."
        else:
            low, middle, high = MENTOR_ANCHORS[field]
            scale = f"1 — {low}. 3 — {middle}. 5 — {high}. Оценки 2 и 4 — промежуточные значения."
        description = f"{PROMPTS[field]} {scale}"
        yield field, label, description, True, {"scaleQuestion": {"low": 1, "high": 5,
                                                                "lowLabel": "1", "highLabel": "5"}}
    for label, field in FIELDS[role]["comments"].items():
        yield field, label, PROMPTS[field], False, {"textQuestion": {"paragraph": True}}


def create_requests(specs):
    return [{"createItem": {"item": {"title": label, "description": description,
                 "questionItem": {"question": {"required": required, **kind}}},
                 "location": {"index": i}}}
            for i, (_, label, description, required, kind) in enumerate(specs)]


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as temp:
        temp.write(payload)
    Path(temp.name).replace(path)


def verify_questions(items, specs):
    if len(items) != len(specs):
        raise ValueError("Число вопросов не соответствует структуре анкеты")
    ids = {}
    for item, (name, label, description, required, kind) in zip(items, specs):
        question = item.get("questionItem", {}).get("question", {})
        field_type, = kind
        content = question.get(field_type, {})
        if (item.get("title") != label or item.get("description", "") != description
                or question.get("required", False) != required
                or field_type not in question or any(content.get(k) != v for k, v in kind[field_type].items())):
            raise ValueError(f"Проверьте настройки вопроса «{label}» у владельца формы")
        question_id = question.get("questionId")
        if not question_id or question_id in ids.values():
            raise ValueError(f"Отсутствует или повторяется questionId для «{label}»")
        ids[name] = question_id
    return ids


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, default=Path("data/google-client.json"))
    parser.add_argument("--token", type=Path, default=Path("data/google-token.json"))
    parser.add_argument("--config", type=Path, default=Path("data/google-forms.json"))
    parser.add_argument("--publish", action="store_true", help="Open forms for responses")
    args = parser.parse_args()
    roster = load_roster()
    if args.token.exists():
        credentials = Credentials.from_authorized_user_file(str(args.token), SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(str(args.client), SCOPES)
        credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        save(args.token, credentials.to_json())
    forms = json.loads(args.config.read_text(encoding="utf-8")) if args.config.exists() else {}
    for role, title in TITLES.items():
        if role not in forms:
            result = call(credentials, "?unpublished=true", {"info": {"title": title}})
            forms[role] = {"form_id": result["formId"], "questions": {}}
            save(args.config, json.dumps(forms, ensure_ascii=False, indent=2))
        form_id = forms[role]["form_id"]
        specs = list(question_specs(role, roster))
        result = call(credentials, "/" + form_id)
        if not result.get("items") and not forms[role]["questions"]:
            call(credentials, "/" + form_id + ":batchUpdate", {"requests": create_requests(specs)})
            result = call(credentials, "/" + form_id)
        forms[role]["questions"] = verify_questions(result.get("items", []), specs)
        save(args.config, json.dumps(forms, ensure_ascii=False, indent=2))
        if args.publish:
            call(credentials, "/" + form_id + ":setPublishSettings",
                 {"publishSettings": {"publishState": {"isPublished": True, "isAcceptingResponses": True}},
                  "updateMask": "publishState"})
        details = call(credentials, "/" + form_id)
        state = details.get("publishSettings", {}).get("publishState", {})
        print(f"{role}: published={state.get('isPublished', False)}, "
              f"accepting={state.get('isAcceptingResponses', False)}, {details.get('responderUri', form_id)}")


if __name__ == "__main__":
    main()
