"""GPU telemetry without a GPU: a fake nvidia-smi plays a healthy and an unhealthy T4.
Run: python3 tests/telemetry_test.py"""
import os, stat, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pilot import telemetry  # noqa: E402

FAKE = r'''#!/usr/bin/env python3
import os, sys
args = " ".join(sys.argv[1:])
mode = os.environ.get("FAKE_MODE", "ok")
if "clocks_throttle" in args and mode == "old-driver":
    print('Field "clocks_throttle_reasons.active" is not a valid field to query.'); sys.exit(2)
if "compute-apps" in args:
    sys.exit(0)
if "index,name" in args:
    print("0, Tesla T4, 15360, 70.00, 1590"); sys.exit(0)
if "utilization.gpu" in args:
    cnt = os.environ["FAKE_COUNTER"]
    n = int(open(cnt).read() or 0) if os.path.exists(cnt) else 0
    open(cnt, "w").write(str(n + 1))
    if mode == "bad":
        util = 0 if n % 2 else 90              # idle half the time
        sm = 900 if n % 3 == 0 else 1590       # unstable clocks
        thr = "0x0000000000000040" if n % 2 == 0 else "0x0000000000000000"
        row = [0, util, 30, 14500, sm, 5000, 86, 69.9, thr]
    else:
        row = [0, 97, 40, 6000, 1590, 5000, 65, 68.5, "0x0000000000000004"]
    if mode == "old-driver":
        row = row[:-1]
    print(", ".join(str(x) for x in row)); sys.exit(0)
print("unexpected", args); sys.exit(1)
'''

fails = 0


def check(cond, what):
    global fails
    print(("ok: " if cond else "FAIL: ") + what)
    fails += 0 if cond else 1


def run(mode, seconds=1.0):
    d = tempfile.mkdtemp()
    os.environ.update(FAKE_MODE=mode, FAKE_COUNTER=os.path.join(d, "n"))
    s = telemetry.Sampler(os.path.join(d, "out", "gpu.csv"), interval=0.05).start()
    time.sleep(seconds)
    st = s.stop()
    st["seconds"] = 60  # pretend a long job so the duration-gated flags apply
    st["flags"] = telemetry.flags(st)
    return st, open(os.path.join(d, "out", "gpu.csv")).read()


bindir = tempfile.mkdtemp()
fake = os.path.join(bindir, "nvidia-smi")
open(fake, "w").write(FAKE)
os.chmod(fake, os.stat(fake).st_mode | stat.S_IEXEC)
os.environ["PATH"] = bindir + os.pathsep + os.environ["PATH"]

st, csv = run("ok")
check(st["util_avg"] == 97 and st["mem_peak_mb"] == 6000 and st["mem_total_mb"] == 15360,
      "healthy: summary numbers")
check(st["flags"] == [], f"healthy: no flags {st['flags']}")
check(st["power_cap_pct"] == 100, "power cap counted but not flagged")
check(telemetry.line(st).startswith("gpu ok: util 97%, mem 39%"), telemetry.line(st))
rows = [l for l in csv.splitlines() if l and not l.startswith(("#", "t,"))]
check(st["samples"] >= 10 and len(rows) == 1, f"unchanged samples compacted to 1 row ({st['samples']} samples)")
check("Tesla T4" in csv, "csv header names the GPU")

st, csv = run("bad")
fl = " · ".join(st["flags"])
for want in ("idle", "mem peak 94%", "thermal throttle", "SM clock unstable"):
    check(want in fl, f"bad: flag '{want}' in [{fl}]")
check(telemetry.line(st).startswith("gpu WARN: "), telemetry.line(st))
rows = [l for l in csv.splitlines() if l and not l.startswith(("#", "t,"))]
check(len(rows) > 5 and "0x40" in csv, "changing samples are all kept, throttle as hex")

st, csv = run("old-driver")
check("throttle" not in csv.splitlines()[-1] and st.get("util_avg") == 97
      and "thermal_throttle_pct" not in st, "unknown field dropped, sampling continues")

check(telemetry.line(None) == "gpu: no telemetry", "no samples -> one honest line")
print("telemetry: all checks passed" if not fails else f"telemetry: {fails} FAILED")
sys.exit(1 if fails else 0)
