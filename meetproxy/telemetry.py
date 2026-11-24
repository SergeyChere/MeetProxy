"""GPU telemetry for a running job: collect everything, return it compactly.

Three levels, from cheap to read to complete:
  flags    one line for the agent, only what is off ("idle 66% · thermal throttle 12%") or "ok"
  summary  one JSON object in out/<job>.done under "gpu_stats" (averages, peaks, fractions)
  raw      out/<job>/gpu.csv, every sample that changed (plus one every KEEP_S), for digging

Sampling uses `nvidia-smi --query-gpu` every GPU_SAMPLE_S seconds (default 1; 0 disables).
The interval doubles every MAX_ROWS samples so a 12-hour job stays a small file.
"""
import os, subprocess, threading, time

# (csv column, nvidia-smi field). Optional fields are dropped if the driver does not know them.
FIELDS = [("gpu", "index"), ("util", "utilization.gpu"), ("mem_util", "utilization.memory"),
          ("mem_mb", "memory.used"), ("sm_mhz", "clocks.sm"), ("mem_mhz", "clocks.mem"),
          ("temp_c", "temperature.gpu"), ("power_w", "power.draw"),
          ("throttle", "clocks_throttle_reasons.active")]
OPTIONAL = {"clocks_throttle_reasons.active", "utilization.memory", "power.draw"}
STATIC = "index,name,memory.total,power.limit,clocks.max.sm"

# clocks_throttle_reasons bitmask
THERMAL = 0x20 | 0x40          # SW / HW thermal slowdown
POWER = 0x04 | 0x80            # SW power cap / HW power brake
HW_SLOW = 0x08                 # HW slowdown (often power supply or temperature)

KEEP_S = 30
MAX_ROWS = 3600


def _num(s):
    s = s.strip()
    if not s or s.startswith("[") or s in ("N/A", "Not Supported"):
        return None
    if s.lower().startswith("0x"):
        try:
            return int(s, 16)
        except ValueError:
            return None
    try:
        v = float(s)
        return int(v) if v.is_integer() else round(v, 1)
    except ValueError:
        return None


def _smi(query, timeout=10, errors=None):
    """Rows of nvidia-smi csv output, or None on failure (its message goes into `errors`)."""
    try:
        r = subprocess.run(["nvidia-smi", f"--query-{query}", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        if errors is not None:
            errors.append(str(e))
        return None
    if r.returncode:
        if errors is not None:
            errors.append(r.stdout + r.stderr)
        return None
    return [ln.split(",") for ln in r.stdout.strip().splitlines() if ln.strip()]


def gpu_processes():
    """pids of compute processes on the GPU (may be empty inside containers)."""
    rows = _smi("compute-apps=pid,used_memory") or []
    return [int(p[0]) for p in rows if p and p[0].strip().isdigit()]


def foreign(pids, pgid):
    """Processes on the GPU that do not belong to the job's process group (pids we cannot see
    are ignored: in containers nvidia-smi often reports host pids)."""
    n = 0
    for pid in pids:
        try:
            if pgid is None or os.getpgid(pid) != pgid:
                n += 1
        except (ProcessLookupError, PermissionError):
            pass
    return n


class Sampler:
    def __init__(self, csv_path, interval=None, pgid=None):
        self.path = csv_path
        self.interval = float(os.environ.get("GPU_SAMPLE_S", 1)) if interval is None else interval
        self.pgid = pgid
        self.fields = list(FIELDS)
        self.samples = []          # dicts of numbers, all samples (for the summary)
        self.static = {}
        self.foreign_max = 0
        self.busy_at_start = 0
        self._stop = threading.Event()
        self._th = None
        self._first = None
        self.t0 = None

    # -- collection --
    def _query(self):
        while self.fields:
            q = ",".join(f for _, f in self.fields)
            err = []
            rows = _smi(f"gpu={q}", errors=err)
            if rows is not None:
                return rows
            msg = " ".join(err)
            if "valid field" not in msg:  # a transient failure: skip this sample, keep the fields
                return None
            drop = next((x for x in self.fields if x[1] in OPTIONAL and x[1] in msg), None) or \
                next((x for x in self.fields if x[1] in OPTIONAL), None)
            if drop is None:
                return None
            self.fields.remove(drop)  # unknown field on this driver: retry without it
        return None

    def start(self):
        if self.interval <= 0:
            return self
        rows = _smi(f"gpu={STATIC}") or []
        for r in rows:
            if len(r) >= 5:
                self.static[r[0].strip()] = {"name": r[1].strip(), "mem_total_mb": _num(r[2]),
                                             "power_limit_w": _num(r[3]), "sm_max_mhz": _num(r[4])}
        self.busy_at_start = foreign(gpu_processes(), None)
        self._first = self._query()  # settles the field list before the CSV header is written
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        self.t0 = time.time()
        self._th = threading.Thread(target=self._run, daemon=True)
        self._th.start()
        return self

    def _run(self):
        last_row, last_t = {}, {}
        n, interval = 0, self.interval
        with open(self.path, "w") as f:
            for g, s in self.static.items():
                f.write(f"# gpu {g}: {s['name']}, {s['mem_total_mb']} MiB, "
                        f"power limit {s['power_limit_w']} W, max SM {s['sm_max_mhz']} MHz\n")
            f.write("# rows are written when a value changes, and at least every "
                    f"{KEEP_S} s; throttle is the nvidia-smi clocks_throttle_reasons bitmask\n")
            f.write("t," + ",".join(c for c, _ in self.fields) + "\n")
            while not self._stop.is_set():
                t = round(time.time() - self.t0, 1)
                rows, self._first = (self._first, None) if self._first else (self._query(), None)
                if rows:
                    cols = [c for c, _ in self.fields]
                    for r in rows:
                        vals = [_num(x) for x in r[:len(cols)]]
                        s = dict(zip(cols, vals))
                        s["t"] = t
                        self.samples.append(s)
                        g = s.get("gpu")
                        if vals != last_row.get(g) or t - last_t.get(g, -KEEP_S) >= KEEP_S:
                            f.write(f"{t}," + ",".join("" if v is None else
                                    (hex(v) if c == "throttle" else str(v))
                                    for c, v in zip(cols, vals)) + "\n")
                            last_row[g], last_t[g] = vals, t
                    f.flush()
                n += 1
                if n % 10 == 0:
                    self.foreign_max = max(self.foreign_max, foreign(gpu_processes(), self.pgid))
                if n % MAX_ROWS == 0:
                    interval *= 2
                self._stop.wait(interval)

    def stop(self):
        if self._th:
            self._stop.set()
            self._th.join(timeout=15)
        return self.summary()

    # -- compaction --
    def summary(self):
        if not self.samples:
            return None
        # one GPU (the first) carries the summary; jobs use one GPU in practice
        g0 = self.samples[0].get("gpu")
        ss = [s for s in self.samples if s.get("gpu") == g0]
        st = self.static.get(str(g0), {})

        def vals(k):
            return [s[k] for s in ss if s.get(k) is not None]

        def avg(v):
            return round(sum(v) / len(v)) if v else None

        def frac(pred):
            th = [s["throttle"] for s in ss if s.get("throttle") is not None]
            return round(100 * sum(1 for x in th if pred(x)) / len(th)) if th else None

        util, mem = vals("util"), vals("mem_mb")
        busy = [s for s in ss if (s.get("util") or 0) >= 50 and s.get("sm_mhz")]
        sm_busy = [s["sm_mhz"] for s in busy]
        sm_spread = None
        if len(sm_busy) >= 5:
            mean = sum(sm_busy) / len(sm_busy)
            sm_spread = round(100 * (max(sm_busy) - min(sm_busy)) / (2 * mean)) if mean else None
        out = {
            "samples": len(ss), "seconds": ss[-1]["t"],
            "util_avg": avg(util), "util_max": max(util) if util else None,
            "idle_pct": round(100 * sum(1 for u in util if u < 5) / len(util)) if util else None,
            "mem_peak_mb": max(mem) if mem else None, "mem_total_mb": st.get("mem_total_mb"),
            "sm_mhz_avg": avg(sm_busy) or avg(vals("sm_mhz")), "sm_max_mhz": st.get("sm_max_mhz"),
            "sm_spread_pct": sm_spread,
            "temp_max_c": max(vals("temp_c")) if vals("temp_c") else None,
            "power_avg_w": avg(vals("power_w")), "power_limit_w": st.get("power_limit_w"),
            "thermal_throttle_pct": frac(lambda x: x & THERMAL),
            "power_cap_pct": frac(lambda x: x & POWER),
            "hw_slowdown_pct": frac(lambda x: x & HW_SLOW),
            "other_procs": max(self.foreign_max, self.busy_at_start),
            "busy_at_start": self.busy_at_start,
        }
        out = {k: v for k, v in out.items() if v is not None}
        out["flags"] = flags(out)
        return out


def flags(s):
    """Only what is off. Empty list = nothing to worry about."""
    f = []
    long_enough = s.get("seconds", 0) >= 10
    if long_enough and s.get("idle_pct", 0) >= 30:
        f.append(f"idle {s['idle_pct']}%")
    elif long_enough and s.get("util_avg", 100) < 50:
        f.append(f"util avg {s['util_avg']}%")
    if s.get("mem_total_mb") and s.get("mem_peak_mb", 0) >= 0.9 * s["mem_total_mb"]:
        f.append(f"mem peak {round(100 * s['mem_peak_mb'] / s['mem_total_mb'])}%")
    if s.get("thermal_throttle_pct", 0) >= 5:
        f.append(f"thermal throttle {s['thermal_throttle_pct']}%")
    if s.get("hw_slowdown_pct", 0) >= 5:
        f.append(f"hw slowdown {s['hw_slowdown_pct']}%")
    if s.get("sm_spread_pct", 0) >= 10:
        f.append(f"SM clock unstable ±{s['sm_spread_pct']}%")
    if s.get("busy_at_start"):
        f.append(f"GPU busy at start ({s['busy_at_start']} procs)")
    elif s.get("other_procs"):
        f.append(f"{s['other_procs']} other GPU procs")
    return f


def line(stats):
    """The one line an agent reads after a job."""
    if not stats:
        return "gpu: no telemetry"
    if stats["flags"]:
        return "gpu WARN: " + " · ".join(stats["flags"]) + "  (details: gpu_stats in .done, gpu.csv)"
    bits = []
    if "util_avg" in stats:
        bits.append(f"util {stats['util_avg']}%")
    if stats.get("mem_total_mb") and "mem_peak_mb" in stats:
        bits.append(f"mem {round(100 * stats['mem_peak_mb'] / stats['mem_total_mb'])}%")
    if "temp_max_c" in stats:
        bits.append(f"{stats['temp_max_c']}°C")
    return "gpu ok: " + ", ".join(bits)
