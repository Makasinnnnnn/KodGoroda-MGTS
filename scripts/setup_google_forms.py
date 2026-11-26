"""Create both Google Forms and store their question IDs and OAuth token locally."""

import argparse
import json
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

from google_forms import SCOPES, call
from scripts.import_history import DEPARTMENT, FIELDS, INTERN_ID, MENTOR_ID, PERIOD


TITLES = {"intern": "Пульс-опрос стажёра МГТС", "mentor": "Оценка стажёра наставником МГТС"}
PROMPTS = {
    "task_clarity": "Мне понятно, каких результатов от меня ожидают по текущим задачам.",
    "mentor_support": "Я получаю достаточно поддержки и обратной связи от наставника.",
    "workload": "Моя текущая загрузка комфортна и позволяет качественно выполнять задачи.",
    "interest": "Мне интересны задачи, над которыми я работаю.",
    "development": "Я чувствую, что в процессе стажировки развиваю полезные для себя навыки.",
    "team_interaction": "Мне комфортно взаимодействовать с командой.",
    "satisfaction": "В целом я доволен тем, как проходит моя стажировка.",
    "task_understanding": "Насколько стажёр понимает поставленные задачи и ожидаемый результат?",
    "quality": "Насколько качественно стажёр выполняет поставленные задачи?",
    "independence": "Насколько самостоятельно стажёр выполняет поставленные задачи?",
    "deadlines": "Насколько стажёр соблюдает сроки и организует свою работу?",
    "initiative": "Насколько стажёр вовлечён в работу и проявляет инициативу?",
    "mentor_team_interaction": "Насколько эффективно стажёр взаимодействует с наставником и командой?",
    "difficulties": "С какими сложностями вы столкнулись за последний период стажировки?",
    "blockers": "Есть ли что-то, что сейчас мешает вам эффективно работать и развиваться?",
    "work_comment": "Что у стажёра получилось хорошо и с какими сложностями он столкнулся?",
    "attention": "Есть ли сложности или ситуации, на которые стоит обратить внимание?",
}
MENTOR_ANCHORS = {
    "task_understanding": ("Не понимает даже после пояснений", "Понимает типовые задачи", "Быстро понимает цель"),
    "quality": ("Нужна существенная доработка", "Результат в целом соответствует требованиям", "Стабильно качественный результат"),
    "independence": ("Нужен постоянный контроль", "Самостоятелен в типовых задачах", "Сам организует свою работу"),
    "deadlines": ("Регулярно нарушает сроки", "В основном соблюдает сроки", "Соблюдает сроки и заранее сообщает о рисках"),
    "initiative": ("Включается после напоминаний", "Выполняет необходимый объём", "Проявляет инициативу"),
    "mentor_team_interaction": ("Регулярные сложности в коммуникации", "Корректно взаимодействует", "Конструктивно работает с командой"),
}


def technical_list(values):
    return {"choiceQuestion": {"type": "DROP_DOWN", "options": [{"value": value} for value in values]}}


def question_specs(role):
    yield "intern_id", INTERN_ID, "", True, {"textQuestion": {}}
    if role == "mentor":
        yield "mentor_id", MENTOR_ID, "", True, {"textQuestion": {}}
    yield "department", DEPARTMENT, "", True, technical_list(
        ["Технический блок", "Коммерческий блок", "Административный блок", "HR-блок", "IT"])
    yield "period", PERIOD, "", True, technical_list([f"Месяц {n}" for n in range(1, 7)])
    for label, field in FIELDS[role]["scores"].items():
        anchors = (("Совсем не согласен", "Частично согласен", "Полностью согласен")
                   if role == "intern" else MENTOR_ANCHORS[field])
        description = PROMPTS[field] + f" 1: {anchors[0]}. 3: {anchors[1]}. 5: {anchors[2]}."
        yield field, label, description, True, {"scaleQuestion": {"low": 1, "high": 5,
                                                                "lowLabel": "1", "highLabel": "5"}}
    for label, field in FIELDS[role]["comments"].items():
        yield field, label, PROMPTS[field], False, {"textQuestion": {"paragraph": True}}


def create_requests(role):
    return [{"createItem": {"item": {"title": label, "description": description,
                 "questionItem": {"question": {"required": required, **kind}}},
                 "location": {"index": i}}}
            for i, (_, label, description, required, kind) in enumerate(question_specs(role))]


def save(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(payload, encoding="utf-8")
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--client", type=Path, default=Path("data/google-client.json"))
    parser.add_argument("--token", type=Path, default=Path("data/google-token.json"))
    parser.add_argument("--config", type=Path, default=Path("data/google-forms.json"))
    parser.add_argument("--publish", action="store_true", help="Open forms for responses")
    args = parser.parse_args()
    if args.token.exists():
        credentials = Credentials.from_authorized_user_file(str(args.token), SCOPES)
    else:
        flow = InstalledAppFlow.from_client_secrets_file(str(args.client), SCOPES)
        credentials = flow.run_local_server(port=0, access_type="offline", prompt="consent")
        save(args.token, credentials.to_json())
    forms = json.loads(args.config.read_text(encoding="utf-8")) if args.config.exists() else {}
    for role, title in TITLES.items():
        if role not in forms:
            result = call(credentials, "", {"info": {"title": title}})
            forms[role] = {"form_id": result["formId"], "questions": {}}
            save(args.config, json.dumps(forms, ensure_ascii=False, indent=2))
        form_id = forms[role]["form_id"]
        if not forms[role]["questions"]:
            result = call(credentials, "/" + form_id)
            if not result.get("items"):
                call(credentials, "/" + form_id + ":batchUpdate", {"requests": create_requests(role)})
                result = call(credentials, "/" + form_id)
            specs = list(question_specs(role))
            items = result["items"]
            if [item["title"] for item in items] != [spec[1] for spec in specs]:
                raise ValueError(f"Unexpected question titles for {role}")
            forms[role]["questions"] = {name: item["questionItem"]["question"]["questionId"]
                                       for (name, *_), item in zip(specs, items)}
            save(args.config, json.dumps(forms, ensure_ascii=False, indent=2))
        if args.publish:
            call(credentials, "/" + form_id + ":setPublishSettings",
                 {"publishSettings": {"publishState": {"isPublished": True, "isAcceptingResponses": True}},
                  "updateMask": "publishState"})
        details = call(credentials, "/" + form_id)
        print(f"{role}: {details.get('responderUri', form_id)}")


if __name__ == "__main__":
    main()
