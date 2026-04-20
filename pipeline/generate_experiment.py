#!/usr/bin/env python3
"""
Generate ground truth + RE:IN files for an experiment.

For each .aeon model, produces:
  1. Ground truth JSON (truth tables, trajectories)
  2. .rein file (base regulations + experiment observations)

The same random trajectories from ground truth are used as observations
in the .rein file, ensuring RE:IN is given the correct data to recover.

Usage:
  python3 generate_experiment.py <aeon_dir> <output_dir> --N 5 --K 10

Example (E1 sanity):
  python3 generate_experiment.py \
      ../models/experiment_1_sanity \
      ../results/experiment_1 \
      --N 5 --K 10
"""

import json
import random
import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


# ---------------------------------------------------------------------------
# AEON parsing (self-contained — no cross-imports needed)
# ---------------------------------------------------------------------------

def parse_aeon(filepath: Path):
    """Parse .aeon file → (update_functions, input_nodes, regulations).

    Returns:
        update_functions: dict gene→expr
        input_nodes: sorted list of input gene names
        variables: set of all gene names
        regulations: list of {src, dst, sign, optional}
    """
    update_functions: Dict[str, str] = {}
    graph_genes: Set[str] = set()
    regulations = []

    with open(filepath, "r") as f:
        for line in f:
            line = line.split("//")[0].strip()
            if not line:
                continue

            if line.startswith("$"):
                match = re.match(r"^\$(\S+):\s*(.+)$", line)
                if match:
                    gene = match.group(1)
                    expr = match.group(2).strip()
                    update_functions[gene] = expr
                    graph_genes.add(gene)
                    graph_genes |= set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))
                continue

            # Parse regulation edges
            regs = _parse_regulation(line)
            for r in regs:
                regulations.append(r)
                graph_genes.add(r["src"])
                graph_genes.add(r["dst"])

    input_nodes = sorted(graph_genes - set(update_functions.keys()))
    return update_functions, input_nodes, graph_genes, regulations


def _parse_regulation(line: str):
    """
    an AEON regulation line into regulation dicts."""
    clean = line.replace(" ", "")
    patterns = [
        ("-??", "both", True),
        ("->?", "positive", True),
        ("?->", "positive", True),
        ("-|?", "negative", True),
        ("?-|", "negative", True),
        ("-?", "both", True),
        ("->", "positive", False),
        ("-|", "negative", False),
    ]
    for symbol, kind, optional in patterns:
        if symbol in clean:
            parts = clean.split(symbol, 1)
            if len(parts) != 2:
                continue
            src, dst = parts
            if kind == "both":
                return [
                    {"src": src, "dst": dst, "sign": "positive", "optional": optional},
                    {"src": src, "dst": dst, "sign": "negative", "optional": optional},
                ]
            return [{"src": src, "dst": dst, "sign": kind, "optional": optional}]
    return []


# ---------------------------------------------------------------------------
# Simulation
# ---------------------------------------------------------------------------

def _aeon_to_python(expr: str) -> str:
    py = expr.replace("!", "not ")
    py = py.replace("&", " and ")
    py = py.replace("|", " or ")
    return re.sub(r"\s+", " ", py).strip()


def simulate(update_functions: Dict[str, str], input_nodes: List[str],
             initial_state: Dict[str, int], K: int) -> List[Dict[str, int]]:
    """Synchronous simulation for K steps. Returns trajectory of K+1 states."""
    trajectory = [dict(initial_state)]
    current = dict(initial_state)

    for _ in range(K):
        next_state = {}
        for gene in input_nodes:
            next_state[gene] = current[gene]
        for gene, expr in update_functions.items():
            py_expr = _aeon_to_python(expr)
            result = eval(py_expr, {"__builtins__": {}}, current)
            next_state[gene] = int(bool(result))
        trajectory.append(next_state)
        current = next_state

    return trajectory


# ---------------------------------------------------------------------------
# Ground truth generation (truth tables + trajectories)
# ---------------------------------------------------------------------------

def extract_regulators(expr: str) -> List[str]:
    return sorted(set(re.findall(r"\bv_[A-Za-z0-9_]+\b", expr)))


def expression_to_truth_table(expression: str, regulators: List[str]) -> Dict[str, int]:
    """Build truth table as {key_str: output_value}."""
    from itertools import product as iterproduct
    py_expr = _aeon_to_python(expression)
    truth_table = {}
    for values in iterproduct([0, 1], repeat=len(regulators)):
        assignment = dict(zip(regulators, values))
        result = eval(py_expr, {"__builtins__": {}}, assignment)
        key = ", ".join(f"{r}={assignment[r]}" for r in regulators)
        truth_table[key] = int(bool(result))
    return truth_table


def generate_ground_truth(aeon_path: Path, N: int, K: int, seed: int = None) -> dict:
    """Generate complete ground truth from an .aeon model."""
    if seed is not None:
        random.seed(seed)

    update_functions, input_nodes, variables, regulations = parse_aeon(aeon_path)
    all_genes = sorted(set(list(update_functions.keys()) + input_nodes))

    # Per-gene truth tables
    genes_info = []
    for gene in all_genes:
        is_input = gene in input_nodes
        if is_input:
            genes_info.append({
                "name": gene, "is_input": True,
                "update_function": None, "regulators": [],
                "truth_table": {}, "truth_table_size": 0,
            })
            continue

        expr = update_functions[gene]
        regs = extract_regulators(expr)
        tt = expression_to_truth_table(expr, regs)

        # Edge info for this gene
        gene_edges = [r for r in regulations if r["dst"] == gene]
        reg_info = []
        for r in regs:
            edge_signs = [e["sign"] for e in gene_edges if e["src"] == r]
            reg_info.append({"name": r, "edge_signs": edge_signs if edge_signs else ["implicit"]})

        genes_info.append({
            "name": gene, "is_input": False,
            "update_function": expr,
            "regulators": reg_info,
            "num_regulators": len(regs),
            "truth_table": tt,
            "truth_table_size": len(tt),
        })

    # Generate experiments (trajectories)
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

    return {
        "source_file": str(aeon_path),
        "model_name": aeon_path.stem,
        "total_genes": len(all_genes),
        "total_update_functions": len(update_functions),
        "total_inputs": len(input_nodes),
        "input_nodes": input_nodes,
        "genes": genes_info,
        "experiment_params": {"N": N, "K": K},
        "experiments": experiments,
    }


# ---------------------------------------------------------------------------
# .rein file generation
# ---------------------------------------------------------------------------

def write_rein_file(rein_path: Path, variables: Set[str], regulations: list,
                    input_nodes: List[str], experiments: list, K: int,
                    force_optional: bool = True):
    """Write complete .rein file: base regulations + experiment observations."""

    # Add input self-loops
    all_regulations = list(regulations)
    for v in input_nodes:
        already_has = any(r["src"] == v and r["dst"] == v for r in all_regulations)
        if not already_has:
            all_regulations.append({"src": v, "dst": v, "sign": "positive", "optional": True})

    sorted_vars = sorted(variables)

    with open(rein_path, "w") as f:
        f.write("// Synchronous dynamics\n")
        f.write("directive updates sync;\n\n")
        f.write("// Default regulation conditions\n")
        f.write("directive regulation legacy;\n\n")

        # Variable declarations
        parts = [f"{v}[-+] (0..17)" for v in sorted_vars]
        f.write("; ".join(parts) + ";\n\n")

        # Regulations
        for r in all_regulations:
            opt = " optional" if (force_optional or r.get("optional", False)) else ""
            f.write(f"{r['src']} {r['dst']} {r['sign']}{opt};\n")

        # Experiments
        f.write("\n\n// =====================\n")
        f.write("// Experiments\n")
        f.write("// =====================\n\n")

        for exp in experiments:
            i = exp["id"]
            init = exp["init_state"]
            final = exp["final_state"]

            f.write(f"// Experiment {i}\n")
            f.write(f"#Experiment{i}[0] |= $INIT{i} \"initial state\";\n")
            f.write(f"#Experiment{i}[0] |= $NoKnockDowns \"no knockdowns\";\n")
            f.write(f"#Experiment{i}[0] |= $NoOverExpression \"no overexpression\";\n")
            f.write(f"#Experiment{i}[{K}] |= $FIN{i} \"final state\";\n\n")

            # INIT block
            init_lines = [f"{v} = {val}" for v, val in sorted(init.items())]
            f.write(f"$INIT{i} := {{\n  " + " and\n  ".join(init_lines) + "\n};\n\n")

            # FIN block
            fin_lines = [f"{v} = {val}" for v, val in sorted(final.items())]
            f.write(f"$FIN{i} := {{\n  " + " and\n  ".join(fin_lines) + "\n};\n\n")

        # Global blocks
        f.write("$NoKnockDowns := {\n  ")
        f.write(" and\n  ".join(f"KO({v}) = 0" for v in sorted_vars))
        f.write("\n};\n\n")

        f.write("$NoOverExpression := {\n  ")
        f.write(" and\n  ".join(f"FE({v}) = 0" for v in sorted_vars))
        f.write("\n};\n\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def process_model(aeon_path: Path, output_dir: Path, N: int, K: int, seed: int = None):
    """Process a single .aeon model: generate ground truth + .rein file."""
    model_name = aeon_path.stem
    model_dir = output_dir / model_name
    model_dir.mkdir(parents=True, exist_ok=True)

    gt_path = model_dir / f"{model_name}_ground_truth.json"
    rein_path = model_dir / f"{model_name}.rein"

    print(f"Processing {model_name}...")

    # Generate ground truth (with fixed seed for reproducibility)
    gt = generate_ground_truth(aeon_path, N=N, K=K, seed=seed)

    # Save ground truth
    with open(gt_path, "w") as f:
        json.dump(gt, f, indent=2)
    print(f"  Ground truth: {gt_path}")

    # Generate .rein file using the SAME experiments from ground truth
    update_functions, input_nodes, variables, regulations = parse_aeon(aeon_path)
    write_rein_file(rein_path, variables, regulations, input_nodes, gt["experiments"], K)
    print(f"  REIN file:    {rein_path}")

    # Summary
    print(f"  Genes: {gt['total_genes']} ({gt['total_update_functions']} functions, {gt['total_inputs']} inputs)")
    print(f"  Experiments: {N} trajectories, K={K} steps")
    print()

    return gt_path, rein_path


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate ground truth + .rein files for an experiment")
    parser.add_argument("aeon_dir", type=Path, help="Directory containing .aeon model files")
    parser.add_argument("output_dir", type=Path, help="Output directory for results")
    parser.add_argument("--N", type=int, default=5, help="Number of experiments (trajectories)")
    parser.add_argument("--K", type=int, default=10, help="Trajectory length (simulation steps)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility")
    args = parser.parse_args()

    if not args.aeon_dir.exists():
        print(f"Error: directory not found: {args.aeon_dir}")
        sys.exit(1)

    aeon_files = sorted(args.aeon_dir.glob("*.aeon"))
    if not aeon_files:
        print(f"Error: no .aeon files found in {args.aeon_dir}")
        sys.exit(1)

    args.output_dir.mkdir(parents=True, exist_ok=True)

    print(f"Experiment generation")
    print(f"  Models: {len(aeon_files)} from {args.aeon_dir}")
    print(f"  Output: {args.output_dir}")
    print(f"  Params: N={args.N}, K={args.K}, seed={args.seed}")
    print()

    for i, aeon_path in enumerate(aeon_files):
        # Different seed per model but deterministic
        model_seed = args.seed + i
        process_model(aeon_path, args.output_dir, N=args.N, K=args.K, seed=model_seed)

    print(f"Done. Generated files for {len(aeon_files)} models in {args.output_dir}")


if __name__ == "__main__":
    main()
