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
