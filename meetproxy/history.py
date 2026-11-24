"""Run history: one CSV line per finished job in out/history.csv, kept forever on branch `meetproxy`.

Written by the runner only. Read by `meet history` (compact table for the agent) and by
report.history_report (charts for the human)."""
import csv, io, os, re

COLUMNS = ["job", "end", "gpu", "commit", "branch", "seconds", "exit", "error",
           "util_avg", "mem_peak_mb", "flags"]


def row(done):
    code = done.get("code", "")
    m = re.match(r"code (\S+) .*\((.*)\)", code)
    st = done.get("gpu_stats") or {}
    return {
        "job": done.get("job", ""), "end": done.get("end", ""),
        "gpu": (done.get("gpu") or "").split(",")[0].strip(),
        "commit": m.group(1) if m else "", "branch": m.group(2) if m else "",
        "seconds": done.get("seconds", ""), "exit": done.get("exit", ""),
        "error": done.get("error", ""),
        "util_avg": st.get("util_avg", ""), "mem_peak_mb": st.get("mem_peak_mb", ""),
        "flags": " · ".join(st.get("flags", [])),
    }


def append(path, done):
    new = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new:
            w.writeheader()
        w.writerow(row(done))


def read(path):
    try:
        with open(path, newline="") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def table(rows, last=10):
    """Compact fixed-width table, one line per job, newest last."""
    rows = rows[-last:] if last else rows
    if not rows:
        return "no finished jobs yet"
    cols = [("job", "job"), ("gpu", "gpu"), ("commit", "commit"), ("seconds", "s"),
            ("exit", "exit"), ("util_avg", "util%"), ("flags", "flags")]

    def cell(r, k):
        v = r.get(k, "") or ""
        if k == "gpu":
            v = v.replace("NVIDIA ", "").replace("Tesla ", "")
        if k == "flags":
            v = v or ("ok" if r.get("util_avg") else "")
            if r.get("error"):
                v = (r["error"] + (" · " + v if v else ""))
        return str(v)

    data = [[cell(r, k) for k, _ in cols] for r in rows]
    widths = [max(len(h), *(len(d[i]) for d in data)) for i, (_, h) in enumerate(cols)]
    out = io.StringIO()
    fmt = lambda vals: "  ".join(v.ljust(w) for v, w in zip(vals, widths)).rstrip()
    out.write(fmt([h for _, h in cols]) + "\n")
    for d in data:
        out.write(fmt(d) + "\n")
    return out.getvalue().rstrip()
