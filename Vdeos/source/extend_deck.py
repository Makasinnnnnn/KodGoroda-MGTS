"""Add the business example and DeepSeek clip to the edited defense deck."""

import argparse
from pathlib import Path
from xml.dom import minidom
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from build_deck import A, P, R, PKG, add_relation, edit_text, nodes, poster


CT = "http://schemas.openxmlformats.org/package/2006/content-types"
PROBLEM = {
    "Зачем это\nМГТС": "Что стоит\nпоздний сигнал",
    "За полгода стажёр и\nнаставник заполняют\nпо шесть анкет.":
        "Пример из демо.\nКритерии готовности\nпоявились поздно.",
    "Сигналы теряются между анкетами": "Стажёр переделывает отчёт",
    "Чтобы заметить повторяющуюся проблему,\nHR сверяет ответы двух сторон за несколько\nмесяцев.":
        "Критерии появились после старта.\nОтчёт пришлось переделать дважды.",
    "Поздние уточнения ведут к переделкам": "Наставник тратит время повторно",
    "Неясные критерии и редкая обратная связь\nзамедляют работу стажёра и отнимают время\nнаставника.":
        "Он снова объясняет ожидания и проверяет\nновую версию. Это отнимает время\nу других задач команды.",
    "HR видит, с кем нужно поговорить": "Что может изменить МГТС",
    "Куратор проверяет исходные ответы, уточняет\nпричину и смотрит динамику в следующем месяце.":
        "HR предлагает заранее сверить пример результата.\nНа пилоте можно измерять время от сигнала\nдо первого разговора со стажёром.",
}
GOOGLE = {
    "Проверка на исторических данных": "Как Google Forms передаёт ответы",
    "30 анкет стажёров и 30 анкет наставников из двух XLSX":
        "60 исходных анкет из XLSX и два тестовых ответа из Google Forms",
    "Обе Google Forms передали тестовые анкеты": "Анкета → Google Forms API → карточка",
    "СТ-005 · шестой месяц": "Ответы связаны со стажёром СТ-005 в месяце 6",
    "Разница по задачам — 3 балла": "Разница +3. Повторное чтение API не создало дублей.",
}


def build(original, output, movie, ffmpeg):
    with ZipFile(original) as source:
        def document(part):
            return minidom.parseString(source.read(part))

        def edited_slide(part, replacements):
            slide = document(part)
            if edit_text(slide, replacements) != replacements.keys():
                raise ValueError(f"Unexpected text in {part}")
            return slide

        problem = edited_slide("ppt/slides/slide2.xml", PROBLEM)
        google = edited_slide("ppt/slides/slide6.xml", GOOGLE)
        deepseek = edited_slide("ppt/slides/slide5.xml",
                                {"От сигнала к действию HR": "Как DeepSeek предлагает действие HR"})
        video_rels = document("ppt/slides/_rels/slide5.xml.rels")
        add_relation(video_rels, "rIdSpeakerNotes", R + "/notesSlide", "../notesSlides/notesSlide5.xml")
        for rel in nodes(video_rels, PKG, "Relationship"):
            if rel.getAttribute("Target").lower().endswith(".mp4"):
                rel.setAttribute("Target", "../media/mgts-deepseek-advice.mp4")
            elif rel.getAttribute("Type") == R + "/image":
                rel.setAttribute("Target", "../media/mgts-deepseek-advice.png")

        def speaker_notes(part, text):
            notes = document(part)
            first = nodes(notes, A, "t")[0]
            first.firstChild.data = text
            return notes

        deepseek_notes = speaker_notes(
            "ppt/notesSlides/notesSlide5.xml",
            "Мы подали новый синтетический отзыв через локальный вебхук. После обработки DeepSeek предложил "
            "сверить критерии готовности задачи. По ссылкам видно, на каких отзывах основан совет. "
            "Ожидание ответа API сокращено при монтаже.",
        )
        problem_notes = speaker_notes(
            "ppt/notesSlides/notesSlide2.xml",
            "Пример на слайде демонстрационный. За поздним сигналом стоят повторная работа стажёра "
            "и повторная проверка наставника. На пилоте можно измерять, сколько времени проходит "
            "от сигнала до разговора и повторяется ли та же проблема через месяц.",
        )
        problem_rels = document("ppt/slides/_rels/slide2.xml.rels")
        for rel in nodes(problem_rels, PKG, "Relationship"):
            if rel.getAttribute("Type") == R + "/notesSlide":
                rel.setAttribute("Target", "../notesSlides/notesSlide8.xml")
        notes_rels = document("ppt/notesSlides/_rels/notesSlide2.xml.rels")
        for rel in nodes(notes_rels, PKG, "Relationship"):
            if rel.getAttribute("Type") == R + "/slide":
                rel.setAttribute("Target", "../slides/slide10.xml")

        presentation = document("ppt/presentation.xml")
        presentation_rels = document("ppt/_rels/presentation.xml.rels")
        slide_list = nodes(presentation, P, "sldIdLst")[0]
        slide_ids = nodes(slide_list, P, "sldId")
        slide_id = presentation.createElementNS(P, "p:sldId")
        slide_id.setAttribute("id", str(max(int(s.getAttribute("id")) for s in slide_ids) + 1))
        slide_id.setAttributeNS(R, "r:id", "rIdBusinessProblem")
        slide_list.insertBefore(slide_id, slide_ids[2])
        add_relation(presentation_rels, "rIdBusinessProblem", R + "/slide", "slides/slide10.xml")

        types = document("[Content_Types].xml")
        for part, subtype in (("/ppt/slides/slide10.xml", "slide"),
                              ("/ppt/notesSlides/notesSlide8.xml", "notesSlide")):
            override = types.createElementNS(CT, "Override")
            override.setAttribute("PartName", part)
            override.setAttribute("ContentType", f"application/vnd.openxmlformats-officedocument.presentationml.{subtype}+xml")
            types.documentElement.appendChild(override)
        props = document("docProps/app.xml")
        slides_count = props.getElementsByTagName("Slides")
        if slides_count:
            slides_count[0].firstChild.data = str(len(slide_ids) + 1)

        changes = {
            "ppt/presentation.xml": presentation,
            "ppt/_rels/presentation.xml.rels": presentation_rels,
            "[Content_Types].xml": types,
            "docProps/app.xml": props,
            "ppt/slides/slide6.xml": google,
            "ppt/slides/slide7.xml": deepseek,
            "ppt/slides/_rels/slide7.xml.rels": video_rels,
            "ppt/slides/slide10.xml": problem,
            "ppt/slides/_rels/slide10.xml.rels": problem_rels,
            "ppt/notesSlides/notesSlide5.xml": deepseek_notes,
            "ppt/notesSlides/notesSlide8.xml": problem_notes,
            "ppt/notesSlides/_rels/notesSlide8.xml.rels": notes_rels,
        }
        with ZipFile(output, "w", ZIP_DEFLATED) as result:
            for entry in source.infolist():
                if entry.filename in changes:
                    data = changes.pop(entry.filename).toxml(encoding="UTF-8")
                else:
                    data = source.read(entry)
                result.writestr(entry, data)
            for part, item in changes.items():
                result.writestr(part, item.toxml(encoding="UTF-8"))
            result.writestr("ppt/media/mgts-deepseek-advice.png", poster(movie, ffmpeg))
            result.write(movie, "ppt/media/mgts-deepseek-advice.mp4", compress_type=ZIP_STORED)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    args = parser.parse_args()
    if args.original.resolve() == args.output.resolve():
        parser.error("Choose a separate output path.")
    movie = Path(__file__).resolve().parents[1] / "04-deepseek-advice.mp4"
    build(args.original, args.output, movie, args.ffmpeg)
