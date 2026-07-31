"""Tree guarantees: nesting by level, summaries from content, honest fallback."""

from refinery.chunking import build_sections, chunk
from refinery.models.bbox import BBox
from refinery.models.extracted import Element, ElementKind
from refinery.models.profile import DocumentProfile
from refinery.pageindex import build_tree, extractive_summary


def _text(y, content, size=11.0, page=1):
    return Element(kind=ElementKind.TEXT, source_rung="A", text=content,
                   font_size=size, bbox=BBox(x0=72, y0=y, x1=500, y1=y + 14, page=page))


def _profile():
    return DocumentProfile(doc_id="d", source_name="report.pdf", pages=[])


def _tree(elements):
    sections = build_sections(elements)
    ldus, _ = chunk(elements, sections, max_tokens=200, caption_proximity=40)
    return build_tree(_profile(), sections, ldus)


def test_subsections_nest_under_parents():
    tree = _tree([
        _text(40, "1 Finance", size=18.0),
        _text(70, "Overview of the year in numbers."),
        _text(100, "1.1 Revenue", size=14.0),
        _text(130, "Revenue reached record levels in the fourth quarter."),
        _text(160, "2 Operations", size=18.0),
        _text(190, "Operations expanded to two new regions."),
    ])
    assert [n.title for n in tree.child_sections] == ["1 Finance", "2 Operations"]
    assert tree.child_sections[0].child_sections[0].title == "1.1 Revenue"


def test_summary_and_entities_come_from_section_content():
    tree = _tree([
        _text(40, "1 Findings", size=18.0),
        _text(70, "The Audit Services Corporation reviewed the accounts. "
                  "No material misstatements were found."),
    ])
    node = tree.child_sections[0]
    assert node.summary.startswith("The Audit Services Corporation")
    assert "Audit Services Corporation" in node.key_entities


def test_extractive_summary_takes_first_two_sentences():
    text = "One here. Two here. Three should not appear."
    assert extractive_summary(text) == "One here. Two here."


def test_data_types_reflect_chunks():
    tree = _tree([_text(40, "1 Notes", size=18.0), _text(70, "Body prose.")])
    assert tree.child_sections[0].data_types_present == ["text"]
