"""Add three offline video slides to the editable defense presentation."""

import argparse
import subprocess
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

P = "http://schemas.openxmlformats.org/presentationml/2006/main"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P14 = "http://schemas.microsoft.com/office/powerpoint/2010/main"
PKG = "http://schemas.openxmlformats.org/package/2006/relationships"
CT = "http://schemas.openxmlformats.org/package/2006/content-types"
MEDIA_REL = "http://schemas.microsoft.com/office/2007/relationships/media"
CLIPS = (
    ("01-overview", "Обзор программы"),
    ("02-intern-card", "Карточка стажёра"),
    ("03-signal-evidence", "Обоснование сигнала"),
)

for prefix, ns in (("p", P), ("a", A), ("r", R), ("p14", P14)):
    ET.register_namespace(prefix, ns)


def xml(element):
    namespace = element.tag.split("}")[0][1:]
    if namespace in (CT, PKG):
        ET.register_namespace("", namespace)
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def add(parent, name, **attributes):
    return ET.SubElement(parent, f"{{{P}}}{name}", attributes)


def condition(node, *, event=None, delay="0", shape=None, timeline=None):
    conditions = add(node, "stCondLst")
    trigger = add(conditions, "cond", delay=delay)
    if event:
        trigger.set("evt", event)
    if shape:
        add(add(trigger, "tgtEl"), "spTgt", spid=shape)
    if timeline:
        add(trigger, "tn", val=timeline)
    return conditions


def next_on(container, tag, event):
    trigger = add(add(container, tag), "cond", evt=event, delay="0")
    add(add(trigger, "tgtEl"), "sldTgt")


def timed_child(node, id_, **attributes):
    children = add(node, "childTnLst")
    return add(add(children, "par"), "cTn", id=id_, **attributes)


def command(node, target, id_, action, duration):
    call = add(add(node, "childTnLst"), "cmd", type="call", cmd=action)
    behavior = add(call, "cBhvr")
    add(behavior, "cTn", id=id_, dur=duration, fill="hold")
    add(add(behavior, "tgtEl"), "spTgt", spid=target)


def video_timing(slide, target="2"):
    # PowerPoint uses a main-sequence media call for automatic start.
    nodes = add(add(slide, "timing"), "tnLst")
    root = add(add(nodes, "par"), "cTn", id="1", dur="indefinite", restart="never", nodeType="tmRoot")
    children = add(root, "childTnLst")
    sequence = add(children, "seq", concurrent="1", nextAc="seek")
    main = add(sequence, "cTn", id="2", dur="indefinite", nodeType="mainSeq")
    group = timed_child(main, "3", fill="hold")
    triggers = condition(group, event="onBegin", timeline="2")
    triggers.insert(0, ET.Element(f"{{{P}}}cond", delay="indefinite"))
    parallel = timed_child(group, "4", fill="hold")
    condition(parallel)
    effect = timed_child(parallel, "5", presetID="1", presetClass="mediacall",
                         presetSubtype="0", fill="hold", nodeType="afterEffect")
    condition(effect)
    command(effect, target, "6", "playFrom(0.0)", "10000")
    next_on(sequence, "prevCondLst", "onPrev")
    next_on(sequence, "nextCondLst", "onNext")

    media = add(add(children, "video"), "cMediaNode", vol="0", mute="1")
    playback = add(media, "cTn", id="7", repeatCount="indefinite", fill="hold", display="0")
    condition(playback, delay="indefinite")
    add(add(media, "tgtEl"), "spTgt", spid=target)

    # Clicking the video also toggles playback independently of slide navigation.
    interactive = add(children, "seq", concurrent="1", nextAc="seek")
    click = add(interactive, "cTn", id="8", restart="whenNotActive", fill="hold",
                evtFilter="cancelBubble", nodeType="interactiveSeq")
    condition(click, event="onClick", shape=target)
    add(add(click, "endSync", evt="end", delay="0"), "rtn", val="all")
    group = timed_child(click, "9", fill="hold")
    condition(group)
    parallel = timed_child(group, "10", fill="hold")
    condition(parallel)
    toggle = timed_child(parallel, "11", presetID="2", presetClass="mediacall",
                         presetSubtype="0", fill="hold", nodeType="clickEffect")
    condition(toggle)
    command(toggle, target, "12", "togglePause", "1")
    trigger = add(add(interactive, "nextCondLst"), "cond", evt="onClick", delay="0")
    add(add(trigger, "tgtEl"), "spTgt", spid=target)


def video_slide(title, width, height):
    slide = ET.fromstring(f"""
    <p:sld xmlns:p="{P}" xmlns:a="{A}" xmlns:r="{R}" xmlns:p14="{P14}" showMasterSp="0">
      <p:cSld><p:spTree>
        <p:nvGrpSpPr><p:cNvPr id="1" name=""/><p:cNvGrpSpPr/><p:nvPr/></p:nvGrpSpPr>
        <p:grpSpPr/>
        <p:pic>
          <p:nvPicPr>
            <p:cNvPr id="2" name=""><a:hlinkClick r:id="" action="ppaction://media"/></p:cNvPr>
            <p:cNvPicPr><a:picLocks noChangeAspect="1"/></p:cNvPicPr>
            <p:nvPr>
              <a:videoFile r:link="rId2"/>
              <p:extLst><p:ext uri="{{DAA4B4D4-6D71-4841-9C94-3DE7FCFB9230}}">
                <p14:media r:embed="rId1"/>
              </p:ext></p:extLst>
            </p:nvPr>
          </p:nvPicPr>
          <p:blipFill><a:blip r:embed="rId4"/><a:stretch><a:fillRect/></a:stretch></p:blipFill>
          <p:spPr>
            <a:xfrm><a:off x="0" y="0"/><a:ext cx="{width}" cy="{height}"/></a:xfrm>
            <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
          </p:spPr>
        </p:pic>
      </p:spTree></p:cSld>
      <p:clrMapOvr><a:masterClrMapping/></p:clrMapOvr>
      <p:transition advClick="1"/>
    </p:sld>
    """)
    slide.find(f"{{{P}}}cSld").set("name", title)
    slide.find(f".//{{{P}}}nvPicPr/{{{P}}}cNvPr").set("name", title)
    video_timing(slide)
    return xml(slide)


def relationship(root, id_, type_, target):
    ET.SubElement(root, f"{{{PKG}}}Relationship", Id=id_, Type=type_, Target=target)


def poster(movie, at):
    return subprocess.check_output([
        "ffmpeg", "-v", "error", "-ss", at, "-i", str(movie), "-frames:v", "1",
        "-c:v", "png", "-f", "image2pipe", "pipe:1",
    ])


def build(original, folder, output):
    with ZipFile(original) as source, ZipFile(output, "w", ZIP_DEFLATED) as result:
        presentation_part = "ppt/presentation.xml"
        relationships_part = "ppt/_rels/presentation.xml.rels"
        types_part = "[Content_Types].xml"
        properties_part = "docProps/app.xml"
        presentation = ET.fromstring(source.read(presentation_part))
        relationships = ET.fromstring(source.read(relationships_part))
        content_types = ET.fromstring(source.read(types_part))
        properties = ET.fromstring(source.read(properties_part))
        slide_ids = presentation.find(f"{{{P}}}sldIdLst")
        size = presentation.find(f"{{{P}}}sldSz")
        assert int(size.get("cx")) * 9 == int(size.get("cy")) * 16
        assert len(slide_ids) == 6
        video_type = ET.Element(f"{{{CT}}}Default", Extension="mp4", ContentType="video/mp4")
        content_types.insert(0, video_type)
        video_parts = {}
        for i, (stem, title) in enumerate(CLIPS):
            number = 7 + i
            part = f"ppt/slides/slide{number}.xml"
            rid = f"rIdScreencast{number}"
            movie = folder / (stem + ".mp4")
            image = stem + "-poster.png"
            clip_rel = ET.Element(f"{{{PKG}}}Relationships")
            relationship(clip_rel, "rId1", MEDIA_REL, f"../media/{movie.name}")
            relationship(clip_rel, "rId2", R + "/video", f"../media/{movie.name}")
            relationship(clip_rel, "rId3", R + "/slideLayout", "../slideLayouts/slideLayout6.xml")
            relationship(clip_rel, "rId4", R + "/image", f"../media/{image}")
            video_parts[part] = video_slide(title, size.get("cx"), size.get("cy"))
            video_parts[f"ppt/slides/_rels/slide{number}.xml.rels"] = xml(clip_rel)
            video_parts[f"ppt/media/{movie.name}"] = movie
            video_parts[f"ppt/media/{image}"] = poster(movie, ("0", "5", "6")[i])
            slide_id = ET.Element(f"{{{P}}}sldId", {"id": str(262 + i), f"{{{R}}}id": rid})
            slide_ids.insert(2 + i, slide_id)
            relationship(relationships, rid, R + "/slide", f"slides/slide{number}.xml")
            ET.SubElement(content_types, f"{{{CT}}}Override", PartName="/" + part,
                          ContentType="application/vnd.openxmlformats-officedocument.presentationml.slide+xml")
        for element in properties:
            if element.tag.endswith("}Slides"):
                element.text = str(len(slide_ids))
        updated = {
            presentation_part: xml(presentation),
            relationships_part: xml(relationships),
            types_part: xml(content_types),
            properties_part: xml(properties),
        }
        for item in source.infolist():
            data = updated[item.filename] if item.filename in updated else source.read(item)
            result.writestr(item, data)
        for name, data in video_parts.items():
            if isinstance(data, Path):
                result.write(data, name, compress_type=ZIP_STORED)
            else:
                result.writestr(name, data)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    args = parser.parse_args()
    folder = Path(__file__).resolve().parents[1]
    build(args.original, folder, folder / "mgts-defense-with-screencasts.pptx")
