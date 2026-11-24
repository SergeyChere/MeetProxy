# timeout: 1800
# gpu: any
# MeetProxy job template. Runs from the project root on the Colab GPU.
# Copy, edit the variants and the command, then: meet run s01_bench job.sh
set -euo pipefail

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader
# fail loudly if another process is on the GPU: it would distort timings
if nvidia-smi --query-compute-apps=pid --format=csv,noheader | grep -q .; then
  echo "another process is using the GPU"; nvidia-smi; exit 1
fi

# --- build / install (edit) ---
# pip install -q -r requirements.txt
# make -j

echo "variant,run,ms" > "$MEET_OUT/results.csv"
for variant in baseline new; do          # edit: your variants
  for run in 1 2 3; do
    start=$(date +%s%N)
    # edit: the command to measure, e.g. ./bench --variant "$variant"
    python3 -c "print('$variant')"
    end=$(date +%s%N)
    echo "$variant,$run,$(( (end - start) / 1000000 ))" >> "$MEET_OUT/results.csv"
    echo "done: $variant run $run"
  done
done
cat "$MEET_OUT/results.csv"
