  #!/usr/bin/env python3
"""
RE:IN Analysis Dashboard
Upload .aeon / .sbml → generate .rein → run REIN engine → display results (SVG + HTML)
"""

import streamlit as st
import subprocess
import json
import re
import sys
import tempfile
from pathlib import Path
from typing import Optional

import pandas as pd

# ── Paths ──────────────────────────────────────────────────────────────────
REPO_ROOT    = Path(__file__).resolve().parent
RUNNER_FSX   = REPO_ROOT / "vm" / "engine_v2_runner.fsx"
PIPELINE_DIR = REPO_ROOT / "pipeline"

sys.path.insert(0, str(PIPELINE_DIR))
from generate_experiment import (
    parse_aeon, simulate, write_rein_file, generate_ground_truth
)

# SBML converter (preserve-certainty variant keeps optional/definite distinction)
from sbml_to_rein_preserve_certainty import parse_sbml

# ── Page config ────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="RE:IN Analysis Dashboard",
    page_icon="🧬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
  .stApp { background: #FFFFFF; }
  .main .block-container { padding-top: 2rem; padding-bottom: 2rem; }
  [data-testid="stSidebar"] { background-color: #F8F9FA; }
  h1, h2, h3 { color: #0056b3; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════

def run_engine(rein_path: Path, max_solutions: int = 10, traj_length: int = 30,
               timeout: int = 600, deep: bool = False,
               all_svgs: bool = False, removal: bool = False) -> Optional[dict]:
    """Run engine_v2_runner.fsx on a .rein file. Return parsed JSON or None."""
    out_json = rein_path.parent / "analysis_data.json"
    try:
        cmd = ["dotnet", "fsi", str(RUNNER_FSX), "--",
               str(rein_path), str(max_solutions), str(traj_length)]
        if deep:
            cmd.append("--deep")
        if all_svgs:
            cmd.append("--all-svgs")
        if removal:
            cmd.append("--removal")
        subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if out_json.exists():
            return json.loads(out_json.read_text())
        return None
    except subprocess.TimeoutExpired:
        return None
    except Exception:
        return None


def render_svg(svg_html: str, height: int = 600) -> bool:
    """Render an SVG string via st.components.v1.html. Returns True if rendered."""
    if not svg_html or not svg_html.strip():
        return False
    clean = svg_html.strip()
    clean = ''.join(c for c in clean if c.isprintable() or c in '\n\r\t')
    if clean.startswith('<svg') or clean.startswith('<!DOCTYPE') or clean.startswith('<?xml'):
        wrapped = f'<div style="overflow:auto;width:100%;height:100%;background:#fff;">{clean}</div>'
        st.components.v1.html(wrapped, height=height, scrolling=True)
        return True
    return False


def render_html(html: str, height: int = 500) -> bool:
    """Render an HTML string via st.components.v1.html. Returns True if rendered."""
    if not html or not html.strip() or len(html.strip()) < 20:
        return False
    try:
        st.components.v1.html(html, height=height, scrolling=True)
        return True
    except Exception:
        st.markdown(html, unsafe_allow_html=True)
        return True


# ══════════════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════════════

def _generate_full_connectivity(variables):
    """Generate all possible edges between all genes (both signs), all optional."""
    regs = []
    for src in sorted(variables):
        for dst in sorted(variables):
            regs.append({"src": src, "dst": dst, "sign": "positive", "optional": True})
            regs.append({"src": src, "dst": dst, "sign": "negative", "optional": True})
    return regs


def main():
    st.title("🧬 RE:IN Analysis Dashboard")
    st.markdown(
        "Upload a `.aeon`, `.sbml`, or `.rein` Boolean network model → "
        "run the RE:IN solver → view the results."
    )

    # ── Sidebar ───────────────────────────────────────────────────────────
    with st.sidebar:
        st.header("⚙️ Input & Parameters")

        uploaded_file = st.file_uploader(
            "Upload model", type=["aeon", "sbml", "rein"],
            help="Boolean GRN in AEON / SBML-qual format, or a pre-built .rein file"
        )

        is_rein = uploaded_file is not None and uploaded_file.name.endswith(".rein")
        is_sbml = uploaded_file is not None and uploaded_file.name.endswith(".sbml")

        # -- AEON / SBML: conversion mode + experiment params --
        if not is_rein:
            st.markdown("---")
            st.subheader("REIN conversion mode")
            if is_sbml:
                conversion_mode = st.radio(
                    "Edge generation",
                    options=[
                        "Preserve certainty (from .sbml)",
                        "All optional",
                        "Full connectivity",
                    ],
                    index=1,
                    help=(
                        "**Preserve certainty**: edges with a known sign in the "
                        "SBML file become definite; edges with unknown sign become "
                        "optional (both +/-).\n\n"
                        "**All optional**: every edge becomes optional — RE:IN "
                        "decides which are required. Standard for recall/precision.\n\n"
                        "**Full connectivity**: connect every gene to every gene "
                        "(both +/-), all optional. Advanced: tests whether RE:IN "
                        "can infer the topology from scratch."
                    ),
                )
            else:
                conversion_mode = st.radio(
                    "Edge generation",
                    options=[
                        "Faithful (from .aeon)",
                        "All optional",
                        "Full connectivity",
                    ],
                    index=1,
                    help=(
                        "**Faithful**: edges keep their sign and optional/definite "
                        "status from the .aeon file (edges with `?` are optional, "
                        "others are definite).\n\n"
                        "**All optional**: every edge becomes optional — RE:IN "
                        "decides which are required. Standard for recall/precision.\n\n"
                        "**Full connectivity**: connect every gene to every gene "
                        "(both +/-), all optional. Advanced: tests whether RE:IN "
                        "can infer the topology from scratch."
                    ),
                )
            st.markdown("---")
            st.subheader("Experiment parameters")
            N = st.slider("Trajectory observations (N)", 1, 30, 2,
                           help="Number of synchronous fixpoint experiments")
            K = st.slider("Trajectory length / steps (K)", 1, 100, 10,
                           help="Simulation steps per experiment. Use 4–10 for "
                                "structural inference (required/disallowed "
                                "interactions). Higher values for L-value synthesis.")
        else:
            conversion_mode = None
            N = None
            K = None

        max_solutions = st.slider("Max solutions", 1, 1000, 65,
                                   help="Solver upper bound")

        deep_analysis = st.checkbox(
            "Deep analysis",
            value=False,
            help="Run IdentifyInteractions + FindMinimalModels. "
                 "Adds ~90s but finds required/disallowed edges "
                 "and minimal consistent networks natively via RE:IN."
        )

        all_svgs = st.checkbox(
            "Generate all solution SVGs",
            value=False,
            help="Generate a network SVG for every solution (not just the first). "
                 "Enables browsing individual solutions. May add time for many solutions."
        )

        run_btn = st.button("🚀 Run Analysis", type="primary",
                            use_container_width=True)

        if st.button("🗑️ Clear", use_container_width=True):
            for k in list(st.session_state.keys()):
                del st.session_state[k]
            st.rerun()

    # ── No file yet ───────────────────────────────────────────────────────
    if uploaded_file is None:
        st.info("👈 Upload a `.aeon`, `.sbml`, or `.rein` file in the sidebar to begin.")
        return

    # ── Persist uploaded file across reruns ────────────────────────────────
    if "file_path" not in st.session_state or \
            st.session_state.get("model_name") != uploaded_file.name:
        tmp_dir = Path(tempfile.mkdtemp(prefix="rein_"))
        file_path = tmp_dir / uploaded_file.name
        file_path.write_bytes(uploaded_file.getvalue())
        st.session_state["file_path"] = str(file_path)
        st.session_state["model_name"] = uploaded_file.name
        st.session_state.pop("output", None)

    file_path = Path(st.session_state["file_path"])

    # ══════════════════════════════════════════════════════════════════════
    # REIN file path — skip parsing, just show file info
    # ══════════════════════════════════════════════════════════════════════
    if is_rein:
        rein_text = file_path.read_text()
        n_lines = len(rein_text.splitlines())
        n_interactions = sum(1 for line in rein_text.splitlines()
                             if line.strip() and not line.strip().startswith("//")
                             and not line.strip().startswith("#")
                             and not line.strip().startswith("$")
                             and not line.strip().startswith("directive")
                             and ("positive" in line or "negative" in line))
        st.markdown(f"### REIN file: `{uploaded_file.name}`")
        c1, c2 = st.columns(2)
        c1.metric("Lines", n_lines)
        c2.metric("Interaction lines", n_interactions)

        variables = set()
        regulations = []
        input_nodes = []
        unique_regs = []
    elif is_sbml:
        # ══════════════════════════════════════════════════════════════════
        # SBML file path — parse topology
        # ══════════════════════════════════════════════════════════════════
        try:
            sbml_vars, update_functions, input_nodes, regulations = parse_sbml(file_path)
            variables = set(sbml_vars)
        except Exception as e:
            st.error(f"Failed to parse .sbml file: {e}")
            return
    else:
        # ══════════════════════════════════════════════════════════════════
        # AEON file path — parse topology
        # ══════════════════════════════════════════════════════════════════
        try:
            update_functions, input_nodes, variables, regulations = parse_aeon(file_path)
        except Exception as e:
            st.error(f"Failed to parse .aeon file: {e}")
            return

    if not is_rein:
        # Deduplicate regulations
        seen = set()
        unique_regs = []
        for r in regulations:
            key = (r["src"], r["dst"], r["sign"])
            if key not in seen:
                unique_regs.append(r)
                seen.add(key)

        n_genes  = len(variables)
        n_edges  = len(unique_regs)
        n_inputs = len(input_nodes)

        source_label = ".sbml" if is_sbml else ".aeon"
        st.markdown(f"### Model: `{uploaded_file.name}`")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Genes", n_genes - n_inputs)
        c2.metric(f"Edges (from {source_label})", n_edges)
        c3.metric("Input nodes", n_inputs)
        if conversion_mode == "Full connectivity":
            full_edges = n_genes * n_genes * 2
            c4.metric("Full connectivity edges", full_edges)

    # ── Run pipeline ──────────────────────────────────────────────────────
    if run_btn:
        st.session_state.pop("output", None)
        work_dir = file_path.parent / "work"
        work_dir.mkdir(exist_ok=True)

        if is_rein:
            # Direct .rein — just run the engine
            rein_path = file_path
            rein_text = file_path.read_text()
        elif is_sbml:
            # SBML → REIN conversion
            with st.spinner("Converting SBML → REIN…"):
                try:
                    import random
                    random.seed(42)
                    all_genes = sorted(variables)
                    experiments = []
                    for i in range(N):
                        init = {gene: random.randint(0, 1) for gene in all_genes}
                        traj = simulate(update_functions, input_nodes, init, K)
                        experiments.append({
                            "id": i, "K": K,
                            "init_state": traj[0],
                            "final_state": traj[-1],
                            "full_trajectory": traj,
                        })

                    rein_path = work_dir / f"{file_path.stem}.rein"

                    if conversion_mode == "Full connectivity":
                        full_regs = _generate_full_connectivity(variables)
                        write_rein_file(rein_path, variables, full_regs,
                                        input_nodes, experiments, K,
                                        force_optional=True)
                    elif conversion_mode == "Preserve certainty (from .sbml)":
                        write_rein_file(rein_path, variables, unique_regs,
                                        input_nodes, experiments, K,
                                        force_optional=False)
                    else:  # "All optional"
                        write_rein_file(rein_path, variables, unique_regs,
                                        input_nodes, experiments, K,
                                        force_optional=True)
                except Exception as e:
                    st.error(f"Failed to generate .rein from SBML: {e}")
                    return
            rein_text = rein_path.read_text()
        else:
            # AEON → REIN conversion
            with st.spinner("Generating .rein file…"):
                try:
                    gt = generate_ground_truth(file_path, N=N, K=K, seed=42)
                    rein_path = work_dir / f"{file_path.stem}.rein"

                    if conversion_mode == "Full connectivity":
                        full_regs = _generate_full_connectivity(variables)
                        write_rein_file(rein_path, variables, full_regs,
                                        input_nodes, gt["experiments"], K,
                                        force_optional=True)
                    elif conversion_mode == "Faithful (from .aeon)":
                        write_rein_file(rein_path, variables, unique_regs,
                                        input_nodes, gt["experiments"], K,
                                        force_optional=False)
                    else:  # "All optional"
                        write_rein_file(rein_path, variables, unique_regs,
                                        input_nodes, gt["experiments"], K,
                                        force_optional=True)
                except Exception as e:
                    st.error(f"Failed to generate .rein: {e}")
                    return
            rein_text = rein_path.read_text()

        # Run REIN engine
        traj_len = max(K, 30) if K else 30
        with st.spinner("Running RE:IN solver…"):
            output = run_engine(rein_path, max_solutions=max_solutions,
                                traj_length=traj_len, deep=deep_analysis,
                                all_svgs=all_svgs)

        if output is None:
            st.error("Engine returned no output. Check that `dotnet fsi` is available.")
            return

        if output.get("error"):
            st.error(f"Engine error: {output['error']}")

        output["_rein_text"] = rein_text
        output["_rein_path"] = str(rein_path)
        st.session_state["output"] = output

    # ── Display results ───────────────────────────────────────────────────
    if "output" not in st.session_state:
        st.info("Click **Run Analysis** to start the solver.")
        return

    output = st.session_state["output"]
    solution_count = output.get("solutionCount", 0) or 0

    if solution_count == 0:
        st.warning("⚠️ No solutions found (UNSAT). The model may be over-constrained.")
    else:
        st.success(f"✅ Analysis complete — {solution_count} solution(s) found.")

    # ── Tabs ──────────────────────────────────────────────────────────────
    (tab_net, tab_sol, tab_summary, tab_obs,
     tab_required, tab_removal, tab_rein) = st.tabs([
        "🌐 Problem Network",
        "🔬 Solution Network",
        "📊 Solution Summary",
        "🧪 Observations",
        "🔒 Built-in Interactions",
        "🧬 Structural Backbone Proof",
        "📄 Generated .rein",
    ])

    # ── Tab 1: Problem Network SVG ────────────────────────────────────────
    with tab_net:
        st.subheader("Problem-Level Network")
        st.markdown(
            "Shows **all** edges in the model. "
            "Dashed lines = optional (uncertain), solid = definite."
        )
        if not render_svg(output.get("network_svg", ""), height=600):
            st.info(
                "**Network SVG is empty.** "
                "`DrawBespokeNetworkWithSizeSVG` requires **SixLabors.Fonts** "
                "on the server. Install it to enable this view."
            )

    # ── Tab 2: Solution Network SVG ───────────────────────────────────────
    with tab_sol:
        st.subheader("Solution Network")
        st.markdown(
            "Shows **only** the edges present in a single solution. "
            "All edges are solid — this is one concrete consistent network."
        )
        if solution_count == 0:
            st.info("No solutions found — no solution network to display.")
        else:
            svgs = output.get("solution_svgs", []) or []
            if len(svgs) > 1:
                idx = st.selectbox(
                    "Select solution",
                    range(len(svgs)),
                    format_func=lambda i: f"Solution {i + 1} of {len(svgs)}",
                    key="sol_select",
                )
                if not render_svg(svgs[idx], height=600):
                    st.info("SVG for this solution is empty.")
            elif len(svgs) == 1:
                if not render_svg(svgs[0], height=600):
                    st.info("Solution SVG is empty.")
            else:
                # Fall back to single solution_svg (first solution)
                st.caption("Showing first solution only. Enable **Generate all solution SVGs** to browse all.")
                if not render_svg(output.get("solution_svg", ""), height=600):
                    st.info("**Solution SVG is empty.** Requires **SixLabors.Fonts** on the server.")

    # ── Tab 3: Solution Summary HTML ──────────────────────────────────────
    with tab_summary:
        st.subheader("Solution Summary Table")
        st.markdown(
            "Interaction matrix and parameter assignments across all solutions "
            "(from `DrawSummary`)."
        )
        if not render_html(output.get("summary_html", ""), height=500):
            if solution_count == 0:
                st.info("No solutions — summary table is empty.")
            else:
                st.warning("Summary HTML not available from engine output.")

    # ── Tab 4: Observations HTML ──────────────────────────────────────────
    with tab_obs:
        st.subheader("Experimental Observations")
        st.markdown(
            "The constraints fed to the solver — initial/final states for each "
            "experiment (from `DrawObservations`)."
        )
        if not render_html(output.get("observations_html", ""), height=500):
            st.info("Observations HTML not available from engine output.")

    # ── Tab 5: Native Engine Constraints (deep analysis) ───────────────────
    with tab_required:
        st.subheader("🔒 Native Engine Constraints")
        st.markdown(
            "RE:IN's `IdentifyInteractions` determines which edges are **required** "
            "(removing them causes UNSAT — no valid network exists without them) and "
            "which are **disallowed** (forcing them present causes UNSAT — no valid "
            "network can include them). Requires the **Deep analysis** checkbox."
        )
        req_count = output.get("required_count", 0) or 0
        dis_count = output.get("disallowed_count", 0) or 0
        req_html = output.get("required_html", "")
        c_svg = output.get("constrained_svg", "")

        if req_html:
            c1, c2 = st.columns(2)
            c1.metric("Required edges", req_count)
            c2.metric("Disallowed edges", dis_count)
            render_html(req_html, height=400)
            if c_svg:
                st.markdown("#### Constrained Network")
                render_svg(c_svg, height=500)
        else:
            st.info(
                "No data. Enable the **Deep analysis** checkbox in the sidebar "
                "and re-run to populate this tab."
            )

    # ── Merged: Structural Backbone Proof (removal-UNSAT + edge frequency) ──
    with tab_removal:
        st.subheader("🧬 Structural Necessity Analysis (Removal-UNSAT)")
        st.markdown(
            "This tab performs the explicit removal experiment. It proves "
            "structural necessity by forcing each edge absent. If the model "
            "becomes UNSAT without an edge, that edge is part of the "
            "**Causal Backbone**. Results are cross-referenced with statistical "
            "edge frequency."
        )

        if solution_count == 0:
            st.warning("Cannot run removal analysis on an UNSAT model.")
        else:
            removal_data = output.get("removal_required", [])

            # ── Section 1: Run Analysis ───────────────────────────────
            st.markdown("### Run Analysis")

            if not removal_data:
                st.info(
                    "No removal-UNSAT data available. Click below to run the analysis. "
                    "This tests each optional edge individually (~5s per edge)."
                )
                st.info(
                    "**Note:** Structural inference (required/disallowed interactions) "
                    "works best with step-by-step trajectory observations (K ≤ 10) and "
                    "all-optional edges. For strongest results, upload a hand-crafted "
                    ".rein file with a step-by-step trajectory rather than using the "
                    "AEON/SBML pipeline."
                )
                if st.button("🧬 Prove Structural Necessity", type="primary",
                             use_container_width=True, key="removal_btn"):
                    rein_path_str = output.get("_rein_path", "")
                    if not rein_path_str:
                        fp = Path(st.session_state.get("file_path", ""))
                        work_dir = fp.parent / "work"
                        candidates = sorted(work_dir.glob("*.rein")) if work_dir.exists() else []
                        if candidates:
                            rein_path_str = str(candidates[0])
                        elif fp.suffix == ".rein":
                            rein_path_str = str(fp)

                    if not rein_path_str or not Path(rein_path_str).exists():
                        st.error("Cannot find the .rein file to re-run. Please run baseline first.")
                    else:
                        with st.spinner("Running removal-UNSAT analysis (this may take ~60s)…"):
                            removal_output = run_engine(
                                Path(rein_path_str),
                                max_solutions=20,
                                traj_length=max(30, int(output.get("_K", 10))),
                                removal=True,
                            )
                        if removal_output and removal_output.get("removal_required"):
                            output["removal_required"] = removal_output["removal_required"]
                            st.session_state["output"] = output
                            st.rerun()
                        else:
                            st.error("Removal analysis returned no results.")
            else:
                st.success(f"Removal-UNSAT analysis complete — {len(removal_data)} edge(s) tested.")

                # ── Section 2: Results ───────────────────────────────
                st.markdown("### Results")

                req_edges = [e for e in removal_data if e["status"] == "REQUIRED"]
                sat_edges = [e for e in removal_data if e["status"] == "SAT"]

                c1, c2, c3 = st.columns(3)
                c1.metric("Edges tested", len(removal_data))
                c2.metric("Required (UNSAT)", len(req_edges))
                c3.metric("Not required (SAT)", len(sat_edges))

                # a) Required interaction list (from removal-UNSAT)
                st.markdown("#### Required Interactions")
                if req_edges:
                    for e in req_edges:
                        arrow = "→" if e["sign"] == "positive" else "⊣"
                        st.markdown(
                            f'<span style="color:#D32F2F;font-weight:bold;">'
                            f'{e["source"].replace("v_","")} {arrow} '
                            f'{e["target"].replace("v_","")}</span> '
                            f'({e["sign"]})',
                            unsafe_allow_html=True,
                        )
                else:
                    st.info(
                        "No structurally required interactions found. "
                        "All edges can be individually removed while maintaining "
                        "at least one consistent model."
                    )

                # b) Edge frequency × removal-UNSAT joined table
                st.markdown("#### Edge Frequency × Removal-UNSAT Classification")
                st.caption(
                    "Per-edge: how often it appeared across the baseline's enumerated "
                    "solutions, alongside its removal-UNSAT verdict. "
                    "**Required** = removing it makes the model UNSAT. "
                    "**Disallowed** = it never appeared in any enumerated solution. "
                    "**Inconclusive** = SAT on removal but appeared in ≥1 solution."
                )

                edge_freq = output.get("edge_frequency", [])
                sol_count = output.get("solutionCount", 0)

                if not edge_freq:
                    st.info("No edge-frequency data from the baseline run.")
                else:
                    # Build removal-status lookup from current run's data
                    removal_status_map = {
                        (e["source"], e["target"], e["sign"]): e["status"]
                        for e in removal_data
                    }

                    rows = []
                    for ef in sorted(edge_freq, key=lambda x: (x["source"], x["target"], x["sign"])):
                        key = (ef["source"], ef["target"], ef["sign"])
                        freq_val = ef["frequency"]
                        count = ef["count"]
                        status = removal_status_map.get(key)

                        if status == "REQUIRED":
                            classification = "Required"
                        elif freq_val <= 0.0:
                            classification = "Disallowed"
                        else:
                            classification = "Inconclusive"

                        edge_label = (
                            f"{key[0].replace('v_','')} → {key[1].replace('v_','')}"
                            if key[2] == "positive"
                            else f"{key[0].replace('v_','')} ⊣ {key[1].replace('v_','')}"
                        )

                        rows.append({
                            "Edge": edge_label,
                            "Sign": "Activation" if key[2] == "positive" else "Inhibition",
                            "Frequency": f"{freq_val:.0%}",
                            "Count": f"{count}/{sol_count}",
                            "Classification": classification,
                            "_cls": classification,
                        })

                    n_req = sum(1 for r in rows if r["_cls"] == "Required")
                    n_dis = sum(1 for r in rows if r["_cls"] == "Disallowed")
                    n_inc = sum(1 for r in rows if r["_cls"] == "Inconclusive")

                    m1, m2, m3 = st.columns(3)
                    m1.metric("Required", n_req)
                    m2.metric("Disallowed", n_dis)
                    m3.metric("Inconclusive", n_inc)

                    df = pd.DataFrame(rows)
                    display_cols = ["Edge", "Sign", "Frequency", "Count", "Classification"]
                    display_df = df[display_cols]

                    def _color_row(row):
                        cls = df.loc[row.name, "_cls"] if row.name in df.index else ""
                        if cls == "Required":
                            return ["background-color: #ffcdd2; font-weight: bold;"] * len(row)
                        elif cls == "Disallowed":
                            return ["background-color: #f5f5f5;"] * len(row)
                        elif cls == "Inconclusive":
                            return ["background-color: #fff3cd;"] * len(row)
                        return [""] * len(row)

                    styled = display_df.style.apply(_color_row, axis=1)
                    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Tab 6: Generated .rein file ───────────────────────────────────────
    with tab_rein:
        st.subheader("Generated .rein File")
        rein_text = output.get("_rein_text", "")
        if rein_text:
            n_lines = len(rein_text.splitlines())
            st.caption(f"{n_lines} lines")
            rein_path_str = output.get("_rein_path", "")
            download_name = Path(rein_path_str).name if rein_path_str else "model.rein"
            st.download_button(
                label="⬇️ Download .rein file",
                data=rein_text,
                file_name=download_name,
                mime="text/plain",
            )
            st.markdown(
                f'<div style="max-height:600px;overflow:auto;background:#f6f8fa;'
                f'border:1px solid #d0d7de;border-radius:6px;padding:12px;">'
                f'<pre style="margin:0;white-space:pre;font-size:13px;">'
                f'{rein_text.replace("<","&lt;").replace(">","&gt;")}</pre></div>',
                unsafe_allow_html=True,
            )
        else:
            st.info("No .rein file content stored.")


if __name__ == "__main__":
    main()
