"""Telemetry: parsing, sampling, compaction, flags, the one line the agent reads."""
import os, time

import pytest

from pilot import telemetry as T


@pytest.mark.parametrize("raw,want", [
    ("97", 97), (" 68.5 ", 68.5), ("70.00", 70), ("[N/A]", None), ("[Not Supported]", None),
    ("N/A", None), ("", None), ("0x0000000000000040", 0x40), ("0xZZ", None), ("abc", None)])
def test_num(raw, want):
    assert T._num(raw) == want


def test_smi_failure_and_missing(no_gpu):
    assert T._smi("gpu=name") is None
    assert T.gpu_processes() == []


def test_foreign_processes(monkeypatch):
    me = os.getpgid(0)
    assert T.foreign([os.getpid()], me) == 0              # our own group
    assert T.foreign([os.getpid()], me + 1) == 1          # someone else's group
    assert T.foreign([os.getpid()], None) == 1            # before the job: anything counts
    assert T.foreign([2 ** 22 + 7], me) == 0              # invisible pid (container): ignored


def run_sampler(tmp_path, seconds=0.8, interval=0.05, **kw):
    s = T.Sampler(str(tmp_path / "o" / "gpu.csv"), interval=interval, **kw).start()
    time.sleep(seconds)
    st = s.stop()
    return s, st, (tmp_path / "o" / "gpu.csv").read_text()


def test_healthy_gpu(tmp_path, fake_gpu):
    s, st, csv = run_sampler(tmp_path)
    assert st["util_avg"] == 97 and st["mem_total_mb"] == 15360 and st["sm_max_mhz"] == 1590
    assert st["power_cap_pct"] == 100 and st["flags"] == []
    rows = [l for l in csv.splitlines() if l and not l.startswith(("#", "t,"))]
    assert st["samples"] >= 5 and len(rows) == 1           # unchanged samples compacted
    assert csv.startswith("# gpu 0: Tesla T4, 15360 MiB, power limit 70 W, max SM 1590 MHz")


def test_bad_gpu_flags(tmp_path, fake_gpu):
    fake_gpu("bad")
    s, st, csv = run_sampler(tmp_path, seconds=2.5)
    st["seconds"] = 60                                     # pretend long enough for duration flags
    fl = " · ".join(T.flags(st))
    for want in ("idle", "mem peak 94%", "thermal throttle", "SM clock unstable"):
        assert want in fl
    assert "0x40" in csv


def test_old_driver_drops_unknown_field(tmp_path, fake_gpu):
    fake_gpu("old-driver")
    s, st, csv = run_sampler(tmp_path)
    header = next(l for l in csv.splitlines() if l.startswith("t,"))
    row = csv.splitlines()[-1]
    assert "throttle" not in header and st["util_avg"] == 97
    assert len(header.split(",")) == len(row.split(","))   # header matches the data
    assert "thermal_throttle_pct" not in st


def test_broken_driver_gives_no_summary(tmp_path, fake_gpu):
    fake_gpu("broken")
    s, st, csv = run_sampler(tmp_path, seconds=0.3)
    assert st is None and T.line(st) == "gpu: no telemetry"


def test_busy_gpu_at_start(tmp_path, fake_gpu):
    fake_gpu("busy")
    s, st, _ = run_sampler(tmp_path, seconds=0.8)
    assert st["busy_at_start"] == 1
    assert any("GPU busy at start" in f for f in st["flags"])


def test_disabled_sampler(tmp_path, fake_gpu):
    s = T.Sampler(str(tmp_path / "gpu.csv"), interval=0).start()
    assert s.stop() is None and not (tmp_path / "gpu.csv").exists()


def test_env_interval(monkeypatch, tmp_path):
    monkeypatch.setenv("GPU_SAMPLE_S", "0")
    assert T.Sampler(str(tmp_path / "g.csv")).interval == 0


def test_keepalive_rows_and_interval_doubling(tmp_path, fake_gpu, monkeypatch):
    monkeypatch.setattr(T, "KEEP_S", 0.15)                 # one row at least every 0.15 s
    monkeypatch.setattr(T, "MAX_ROWS", 4)                  # interval doubles every 4 samples
    s, st, csv = run_sampler(tmp_path, seconds=3, interval=0.03)
    rows = [l for l in csv.splitlines() if l and not l.startswith(("#", "t,"))]
    assert len(rows) >= 3                                  # keep-alive rows despite no change
    ts = [s_["t"] for s_ in s.samples]
    gaps = [b - a for a, b in zip(ts, ts[1:])]
    first, last = sum(gaps[:3]) / 3, sum(gaps[-2:]) / 2
    assert last > 1.5 * first                              # sampling slowed down


@pytest.mark.parametrize("stats,want", [
    ({"seconds": 5, "idle_pct": 90}, []),                                   # too short to judge
    ({"seconds": 60, "idle_pct": 40}, ["idle 40%"]),
    ({"seconds": 60, "idle_pct": 10, "util_avg": 30}, ["util avg 30%"]),
    ({"mem_peak_mb": 900, "mem_total_mb": 1000}, ["mem peak 90%"]),
    ({"mem_peak_mb": 899, "mem_total_mb": 1000}, []),
    ({"thermal_throttle_pct": 5}, ["thermal throttle 5%"]),
    ({"hw_slowdown_pct": 7}, ["hw slowdown 7%"]),
    ({"sm_spread_pct": 10}, ["SM clock unstable ±10%"]),
    ({"other_procs": 2}, ["2 other GPU procs"]),
    ({"other_procs": 2, "busy_at_start": 1}, ["GPU busy at start (1 procs)"]),
    ({"power_cap_pct": 100}, []),                                           # normal under load
])
def test_flags(stats, want):
    assert T.flags(stats) == want


def test_line():
    assert T.line({"flags": ["idle 40%"]}).startswith("gpu WARN: idle 40%")
    assert T.line({"flags": [], "util_avg": 97, "mem_peak_mb": 512, "mem_total_mb": 1024,
                   "temp_max_c": 70}) == "gpu ok: util 97%, mem 50%, 70°C"
    assert T.line({"flags": []}) == "gpu ok: "


def test_transient_failure_keeps_all_fields(tmp_path, fake_gpu):
    """A driver hiccup must not permanently drop columns (only 'not a valid field' does)."""
    fake_gpu("broken")
    s = T.Sampler(str(tmp_path / "g.csv"), interval=0.05)
    assert s._query() is None
    assert len(s.fields) == len(T.FIELDS)


def test_smi_exception_is_reported(monkeypatch):
    def hang(*a, **k):
        raise T.subprocess.TimeoutExpired("nvidia-smi", 10)
    monkeypatch.setattr(T.subprocess, "run", hang)
    err = []
    assert T._smi("gpu=name", errors=err) is None and "timed out" in err[0]


def test_unknown_required_field_gives_up(monkeypatch, tmp_path):
    s = T.Sampler(str(tmp_path / "g.csv"), interval=0.05)
    s.fields = [("gpu", "index")]                          # nothing optional left to drop
    monkeypatch.setattr(T, "_smi", lambda q, errors=None: errors.append("not a valid field") or None)
    assert s._query() is None
