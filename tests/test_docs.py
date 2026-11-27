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
        text = re.sub(r"PRODUCT §\d+(?:\.\d+)?", "", _read(*doc))   # references into PRODUCT
        refs = set(re.findall(r"§(\d+(?:\.\d+)?)", text))
        if doc != ("docs", "DESIGN.md"):
            refs = set(re.findall(r"(?:DESIGN |Design: [^·\n]*?)§(\d+(?:\.\d+)?)", text)) | \
                   set(re.findall(r"§(\d+(?:\.\d+)?)", text))
        for r in refs:
            if doc == ("docs", "PRODUCT.md"):
                continue
            assert r in secs, f"{'/'.join(doc)} cites missing DESIGN §{r}"


def test_every_skill_section_named_in_product_exists():
    product, skill = _read("docs", "PRODUCT.md"), _read("skill", "meetproxy", "SKILL.md")
    table = product[product.index("### 1.2 What the skill contains"):product.index("## 2. ")]
    names = re.findall(r"^\| `([^`]+)`", table, re.M)
    sections = [n for n in names if "/" not in n]
    refs = [n for n in names if "/" in n]
    assert sections and refs, "PRODUCT §1.2 lists no skill sections or references"
    headings = re.findall(r"^## \d+\. (.+)$", skill, re.M)
    assert sections == headings, f"PRODUCT §1.2 {sections} != SKILL.md sections {headings}"
    for r in refs:
        assert os.path.exists(os.path.join(ROOT, "skill", "meetproxy", r)), r
        assert r in skill, f"SKILL.md never points to {r}"
    for pr in set(re.findall(r"\bPR-\d+\b", table)):
        assert re.search(rf"^\| \*\*{pr}\*\* \|", product, re.M), pr


def test_documents_point_to_each_other():
    product, design, road = _read("docs", "PRODUCT.md"), _read("docs", "DESIGN.md"), _read("ROADMAP.md")
    assert "(DESIGN.md)" in product and "ROADMAP.md" in product
    assert "(../skill/meetproxy/SKILL.md)" in product
    assert "Derived from [PRODUCT.md]" in design and "ROADMAP" in design
    assert "docs/PRODUCT.md" in road and "docs/DESIGN.md" in road


# ---- the skill loads progressively (PRODUCT §1.2) ----

def test_entry_skill_does_not_carry_a_route():
    skill = _read("skill", "meetproxy", "SKILL.md")
    for word in ("setup.sh", "meet ", "pip install", "GH_TOKEN", "colab_runner.ipynb", "$MEET_OUT"):
        assert word not in skill, f"route detail {word!r} belongs in a reference, not SKILL.md"
    assert len(skill.split()) < 1200, "the entry skill must stay short"


def test_mailbox_setup_is_only_in_the_mailbox_reference():
    ref = os.path.join(ROOT, "skill", "meetproxy", "reference")
    for f in os.listdir(ref):
        if f not in ("mailbox.md", "troubleshooting.md"):
            assert "setup.sh" not in open(os.path.join(ref, f)).read(), f
    assert "setup.sh" in open(os.path.join(ref, "mailbox.md")).read()


def test_every_route_says_what_exists_today():
    product = _read("docs", "PRODUCT.md")
    table = product[product.index("### 1.4 What exists today"):product.index("## 2. ")]
    skill = _read("skill", "meetproxy", "SKILL.md")
    assert "working and tested" in table and "instructions only" in table and "not shipped" in table
    assert skill.count("instructions only") >= 2 and "working, tested" in skill


def test_readme_leads_with_the_skill_and_truthful_routes():
    readme = _read("README.md")
    routes = readme.index("## What works today")
    assert routes < readme.index("## Install the skill") < readme.index("## Local GPU")
    assert readme.index("## Local GPU") < readme.index("## Colab via the mailbox")
    table = readme[routes:readme.index("## Install the skill")]
    assert table.count("instructions only") == 2 and "working and tested" in table
    local = readme[readme.index("## Local GPU"):readme.index("## Colab via the mailbox")]
    assert "GH_TOKEN" not in local and "notebook" in local.lower()  # says no notebook needed
