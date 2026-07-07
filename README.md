# Algorithms for Synthesis of Gene Regulatory Networks

**Authors:** Ofri Caspi, Michal Zimering
**Supervisor:** Prof. Hillel Kugler | **Co-supervisor:** Eitan Tannenbaum
**Bar Ilan University — B.Sc. Final Project**

---

## Overview

This repository accompanies the B.Sc. thesis _"Algorithms for Synthesis of Gene
Regulatory Networks"_. It provides an interactive research environment for
evaluating **RE:IN** (Reasoning Engine for Interaction Networks) — an SMT-based
(Z3) synthesis engine for Boolean Gene Regulatory Networks (GRNs) that
reconstructs network topologies from trajectory observations.

The project distinguishes between two complementary notions of edge importance:

- **Statistical correlation** — how often an edge appears across enumerated
  consistent solutions (_edge frequency_).
- **Formal structural necessity** — whether the model becomes UNSAT when the
  edge is forbidden (_removal-UNSAT proof_).

The thesis formally characterises **six deterministic rules (R1–R3, D1–D3)**
that predict structural necessity with **100% accuracy** on cascade-topology
models with step-by-step trajectory observations. This repository provides the
runtime infrastructure that validates those rules experimentally.

---

## Research Questions

### RQ1 — Evaluating Inference Performance (Michal Zimering)

Invistigating RE:IN’s performance through three research questions.
The first three research questions are evaluated using models sourced from
the **Biodivine Boolean Models (BBM) corpus**.

1. Original Network Reconstruction (Q1):
   Can RE:IN identify feasible solutions for a model derived from a known reference,
   where all interactions are defined as optional and the constraints are based on
   experimental observations generated from the original model?
   Specifically, is the original network—the model in which all interactions are present—
   included among these solutions?

2. Solution Space Reduction via Observation Volume (Q2):
   Does the number of solutions found by RE:IN decrease as the amount of provided
   information—specifically the number of independent experimental observations—increases?

3. Solution Space Reduction via Trajectory Resolution (Q3):
   Does the number of solutions found by RE:IN decrease as the information density increases—
   specifically by adding intermediate states to the experimental observations?

### RQ2 — Structural Interaction Identification (Ofri Caspi)

Which edges are provably **required** (removing them makes the model UNSAT)
or **disallowed** (forcing them present makes the model UNSAT)? RQ2 is the
core of the interactive demo. The `experiments/RQ2/` directory contains the
hand-crafted validation models used to exercise the six deterministic rules:

| File                    | Purpose                                                  |
| ----------------------- | -------------------------------------------------------- |
| `designed_cascade.rein` | Proof-by-construction benchmark (R1×3, D1, D2)           |
| `seaurchinA2-11.rein`   | Sea urchin relay — R1, R2, D1, D2 (canonical example)    |
| `seaurchinC3-6.rein`    | Sea urchin cascade — R1 chain (minimal causal backbone)  |
| `seaurchinf1-3.rein`    | Sea urchin endomesoderm — R3 (inhibitory required edges) |
| `seaurchinf2-1.rein`    | Sea urchin endomesoderm — D3 (forbidden inhibition)      |

Additional models from the full 26-model sea urchin series are included in the
directory; the five above are the primary validation models discussed in the
thesis. Full series results are tabulated in the thesis appendix.

---

## Key Findings

### Evaluating Inference Performance

1. **Successful Network Reconstruction**: The pipeline achieved a 100% success rate in identifying ground-truth configurations using $N=5$ independent observations. This demonstrates significant success in consistently recovering correct network structures from synthetic biological data.

2. **Expressiveness Limitations**: Increasing data volume to $N=10$ observations revealed that the engine is not suited for models with **complex** update functions. The additional data exposed that RE:IN’s predefined regulatory schemas cannot represent **non-monotonic** or **asymmetric** logic, leading to unsatisfiable (UNSAT) outcomes in these cases (e.g., Models 29, 97, and 171). A detailed breakdown of the specific reasons causing the UNSAT outcome for each model is provided in the Excel file located within the experiments/RQ1/ directory.

3. **Solution Space Convergence**: Increasing data density—both in terms of experiment quantity ($N$) and temporal resolution (via $T_{mid}$ steps)—consistently reduces the number of valid solutions. This confirms that higher data density is a critical factor in narrowing the solution space and focusing it toward the ground-truth model.

### The Six Deterministic Rules

The thesis formally characterises six analytic rules that predict an edge's
structural role from network topology and trajectory alone. The dashboard's
Structural Backbone Proof tab independently validates each rule against the
removal-UNSAT verdict.

**Required edges (R-rules)** — an edge is _required_ when:

| Rule   | Name         | Condition                                                                            |
| ------ | ------------ | ------------------------------------------------------------------------------------ |
| **R1** | Activation   | Edge is the sole timing-consistent activator at the step the target gene turns ON.   |
| **R2** | Maintenance  | Edge is the only active optional activator when a gene must remain ON across a step. |
| **R3** | Deactivation | Edge is the only active optional inhibitor that can explain a gene turning OFF.      |

**Disallowed edges (D-rules)** — an edge is _disallowed_ when:

| Rule   | Name                            | Condition                                                                                                      |
| ------ | ------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| **D1** | Forced Activation Contradiction | The activating edge would force the target ON, but the trajectory requires it OFF with no inhibitor available. |
| **D2** | Trapped Transient Signal        | A self-loop would prevent a signal from turning OFF as required by the trajectory.                             |
| **D3** | Forbidden Inhibition            | The inhibitor is active at a step when the target must remain ON.                                              |

### Headline Results

1. **100% agreement with removal-UNSAT** on all RQ2 validation models
   (cascade-topology networks with sparse in-degree and step-by-step
   trajectory observations). Dense BBM corpus models return 0 required
   interactions because multiple optional activators are simultaneously
   active at every cascade step, preventing the sole-activator condition
   from being satisfied.
2. **Structural necessity ≠ statistical frequency.** An edge can appear in
   100% of enumerated solutions and still be removal-SAT (not structurally
   required) — Z3 chose to include it when free to do so, but can find valid
   networks without it when forced. The dashboard surfaces both signals side
   by side so this distinction is observable per-edge.
3. **Prior exploratory results** (Phase 1 L-value recovery benchmarks) are
   superseded by the structural-necessity framework and are retained only in
   `_archive/` for historical reference.

---

## Interactive Dashboard

The primary deliverable is a Streamlit dashboard that wraps the RE:IN engine:

```bash
streamlit run streamlit_dashboard.py
```

### Workflow

1. Upload a `.aeon`, `.sbml`, or pre-built `.rein` file.
2. Configure experiment parameters in the sidebar:
   - **Trajectory observations (N)** — number of simulation runs.
   - **Trajectory length / steps (K)** — steps per run. Use **K ≤ 10** for
     structural inference (required/disallowed); higher values for L-value
     synthesis.
   - **Max solutions** — solver enumeration cap.
   - **Deep analysis** — enables RE:IN's native `IdentifyInteractions`.
3. Click **🚀 Run Analysis**. Results populate across seven tabs.

### Tabs

| Tab                          | Purpose                                                        |
| ---------------------------- | -------------------------------------------------------------- |
| 🌐 Problem Network           | Full model topology (optional edges dashed, definite solid)    |
| 🔬 Solution Network          | A single concrete consistent network                           |
| 📊 Solution Summary          | Interaction matrix & parameter assignments across solutions    |
| 🧪 Observations              | Initial/final-state constraints fed to the solver              |
| 🔒 Built-in Interactions     | RE:IN's native `IdentifyInteractions` (requires Deep analysis) |
| 🧬 Structural Backbone Proof | **Primary interface for RQ2** — see below                      |
| 📄 Generated .rein           | Download the generated `.rein` file                            |

### 🧬 Structural Backbone Proof (RQ2 Interface)

This unified tab is the project's central experimental interface. It performs
the **explicit removal-UNSAT experiment**: each optional edge is forced
absent, the model is re-solved, and the edge is classified as **Required**
(UNSAT without it), **Disallowed** (never appeared in any enumerated
solution), or **Inconclusive** (SAT on removal; ambiguous).

The verdict is cross-referenced **in-memory** against the edge-frequency
data produced by the same baseline enumeration — producing the joined
classification table central to the thesis's structural-necessity vs.
statistical-correlation argument. No pre-computed data is required; both
signals are derived live from the current run.

> **For best results:** upload one of the pre-built `.rein` files from
> `experiments/RQ2/` (e.g. `designed_cascade.rein`) rather than converting
> an `.aeon` file. The hand-crafted files use the seaurchin-style format
> (step-by-step observations, no directive lines) that `IdentifyInteractions`
> requires to produce non-trivial results.

---

## Repository Structure

```
grn-rein-project/
├── streamlit_dashboard.py                 # Main interactive UI (entry point)
├── requirements.txt                        # Python dependencies
├── pipeline/
│   ├── generate_experiment.py             # AEON → .rein + trajectory generation
│   └── sbml_to_rein_preserve_certainty.py # SBML → .rein converter
├── vm/
│   └── engine_v2_runner.fsx               # F# bridge to RE:IN / Z3
├── experiments/
│   ├── RQ1/                               # Infrastructure for BBM corpus eval
│   └── RQ2/                               # Hand-crafted validation .rein files
├── reports/
│   └── model_screening_report.csv         # Initial 285-model BBM screening
├── README.md
└── _archive/                              # Superseded scripts & historical results
```

---

## Installation

### Dependencies

The active code depends on a minimal Python stack:

```
streamlit
pandas
requests
```

> **Note on dependency cleanup:** earlier revisions of `requirements.txt`
> included `biodivine_aeon`, `matplotlib`, and `numpy`. These were tied to
> legacy code paths and have been pruned in the current submission.

```bash
pip install -r requirements.txt
```

### Engine (RE:IN + Z3)

The RE:IN engine is loaded by [vm/engine_v2_runner.fsx](vm/engine_v2_runner.fsx)
via .NET F# Interactive (`dotnet fsi`). It depends on:

- .NET 8 SDK (`dotnet fsi` available on `PATH`)
- RE:IN, RENotebookApi, ReasoningEngine, RESIN, ReinMoCo DLLs
  (netstandard2.0 builds)
- Microsoft.Z3 (4.8.9) + native `libz3`
- Newtonsoft.Json (12.0.2)
- AutomaticGraphLayout (1.1.9)

---

## Reproducibility & Environment

**This submission is optimised for a specific GCP VM environment.** The
engine script references DLLs via **hardcoded absolute paths** rooted at
`/submission/artifact/...`. Setting up an equivalent local
environment — while theoretically possible by editing the `#r` directives at
the top of [vm/engine_v2_runner.fsx](vm/engine_v2_runner.fsx) to point at a
local RE:IN build — is out of scope for this submission.

To run the submission as intended:

1. Connect to the provided GCP VM (credentials supplied separately).
2. `cd ~/grn-rein-project`
3. `pip install -r requirements.txt`
4. `streamlit run streamlit_dashboard.py`
5. Open the displayed URL in a browser.

---

## References

- Yordanov, B., Dunn, S.-J., Kugler, H., _et al._ (2016). _A method to
  identify and analyze biological programs through automated reasoning._
  npj Systems Biology and Applications **2**, 16010.
- Pastva, S., Červený, J., Šafránek, D., _et al._ (2023). _Biodivine Boolean
  Models: A comprehensive collection of Boolean network models._
  bioRxiv 2023.06.12.544361.
- Dunn, S.-J., Li, M. A., Carbognin, E., Smith, A., & Martello, G. (2019).
  _A common molecular logic determines embryonic stem cell self-renewal and
  reprogramming._ The EMBO Journal **38**.

---

## License & Contact

Licensed under the **MIT License** — academic use, with attribution.
