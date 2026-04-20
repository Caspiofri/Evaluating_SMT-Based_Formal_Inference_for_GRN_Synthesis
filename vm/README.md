# VM Components

## engine_v2_runner.fs
F# bridge that loads RE:IN DLLs and runs synthesis.
Lives on the Windows GCP VM — not committed to this repository.
Copy it into this vm/ directory on the VM before running experiments.

## To reproduce all results from scratch
```bash
git pull
# copy engine_v2_runner.fs into vm/
bash vm/run_all.sh
```

This runs all 199 removal experiments and generates results/ CSVs automatically.
Experiments already run are skipped (safe to re-run after partial completion).

## What run_all.sh does
1. Reads vm/removal_run_manifest.txt (199 .rein files)
2. For each: runs engine_v2_runner.fs, writes *_analysis_data.json alongside .rein
3. Skips files where *_analysis_data.json already exists
4. Runs pipeline/compute_required_interactions_from_removals.py to generate results/
