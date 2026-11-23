"""History and human reports without a GPU: synthetic telemetry in, markdown + SVG out.
Run: python3 tests/report_test.py [keep-dir]   (keep-dir: write the sample there to look at it)"""
import csv, json, math, os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pilot import history, report  # noqa: E402

fails = 0


def check(cond, what):
    global fails
    print(("ok: " if cond else "FAIL: ") + what)
    fails += 0 if cond else 1


out = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
job = os.path.join(out, "s03_bench")
os.makedirs(job, exist_ok=True)

# telemetry of a 10-minute job: warm-up, a data-loading stall, then thermal throttling
with open(os.path.join(job, "gpu.csv"), "w") as f:
    f.write("# gpu 0: Tesla T4, 15360 MiB, power limit 70.0 W, max SM 1590 MHz\n")
    f.write("t,gpu,util,mem_util,mem_mb,sm_mhz,mem_mhz,temp_c,power_w,throttle\n")
    for t in range(0, 600, 3):
        stall = 150 <= t < 230
        hot = t >= 420
        util = 0 if t < 20 else (3 if stall else 96 + (t % 4))
        mem = 300 if t < 20 else min(13900, 6000 + t * 20)
        sm = 585 if util < 5 else (1110 + 60 * math.sin(t / 9) if hot else 1590)
        temp = min(86, 45 + t // 8)
        power = 12 if util < 5 else (61 if hot else 69.5)
        thr = 0x40 if hot else (0x4 if util > 50 else 0x1)
        f.write(f"{t},0,{util},{int(util * .4)},{mem},{int(sm)},5000,{temp},{power},{hex(thr)}\n")
with open(os.path.join(job, "results.csv"), "w") as f:
    f.write("variant,run,ms\n" + "".join(f"{v},{r},{b + r * 3}\n"
            for v, b in (("baseline", 41.2), ("tiled", 23.9), ("tiled_fp16", 14.1)) for r in (1, 2, 3)))
done = {"job": "s03_bench", "start": "2026-11-23T18:10:00+00:00", "end": "2026-11-23T18:20:00+00:00",
        "gpu": "Tesla T4, 15360 MiB, 535.104", "code": "code 7f3a9c1 tiled kernel (claude/tiling)",
        "exit": 0, "seconds": 600.0,
        "gpu_stats": {"samples": 600, "seconds": 600, "util_avg": 71, "util_max": 99, "idle_pct": 17,
                      "mem_peak_mb": 13900, "mem_total_mb": 15360, "sm_mhz_avg": 1402,
                      "sm_max_mhz": 1590, "sm_spread_pct": 23, "temp_max_c": 86, "power_avg_w": 55,
                      "power_limit_w": 70, "thermal_throttle_pct": 30, "power_cap_pct": 48,
                      "hw_slowdown_pct": 0, "other_procs": 0, "busy_at_start": 0,
                      "flags": ["mem peak 90%", "thermal throttle 30%", "SM clock unstable ±23%"]}}
log = "# colab-pilot: s03_bench on Tesla T4\nbuilding\n" + "".join(f"done: run {i}\n" for i in range(9))

md = report.job_report(job, done, log)
text = open(md).read()
check(os.path.exists(os.path.join(job, "charts", "gpu.svg")), "job chart written")
check("![GPU telemetry](charts/gpu.svg)" in text, "report embeds the chart by relative path")
check("thermal throttle 30%" in text and "13.6 of 15 GB" in text, "report: flags and readable numbers")
check("| tiled_fp16 | 3 | 23.1 |" in text, "report: results table")
check("this file is not for you" in text, "report says it is for humans")
svg = open(os.path.join(job, "charts", "gpu.svg")).read()
check(svg.startswith("<?xml") and "<svg" in svg and len(svg) < 400_000, f"svg is valid and small ({len(svg) // 1024} KB)")

# history: csv rows from .done dicts, compact table, history report
hpath = os.path.join(out, "history.csv")
if os.path.exists(hpath):
    os.remove(hpath)
for i, (sec, ex, util) in enumerate([(812, 0, 64), (790, 0, 66), (35, 1, None), (603, 0, 71), (600, 0, 71)]):
    d = dict(done, job=f"s0{i}_bench", seconds=sec, exit=ex, code=f"code abc{i}def msg (main)")
    if util is None:
        d.pop("gpu_stats"); d["error"] = "timeout"
    else:
        d["gpu_stats"] = dict(done["gpu_stats"], util_avg=util, flags=[] if i < 3 else done["gpu_stats"]["flags"])
    history.append(hpath, d)
rows = history.read(hpath)
check(len(rows) == 5 and rows[0]["commit"] == "abc0def" and rows[0]["branch"] == "main", "history rows parsed")
t = history.table(rows, last=3)
lines = t.splitlines()
check(len(lines) == 4 and lines[0].startswith("job") and "timeout" in t and "T4" in t
      and "Tesla" not in t, "compact table: header + 3 newest, short GPU name, error shown")
check(all(len(l) < 120 for l in lines), "table lines stay short")
hmd = report.history_report(rows, out)
htext = open(hmd).read()
check(os.path.exists(os.path.join(out, "charts", "history.svg")) and "![Job history]" in htext, "history chart + md")
check("❌ timeout" in htext and htext.index("s04_bench") < htext.index("s00_bench"), "history newest first, failures marked")
print("report: all checks passed" if not fails else f"report: {fails} FAILED")
sys.exit(1 if fails else 0)
