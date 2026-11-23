"""History rows and table; human reports and charts, including their failure modes."""
import builtins, os, sys

import pytest

from pilot import history as H, report as P


def done(job="j1", **kw):
    d = {"job": job, "end": "2026-11-23T18:00:00+00:00", "gpu": "NVIDIA L4, 23034 MiB, 550",
         "code": "code abc1234 fix tiling (claude/x)", "seconds": 12.5, "exit": 0,
         "gpu_stats": {"util_avg": 88, "mem_peak_mb": 4000, "flags": ["idle 31%"]}}
    d.update(kw)
    return d


def test_row_parsing():
    r = H.row(done())
    assert r["commit"] == "abc1234" and r["branch"] == "claude/x" and r["gpu"] == "NVIDIA L4"
    assert r["util_avg"] == 88 and r["flags"] == "idle 31%"
    r = H.row({"job": "x", "code": "workdir is not a git repo"})
    assert r["commit"] == "" and r["util_avg"] == "" and r["flags"] == ""


def test_append_read_table(tmp_path):
    p = str(tmp_path / "h.csv")
    assert H.read(p) == [] and H.table([]) == "no finished jobs yet"
    H.append(p, done("a"))
    H.append(p, done("b", exit=1, error="timeout", gpu_stats=None))
    H.append(p, done("c", gpu_stats={"util_avg": 99, "flags": []}))
    rows = H.read(p)
    assert [r["job"] for r in rows] == ["a", "b", "c"]
    assert open(p).read().count("job,end") == 1                       # header once
    t = H.table(rows, last=0)
    lines = t.splitlines()
    assert len(lines) == 4 and "L4" in lines[1] and "NVIDIA" not in t
    assert "timeout" in lines[2] and lines[3].rstrip().endswith("ok")
    assert len(H.table(rows, last=1).splitlines()) == 2


# ---------- report ----------

GPU_CSV = """# gpu 0: Tesla T4, 15360 MiB, power limit 70.0 W, max SM 1590 MHz
# comment
t,gpu,util,mem_util,mem_mb,sm_mhz,mem_mhz,temp_c,power_w,throttle
0.0,0,0,0,300,585,5000,45,12,0x1
2.0,0,97,40,6000,1590,5000,60,69,0x4
5.0,0,97,40,6000,1100,5000,84,61,0x40
8.0,0,97,40,6000,1100,5000,85,61,0x48
9.0,0,97,40,6000,1590,5000,80,69,
9.5,0,,40,6000,1590,5000,80,69,
"""


def test_read_gpu_csv(tmp_path):
    p = tmp_path / "gpu.csv"
    p.write_text(GPU_CSV)
    meta, rows = P.read_gpu_csv(str(p))
    r = rows[0]
    assert len(meta) == 2 and len(r) == 6 and r[5]['util'] is None and r[2]["throttle"] == 0x40 and r[4]["throttle"] is None
    assert P._static(meta) == {"name": "Tesla T4", "mem_total_mb": 15360.0,
                               "power_limit_w": 70.0, "sm_max_mhz": 1590.0}
    assert P.read_gpu_csv(str(tmp_path / "missing.csv")) == ([], {})
    assert P._spans(r, P.THERMAL, 10) == [(5.0, 9.0)]
    assert P._spans(r[:4], P.HW_SLOW, 10) == [(8.0, 10)]
    xs, ys = P._steps(r, "util", 12)
    assert xs[-1] == 12 and ys[-1] == 97


def test_static_unknown_values():
    assert P._static(["gpu 0: X, None MiB, power limit None W, max SM None MHz"])["mem_total_mb"] is None
    assert P._static(["nothing here"]) == {}


def test_gpu_chart_and_empty(tmp_path):
    (tmp_path / "gpu.csv").write_text(GPU_CSV)
    assert P.gpu_chart(str(tmp_path / "gpu.csv"), str(tmp_path / "g.svg"), seconds=10, title="x")
    assert (tmp_path / "g.svg").read_text().count("<svg") == 1
    assert P.gpu_chart(str(tmp_path / "none.csv"), str(tmp_path / "n.svg")) is False
    assert P.history_chart([], str(tmp_path / "h.svg")) is False


def test_job_report_full(tmp_path):
    j = tmp_path / "j1"
    j.mkdir()
    (j / "gpu.csv").write_text(GPU_CSV)
    (j / "results.csv").write_text("v,ms\n" + "".join(f"x{i},{i}\n" for i in range(40)))
    d = done(gpu_stats={"util_avg": 80, "util_max": 99, "idle_pct": 10, "mem_peak_mb": 6000,
                        "mem_total_mb": 15360, "sm_mhz_avg": 1400, "sm_spread_pct": 12,
                        "sm_max_mhz": 1590, "temp_max_c": 85, "power_avg_w": 60,
                        "power_limit_w": 70, "thermal_throttle_pct": 30, "power_cap_pct": 40,
                        "other_procs": 0, "flags": ["thermal throttle 30%"]})
    md = open(P.job_report(str(j), d, "line1\n\nline2 | pipe\n")).read()
    assert "✅ exit 0" in md and "abc1234 fix tiling (claude/x)" in md and "2026-11-23 18:00 UTC" in md
    assert "⚠️ **GPU:** thermal throttle 30%" in md and "![GPU telemetry](charts/gpu.svg)" in md
    assert "5.9 of 15 GB" in md and "(±12%)" in md
    assert "*10 more rows in [results.csv](results.csv)*" in md and "| x29 | 29 |" in md
    assert "line2 | pipe" in md                                       # log kept verbatim in code block


def test_job_report_minimal_failed(tmp_path):
    j = tmp_path / "j2"
    j.mkdir()
    md = open(P.job_report(str(j), {"job": "j2", "exit": 3, "error": "timeout", "end": "bad"})).read()
    assert "❌ exit 3" in md and "timeout" in md and "charts/gpu.svg" not in md and "## GPU" not in md


def test_job_report_healthy_gpu_line(tmp_path):
    j = tmp_path / "j3"
    j.mkdir()
    md = open(P.job_report(str(j), done(gpu_stats={"util_avg": 99, "flags": []}))).read()
    assert "🟢 **GPU:** nothing unusual" in md


def test_history_report_links_existing_reports(tmp_path):
    rows = []
    p = str(tmp_path / "h.csv")
    for i in range(3):
        H.append(p, done(f"s{i}", exit=0 if i != 1 else 2))
    os.makedirs(tmp_path / "s2")
    (tmp_path / "s2" / "report.md").write_text("x")
    md = open(P.history_report(H.read(p), str(tmp_path))).read()
    assert "[s2](s2/report.md)" in md and "| s0 |" in md and "❌ 2" in md
    assert md.index("s2") < md.index("s0")
    assert (tmp_path / "charts" / "history.svg").exists()


def test_no_matplotlib(monkeypatch, tmp_path):
    real = builtins.__import__

    def fake(name, *a, **k):
        if name.startswith("matplotlib"):
            raise ImportError("no matplotlib")
        return real(name, *a, **k)
    monkeypatch.setattr(builtins, "__import__", fake)
    for m in [m for m in sys.modules if m.startswith("matplotlib")]:
        monkeypatch.delitem(sys.modules, m)
    with pytest.raises(P.NoMatplotlib, match="pip install matplotlib"):
        P.gpu_chart(str(tmp_path / "x.csv"), str(tmp_path / "x.svg"))
