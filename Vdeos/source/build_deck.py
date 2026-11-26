"""Refresh text and embed the three recordings in the original nine-slide deck."""

import argparse
import json
import posixpath
import subprocess
from pathlib import Path
from xml.dom import minidom
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CLIPS = {3: "01-overview", 4: "02-intern-card", 5: "03-signal-evidence"}


def nodes(root, ns, name):
    return list(root.getElementsByTagNameNS(ns, name))


def edit_text(document, replacements):
    applied = set()
    for shape in nodes(document, P, "sp"):
        paragraphs = nodes(shape, A, "p")
        old = "\n".join("".join(t.firstChild.data if t.firstChild else "" for t in nodes(p, A, "t"))
                        for p in paragraphs)
        if old not in replacements:
            continue
        new_lines = replacements[old].split("\n")
        parent = paragraphs[0].parentNode
        for index, line in enumerate(new_lines):
            if index < len(paragraphs):
                p = paragraphs[index]
            else:
                p = paragraphs[-1].cloneNode(True)
                parent.appendChild(p)
            text_nodes = nodes(p, A, "t")
            for t in text_nodes:
                while t.firstChild:
                    t.removeChild(t.firstChild)
            text_nodes[0].appendChild(document.createTextNode(line))
        for p in paragraphs[len(new_lines):]:
            parent.removeChild(p)
        applied.add(old)
    return applied


def add_relation(document, id_, type_, target):
    relation = document.createElementNS(PKG, "Relationship")
    for name, value in {"Id": id_, "Type": type_, "Target": target}.items():
        relation.setAttribute(name, value)
    document.documentElement.appendChild(relation)


def attach_third_video(document, picture, source_slide, rels):
    source_picture = nodes(source_slide, P, "pic")[0]
    source_properties = nodes(source_picture, P, "nvPicPr")[0]
    properties = nodes(picture, P, "nvPicPr")[0]
    shape = nodes(properties, P, "cNvPr")[0]
    source_id = nodes(source_properties, P, "cNvPr")[0].getAttribute("id")
    target_id = shape.getAttribute("id")
    source_data = nodes(source_properties, P, "nvPr")[0]
    new_data = document.importNode(source_data, True)
    properties.replaceChild(new_data, nodes(properties, P, "nvPr")[0])
    nodes(new_data, A, "videoFile")[0].setAttributeNS(R, "r:link", "rIdVideoLink")
    media = new_data.getElementsByTagName("p14:media")[0]
    media.setAttribute("xmlns:p14", media.namespaceURI)
    media.setAttributeNS(R, "r:embed", "rIdVideoEmbed")
    click = document.createElementNS(A, "a:hlinkClick")
    click.setAttributeNS(R, "r:id", "")
    click.setAttribute("action", "ppaction://media")
    shape.insertBefore(click, shape.firstChild)
    timing = document.importNode(nodes(source_slide, P, "timing")[0], True)
    for item in timing.getElementsByTagName("*"):
        if item.getAttribute("spid") == source_id:
            item.setAttribute("spid", target_id)
    extensions = [node for node in document.documentElement.childNodes
                  if node.nodeType == node.ELEMENT_NODE and node.localName == "extLst"]
    document.documentElement.insertBefore(timing, extensions[0] if extensions else None)
    target = "../media/media3.mp4"
    add_relation(rels, "rIdVideoLink", R + "/video", target)
    add_relation(rels, "rIdVideoEmbed", "http://schemas.microsoft.com/office/2007/relationships/media", target)
    return target


def poster(movie, ffmpeg):
    return subprocess.check_output([ffmpeg, "-v", "error", "-ss", "0.5", "-i", str(movie),
                                    "-frames:v", "1", "-c:v", "png", "-f", "image2pipe", "pipe:1"])


def build(original, output, clips_folder, ffmpeg):
    replacements = json.loads(Path(__file__).with_name("defense-text.json").read_text(encoding="utf-8-sig"))
    edited, videos, applied = {}, {}, set()
    with ZipFile(original) as source:
        original_video_slide = minidom.parseString(source.read("ppt/slides/slide3.xml"))
        for slide in range(1, 10):
            part = f"ppt/slides/slide{slide}.xml"
            document = minidom.parseString(source.read(part))
            updated = edit_text(document, replacements)
            applied.update(updated)
            if slide in CLIPS:
                rel_part = f"ppt/slides/_rels/slide{slide}.xml.rels"
                rels = minidom.parseString(source.read(rel_part))
                picture = nodes(document, P, "pic")[0]
                targets = {r.getAttribute("Id"): r.getAttribute("Target") for r in nodes(rels, PKG, "Relationship")}
                if nodes(picture, A, "videoFile"):
                    video_target = targets[nodes(picture, A, "videoFile")[0].getAttributeNS(R, "link")]
                else:
                    video_target = attach_third_video(document, picture, original_video_slide, rels)
                    edited[rel_part] = rels.toxml(encoding="UTF-8")
                poster_target = targets[nodes(picture, A, "blip")[0].getAttributeNS(R, "embed")]
                movie = clips_folder / (CLIPS[slide] + ".mp4")
                videos[posixpath.normpath(posixpath.join("ppt/slides", video_target))] = movie
                edited[posixpath.normpath(posixpath.join("ppt/slides", poster_target))] = poster(movie, ffmpeg)
            if updated or slide in CLIPS:
                edited[part] = document.toxml(encoding="UTF-8")
        if applied != replacements.keys():
            raise ValueError("The input deck did not match the original text.")
        with ZipFile(output, "w", ZIP_DEFLATED) as result:
            for entry in source.infolist():
                if entry.filename in videos:
                    result.write(videos.pop(entry.filename), entry.filename, compress_type=ZIP_STORED)
                else:
                    result.writestr(entry, edited[entry.filename] if entry.filename in edited else source.read(entry))
            for part, movie in videos.items():
                result.write(movie, part, compress_type=ZIP_STORED)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ffmpeg", default="ffmpeg")
    arguments = parser.parse_args()
    folder = Path(__file__).resolve().parents[1]
    output = arguments.output or folder / "mgts-defense-with-screencasts.pptx"
    if arguments.original.resolve() == output.resolve():
        parser.error("Choose a separate output path.")
    build(arguments.original, output, folder, arguments.ffmpeg)
