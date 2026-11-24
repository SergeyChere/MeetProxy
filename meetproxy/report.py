"""Human-readable reports: report.md + SVG charts for one job, history.md for all of them.

For people, not for the agent: made on request only (`# charts: on` in a job, `meet report`),
rendered with matplotlib on the GPU side, so they cost the agent no tokens. GitHub renders the
markdown and the SVGs in place (branch `meetproxy`, folder out/), on a phone too.
"""
import csv, io, json, os
from datetime import datetime

BLUE, PURPLE, GREEN, AMBER, RED, GREY, INK = (
    "#3b6fd8", "#7a5af0", "#1f9d6b", "#e0a020", "#d64545", "#9a948a", "#2b2925")
THERMAL, POWER, HW_SLOW = 0x20 | 0x40, 0x04 | 0x80, 0x08


class NoMatplotlib(RuntimeError):
    pass


def _plt():
    try:
        import logging
        import matplotlib
        logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        raise NoMatplotlib("charts need matplotlib: pip install matplotlib")
    plt.rcParams.update({
        "font.family": ["Inter", "Helvetica", "Arial", "DejaVu Sans"],
        "font.size": 10, "axes.titlesize": 11, "axes.titleweight": "bold",
        "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
        "axes.edgecolor": "#c9c3b8", "axes.labelcolor": INK, "xtick.color": "#6b665e",
        "ytick.color": "#6b665e", "axes.grid": True, "grid.color": "#ece8e1", "grid.linewidth": 0.8,
        "svg.fonttype": "none", "figure.facecolor": "white", "axes.facecolor": "white",
        "legend.frameon": False, "legend.fontsize": 9, "axes.axisbelow": True,
    })
    return plt


# ---------- data ----------

def read_gpu_csv(path):
    """-> (meta lines, {gpu index: [row dicts]}) with numbers parsed; throttle as int."""
    meta, rows, cols = [], {}, None
    try:
        f = open(path)
    except FileNotFoundError:
        return meta, rows
    with f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#"):
                meta.append(line[1:].strip())
                continue
            if cols is None:
                cols = line.split(",")
                continue
            vals = line.split(",")
            r = {}
            for c, v in zip(cols, vals):
                if v == "":
                    r[c] = None
                elif c == "throttle":
                    r[c] = int(v, 16) if v.startswith("0x") else int(float(v))
                else:
                    r[c] = float(v)
            rows.setdefault(r.get("gpu", 0), []).append(r)
    return meta, rows


def _steps(rows, key, end):
    """Rows are written only on change: extend each value until the next row (and to `end`)."""
    xs, ys = [], []
    for r in rows:
        if r.get(key) is None:
            continue
        xs.append(r["t"])
        ys.append(r[key])
    if xs and end and end > xs[-1]:
        xs.append(end)
        ys.append(ys[-1])
    return xs, ys


def _spans(rows, mask, end):
    """Time intervals where (throttle & mask) is set."""
    spans, start = [], None
    for i, r in enumerate(rows):
        on = r.get("throttle") is not None and r["throttle"] & mask
        if on and start is None:
            start = r["t"]
        if not on and start is not None:
            spans.append((start, r["t"]))
            start = None
    if start is not None:
        spans.append((start, end or rows[-1]["t"]))
    return spans


def _static(meta):
    """Parse '# gpu 0: Tesla T4, 15360 MiB, power limit 70.0 W, max SM 1590 MHz'."""
    import re
    for m in meta:
        g = re.match(r"gpu \S+: (.*?), ([\d.]+|None) MiB, power limit ([\d.]+|None) W, "
                     r"max SM ([\d.]+|None) MHz", m)
        if g:
            num = lambda s: None if s == "None" else float(s)
            return {"name": g.group(1), "mem_total_mb": num(g.group(2)),
                    "power_limit_w": num(g.group(3)), "sm_max_mhz": num(g.group(4))}
    return {}


# ---------- charts ----------

def gpu_chart(gpu_csv, svg_path, seconds=None, title=None):
    plt = _plt()
    meta, by_gpu = read_gpu_csv(gpu_csv)
    if not by_gpu:
        return False
    rows = next(iter(by_gpu.values()))
    st = _static(meta)
    end = seconds or rows[-1]["t"]
    fig, axes = plt.subplots(4, 1, figsize=(10, 9.2), sharex=True,
                             gridspec_kw={"hspace": 0.45})
    if title:
        fig.suptitle(title, x=0.06, ha="left", fontsize=14, fontweight="bold", color=INK)

    def shade(ax):
        for a, b in _spans(rows, THERMAL, end):
            ax.axvspan(a, b, color=RED, alpha=0.12, lw=0)
        for a, b in _spans(rows, HW_SLOW, end):
            ax.axvspan(a, b, color=AMBER, alpha=0.12, lw=0)

    ax = axes[0]
    x, y = _steps(rows, "util", end)
    ax.fill_between(x, y, step="post", color=BLUE, alpha=0.18, lw=0)
    ax.step(x, y, where="post", color=BLUE, lw=1.6, label="GPU")
    x, y = _steps(rows, "mem_util", end)
    if x:
        ax.step(x, y, where="post", color=PURPLE, lw=1.2, label="memory bus")
    ax.set_ylim(0, 105)
    ax.set_title("Utilization, %")
    ax.legend(loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2, borderaxespad=0.2)
    shade(ax)

    ax = axes[1]
    x, y = _steps(rows, "mem_mb", end)
    y = [v / 1024 for v in y]
    ax.fill_between(x, y, step="post", color=PURPLE, alpha=0.15, lw=0)
    ax.step(x, y, where="post", color=PURPLE, lw=1.6)
    if st.get("mem_total_mb"):
        tot = st["mem_total_mb"] / 1024
        ax.axhline(tot, color=GREY, ls="--", lw=1)
        ax.text(0.995, tot, f" total {tot:.0f} GB", transform=ax.get_yaxis_transform(),
                ha="right", va="bottom", color=GREY, fontsize=9)
        ax.set_ylim(0, tot * 1.12)
    ax.set_title("Memory used, GB")

    ax = axes[2]
    x, y = _steps(rows, "sm_mhz", end)
    ax.step(x, y, where="post", color=GREEN, lw=1.6, label="SM")
    if st.get("sm_max_mhz"):
        ax.axhline(st["sm_max_mhz"], color=GREY, ls="--", lw=1)
        ax.text(0.995, st["sm_max_mhz"], f" max {st['sm_max_mhz']:.0f}",
                transform=ax.get_yaxis_transform(), ha="right", va="bottom", color=GREY, fontsize=9)
    ax.set_ylim(bottom=0)
    ax.set_title("SM clock, MHz   (red: thermal throttling, amber: HW slowdown)")
    shade(ax)

    ax = axes[3]
    x, y = _steps(rows, "temp_c", end)
    ax.step(x, y, where="post", color=RED, lw=1.6, label="temperature °C")
    ax.set_title("Temperature °C  ·  power W")
    x2, y2 = _steps(rows, "power_w", end)
    if x2:
        ax2 = ax.twinx()
        ax2.step(x2, y2, where="post", color=AMBER, lw=1.3, label="power W")
        ax2.spines["right"].set_visible(True)
        ax2.grid(False)
        if st.get("power_limit_w"):
            ax2.axhline(st["power_limit_w"], color=AMBER, ls=":", lw=1)
        ax2.set_ylim(bottom=0)
        h1, l1 = ax.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax.legend(h1 + h2, l1 + l2, loc="lower right", bbox_to_anchor=(1, 1.0), ncol=2,
                  borderaxespad=0.2)
    ax.set_xlabel("seconds since job start")
    ax.set_xlim(0, max(end, 1))
    fig.savefig(svg_path, format="svg", bbox_inches="tight")
    plt.close(fig)
    return True


def history_chart(rows, svg_path, last=50):
    plt = _plt()
    rows = rows[-last:]
    if not rows:
        return False
    fig, ax = plt.subplots(figsize=(10, 4.2))
    xs = list(range(len(rows)))
    secs = [float(r["seconds"] or 0) for r in rows]
    ok = [str(r.get("exit")) == "0" for r in rows]
    ax.bar(xs, secs, color=[GREEN if o else RED for o in ok], alpha=0.85, width=0.7)
    ax.set_ylabel("seconds")
    ax.set_title("Job time (green: exit 0, red: failed)  ·  GPU utilization")
    labels = [f"{r['job']}\n{r.get('commit') or ''}" for r in rows]
    step = max(1, len(rows) // 25)
    ax.set_xticks(xs[::step])
    ax.set_xticklabels(labels[::step], rotation=60, ha="right", fontsize=8)
    util = [(i, float(r["util_avg"])) for i, r in enumerate(rows) if r.get("util_avg")]
    if util:
        ax2 = ax.twinx()
        ax2.plot([i for i, _ in util], [u for _, u in util], color=BLUE, marker="o", ms=3.5, lw=1.4)
        ax2.set_ylim(0, 105)
        ax2.set_ylabel("util avg, %", color=BLUE)
        ax2.spines["right"].set_visible(True)
        ax2.grid(False)
    fig.savefig(svg_path, format="svg", bbox_inches="tight")
    plt.close(fig)
    return True


# ---------- markdown ----------

def _md_table(header, rows):
    esc = lambda v: str(v).replace("|", "\\|")
    out = ["| " + " | ".join(esc(h) for h in header) + " |",
           "|" + "|".join("---" for _ in header) + "|"]
    out += ["| " + " | ".join(esc(v) for v in r) + " |" for r in rows]
    return "\n".join(out)


def _when(iso):
    try:
        return datetime.fromisoformat(iso).strftime("%Y-%m-%d %H:%M UTC")
    except (TypeError, ValueError):
        return iso or ""


def job_report(job_dir, done, log_text=None):
    """Write job_dir/report.md and job_dir/charts/gpu.svg. job_dir holds gpu.csv/results.csv."""
    os.makedirs(os.path.join(job_dir, "charts"), exist_ok=True)
    name = done.get("job", os.path.basename(job_dir.rstrip("/")))
    st = done.get("gpu_stats") or {}
    has_chart = gpu_chart(os.path.join(job_dir, "gpu.csv"),
                          os.path.join(job_dir, "charts", "gpu.svg"),
                          seconds=done.get("seconds"), title=None)
    code = (done.get("code") or "").replace("code ", "", 1)
    ok = done.get("exit") == 0
    lines = [f"# {name}", "",
             f"**{'✅ exit 0' if ok else '❌ exit ' + str(done.get('exit'))}**"
             f"{' · ' + done['error'] if done.get('error') else ''}"
             f" · {done.get('seconds', '?')} s · {(done.get('gpu') or '').split(',')[0]}"
             f" · {code} · {_when(done.get('end'))}", ""]
    if st:
        fl = st.get("flags") or []
        lines += [("> ⚠️ **GPU:** " + " · ".join(fl)) if fl else "> 🟢 **GPU:** nothing unusual", ""]
    if has_chart:
        lines += ["![GPU telemetry](charts/gpu.svg)", ""]
    if st:
        pct = lambda k: f"{st[k]}%" if k in st else "—"
        mem = (f"{st['mem_peak_mb'] / 1024:.1f} of {st['mem_total_mb'] / 1024:.0f} GB"
               if st.get("mem_total_mb") and "mem_peak_mb" in st else "—")
        rows = [["GPU utilization (avg / max)", f"{pct('util_avg')} / {pct('util_max')}"],
                ["Time GPU was idle", pct("idle_pct")],
                ["Memory peak", mem],
                ["SM clock under load", f"{st.get('sm_mhz_avg', '—')} MHz"
                 + (f" (±{st['sm_spread_pct']}%)" if "sm_spread_pct" in st else "")
                 + (f", max {st['sm_max_mhz']}" if st.get("sm_max_mhz") else "")],
                ["Temperature max", f"{st.get('temp_max_c', '—')} °C"],
                ["Power avg / limit", f"{st.get('power_avg_w', '—')} / {st.get('power_limit_w', '—')} W"],
                ["Thermal throttling", pct("thermal_throttle_pct")],
                ["Power capped", pct("power_cap_pct")],
                ["Other GPU processes", str(st.get("other_procs", 0))]]
        lines += ["## GPU", "", _md_table(["", ""], rows), ""]
    res = os.path.join(job_dir, "results.csv")
    if os.path.exists(res):
        with open(res, newline="") as f:
            data = list(csv.reader(f))
        if data:
            body = data[1:31]
            lines += ["## Results", "", _md_table(data[0], body), ""]
            if len(data) > 31:
                lines += [f"*{len(data) - 31} more rows in [results.csv](results.csv)*", ""]
    if log_text:
        tail = [l for l in log_text.splitlines() if l.strip()][-25:]
        lines += ["## Log (last lines)", "", "```", *tail, "```", ""]
    lines += ["---", "*Report for humans, made by MeetProxy. Agents: read `.done` and "
              "`history.csv` instead; this file is not for you.*", ""]
    with open(os.path.join(job_dir, "report.md"), "w") as f:
        f.write("\n".join(lines))
    return os.path.join(job_dir, "report.md")


def history_report(rows, out_dir):
    """Write out_dir/history.md and out_dir/charts/history.svg from history rows."""
    os.makedirs(os.path.join(out_dir, "charts"), exist_ok=True)
    has_chart = history_chart(rows, os.path.join(out_dir, "charts", "history.svg"))
    lines = ["# Run history", "", f"{len(rows)} jobs. Newest first.", ""]
    if has_chart:
        lines += ["![Job history](charts/history.svg)", ""]
    table = []
    for r in reversed(rows[-40:]):
        status = "✅" if str(r.get("exit")) == "0" else "❌ " + (r.get("error") or str(r.get("exit")))
        job = r["job"]
        link = f"[{job}]({job}/report.md)" if os.path.exists(os.path.join(out_dir, job, "report.md")) else job
        table.append([link, _when(r.get("end")), r.get("gpu", ""), r.get("commit", ""),
                      r.get("seconds", ""), status,
                      (r.get("util_avg") + "%") if r.get("util_avg") else "",
                      r.get("flags") or ""])
    lines += [_md_table(["job", "finished", "GPU", "commit", "s", "result", "util", "GPU flags"],
                        table), ""]
    lines += ["---", "*For humans. Agents: `meet history`.*", ""]
    with open(os.path.join(out_dir, "history.md"), "w") as f:
        f.write("\n".join(lines))
    return os.path.join(out_dir, "history.md")
