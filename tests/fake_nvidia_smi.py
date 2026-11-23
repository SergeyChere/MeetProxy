#!/usr/bin/env python3
"""A stand-in for nvidia-smi in tests. FAKE_GPU_MODE picks the GPU's behaviour:
  ok          healthy Tesla T4 under load (power-capped, which is normal)
  bad         idle half the time, thermal throttling, unstable clocks, memory near full
  old-driver  does not know clocks_throttle_reasons.active
  busy        another process (pid 1) is on the GPU
  broken      every query fails
FAKE_GPU_COUNTER: file used to vary samples over time (default: next to this script)."""
import os, sys

args = " ".join(sys.argv[1:])
mode = os.environ.get("FAKE_GPU_MODE", "ok")
if mode == "broken":
    print("NVIDIA-SMI has failed because it couldn't communicate with the NVIDIA driver.")
    sys.exit(9)
if "clocks_throttle" in args and mode == "old-driver":
    print('Field "clocks_throttle_reasons.active" is not a valid field to query.')
    sys.exit(2)
if "compute-apps" in args:
    if mode == "busy":
        print("1, 500")
    sys.exit(0)
if "index,name" in args:
    print("0, Tesla T4, 15360, 70.00, 1590")
    sys.exit(0)
if "utilization.gpu" in args:
    cnt = os.environ.get("FAKE_GPU_COUNTER") or os.path.join(os.path.dirname(__file__), ".n")
    try:
        n = int(open(cnt).read() or 0)
    except (FileNotFoundError, ValueError):
        n = 0
    open(cnt, "w").write(str(n + 1))
    if mode == "bad":
        util = 0 if n % 2 else 90
        sm = 900 if n % 3 == 0 else 1590
        thr = "0x0000000000000040" if n % 2 == 0 else "0x0000000000000000"
        row = [0, util, 30, 14500, sm, 5000, 86, 69.9, thr]
    else:
        row = [0, 97, 40, 6000, 1590, 5000, 65, 68.5, "0x0000000000000004"]
    if mode == "old-driver":
        row = row[:-1]
    print(", ".join(str(x) for x in row))
    sys.exit(0)
if "query-gpu=name" in args:
    print("Tesla T4, 15360 MiB, 535.104")
    sys.exit(0)
print("fake nvidia-smi: Tesla T4")
