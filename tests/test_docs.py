"""Docs stay navigable: every relative link in the markdown files points at a file that exists,
and the roadmap is linked from the README."""
import os, re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCS = [os.path.join(dp, f) for dp, dn, fs in os.walk(ROOT) for f in fs
        if f.endswith(".md") and "/." not in dp.replace(ROOT, "") and "node_modules" not in dp]


@pytest.mark.parametrize("md", DOCS, ids=lambda p: os.path.relpath(p, ROOT))
def test_relative_links_exist(md):
    text = open(md).read()
    text = re.sub(r"```.*?```", "", text, flags=re.S)        # links inside code blocks are examples
    for target in re.findall(r"\]\(([^)\s]+)\)", text):
        if re.match(r"[a-z]+:", target) or target.startswith("#") or "<" in target:
            continue
        path = os.path.normpath(os.path.join(os.path.dirname(md), target.split("#")[0]))
        assert os.path.exists(path), f"{os.path.relpath(md, ROOT)} links to missing {target}"


def test_roadmap_is_linked_and_milestones_are_consecutive():
    assert "[Roadmap](ROADMAP.md)" in open(os.path.join(ROOT, "README.md")).read()
    road = open(os.path.join(ROOT, "ROADMAP.md")).read()
    found = sorted({int(m) for m in re.findall(r"\bM(\d+)\b", road)})
    assert found and found == list(range(found[0], found[-1] + 1)), f"gaps in milestones: {found}"
    assert found[0] == 0


# ---- product -> design -> roadmap chain ----

def _read(*p):
    return open(os.path.join(ROOT, *p)).read()


def _sections(design):
    return {m for m in re.findall(r"^##+ (\d+(?:\.\d+)?)\.? ", design, re.M)}


def test_every_requirement_is_designed_and_planned():
    product, design, road = _read("docs", "PRODUCT.md"), _read("docs", "DESIGN.md"), _read("ROADMAP.md")
    defined = re.findall(r"^\| \*\*(PR-\d+)\*\* \|", product, re.M)
    assert defined and defined == sorted(set(defined)), "PR ids must be unique and in order"
    trace = design[design.index("### 1.1 Requirements → design"):design.index("## 2. Principles")]
    for pr in defined:
        assert pr in trace, f"{pr} has no row in DESIGN §1.1"
        assert pr in road, f"{pr} is not served by any roadmap milestone"


def test_no_reference_to_an_unknown_requirement():
    product = _read("docs", "PRODUCT.md")
    defined = set(re.findall(r"^\| \*\*(PR-\d+)\*\* \|", product, re.M))
    for doc in (("docs", "DESIGN.md"), ("ROADMAP.md",), ("docs", "PRODUCT.md")):
        for pr in set(re.findall(r"\bPR-\d+\b", _read(*doc))):
            assert pr in defined, f"{'/'.join(doc)} cites undefined {pr}"


def test_design_section_references_exist():
    design = _read("docs", "DESIGN.md")
    secs = _sections(design)
    for doc in (("docs", "DESIGN.md"), ("ROADMAP.md",), ("docs", "spikes", "colab-cli.md")):
        text = _read(*doc)
        refs = set(re.findall(r"§(\d+(?:\.\d+)?)", text))
        if doc != ("docs", "DESIGN.md"):
            refs = set(re.findall(r"(?:DESIGN |Design: [^·\n]*?)§(\d+(?:\.\d+)?)", text)) | \
                   set(re.findall(r"§(\d+(?:\.\d+)?)", text))
        for r in refs:
            if doc == ("docs", "PRODUCT.md"):
                continue
            assert r in secs, f"{'/'.join(doc)} cites missing DESIGN §{r}"


def test_documents_point_to_each_other():
    product, design, road = _read("docs", "PRODUCT.md"), _read("docs", "DESIGN.md"), _read("ROADMAP.md")
    assert "(DESIGN.md)" in product and "ROADMAP.md" in product
    assert "Derived from [PRODUCT.md]" in design and "ROADMAP" in design
    assert "docs/PRODUCT.md" in road and "docs/DESIGN.md" in road
