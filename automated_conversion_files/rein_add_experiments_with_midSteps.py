"""
rein_add_experiments_with_midSteps.py

Extended version of rein_add_experiments.py that records three timepoints per experiment:
INIT at time 0, MID at --k-mid, and FIN at --k-end (--k-end must be >= --k-mid).

Workflow:
1) Convert the input model (--model-type aeon|sbml, --model-name <NAME>) into base RE:IN + JSON.
2) Generate --n experiments by:
   - sampling a unique INIT state,
   - simulating to time --k-mid to obtain MID,
   - continuing simulation to time --k-end to obtain FIN,
   - recording observations at times 0, --k-mid, and --k-end.
3) Append global "no perturbation" constraints.

By default, the conversion preserves interaction certainty when available.
Use --all-optional to force all interactions to be optional.
"""

import argparse
import json
import random
import re
from pathlib import Path
from typing import Dict

from aeon_to_rein import aeon_to_rein_pipeline
from sbml_to_rein import sbml_to_rein_pipeline


# =========================
# Configuration (DEFAULTS)
# =========================

BASE_DIR = Path(__file__).resolve().parent

DEFAULT_MODEL_NAME = "example"
DEFAULT_MODEL_TYPE = "aeon"  # "aeon" or "sbml"

DEFAULT_K_MID = 2
DEFAULT_K_END = 4
DEFAULT_N = 5


# =========================
# CLI
# =========================

def parse_args():
    parser = argparse.ArgumentParser(
        description="Generate a RE:IN file with synthetic experiments at three timepoints "
                    "(INIT, MID, FIN) from an AEON or SBML model via an intermediate JSON."
    )
    parser.add_argument("--model-type", choices=["aeon", "sbml"], default=DEFAULT_MODEL_TYPE,
                        help="Input model format (aeon or sbml).")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME,
                        help="Model base name without extension (e.g., '023').")
    parser.add_argument("--k-mid", type=int, default=DEFAULT_K_MID,
                        help="Timepoint of MID observation (>= 0).")
    parser.add_argument("--k-end", type=int, default=DEFAULT_K_END,
                        help="Timepoint of FINAL observation (must be >= k-mid).")
    parser.add_argument("--n", type=int, default=DEFAULT_N,
                        help="Number of experiments to generate.")
    parser.add_argument("--all-optional", action="store_true",
                        help="Force all interactions to be optional in the generated RE:IN model "
                             "(i.e., do not preserve certainty from the input file).")
    return parser.parse_args()


# =========================
# JSON loading
# =========================

def load_json(json_path: Path):
    with json_path.open(encoding="utf-8") as f:
        return json.load(f)


# =========================
# Simulation
# =========================

def random_initial_state(variables):
    return {v: random.randint(0, 1) for v in variables}


def state_to_tuple(state):
    """Convert a state dict to a hashable, ordered tuple."""
    return tuple((var, state[var]) for var in sorted(state.keys()))


def eval_update_function(expr: str, state: Dict[str, int]) -> int:
    # IMPORTANT: keep AEON → Python logical translation
    python_expr = expr.replace("!", " not ").replace("&", " and ").replace("|", " or ")

    for var, value in state.items():
        python_expr = re.sub(rf"\b{var}\b", str(bool(value)), python_expr)

    return int(eval(python_expr))


def simulate_steps(start_state, update_functions, steps):
    """
    Simulate 'steps' synchronous updates starting from 'start_state'.
    Returns the resulting state.
    """
    state = start_state.copy()

    for _ in range(steps):
        next_state = state.copy()
        for var, expr in update_functions.items():
            next_state[var] = eval_update_function(expr, state)
        state = next_state

    return state


# =========================
# RE:IN experiment blocks
# =========================

def format_state_block(name, state):
    lines = [f"{var} = {val}" for var, val in sorted(state.items())]
    return f"${name} := {{\n  " + " and\n  ".join(lines) + "\n};\n"


def generate_experiment_block(i, init_state, mid_state, final_state, k_mid, k_end):
    block = ""
    block += f"// Experiment {i}\n"
    block += f"#Experiment{i}[0] |= $INIT{i} \"initial state\";\n"
    block += f"#Experiment{i}[0] |= $NoKnockDowns \"no knockdowns\";\n"
    block += f"#Experiment{i}[0] |= $NoOverExpression \"no overexpression\";\n"
    block += f"#Experiment{i}[{k_mid}] |= $MID{i} \"mid state\";\n"
    block += f"#Experiment{i}[{k_end}] |= $FIN{i} \"final state\";\n\n"

    block += format_state_block(f"INIT{i}", init_state) + "\n"
    block += format_state_block(f"MID{i}", mid_state) + "\n"
    block += format_state_block(f"FIN{i}", final_state) + "\n"
    return block


def generate_global_blocks(variables):
    block = "$NoKnockDowns := {\n  "
    block += " and\n  ".join(f"KO({v}) = 0" for v in variables)
    block += "\n};\n\n"

    block += "$NoOverExpression := {\n  "
    block += " and\n  ".join(f"FE({v}) = 0" for v in variables)
    block += "\n};\n\n"

    return block


# =========================
# Main
# =========================

def main():
    args = parse_args()

    model_name = args.model_name
    model_type = args.model_type
    k_mid = args.k_mid
    k_end = args.k_end
    n_experiments = args.n

    preserve_certainty = not args.all_optional

    if k_mid < 0:
        raise ValueError("--k-mid must be >= 0")
    if k_end < k_mid:
        raise ValueError("--k-end must be >= --k-mid")
    if n_experiments <= 0:
        raise ValueError("--n must be > 0")

    aeon_file = BASE_DIR / "aeon" / f"{model_name}.aeon"
    sbml_file = BASE_DIR / "sbml" / f"{model_name}.sbml"
    rein_file = BASE_DIR / "rein" / f"{model_name}.rein"
    json_file = BASE_DIR / "rein" / f"{model_name}.json"

    # Stage 1: Model → RE:IN base + JSON
    if model_type == "aeon":
        aeon_to_rein_pipeline(aeon_file, rein_file, json_file, preserve_certainty=preserve_certainty)
    elif model_type == "sbml":
        sbml_to_rein_pipeline(sbml_file, rein_file, json_file, preserve_certainty=preserve_certainty)
    else:
        raise ValueError("--model-type must be 'aeon' or 'sbml'")

    # Stage 2: Experiments
    data = load_json(json_file)

    used_initial_states = set()
    max_attempts = 100

    with rein_file.open("a", encoding="utf-8") as f:
        f.write("\n\n// =====================\n")
        f.write("// Experiments\n")
        f.write("// =====================\n\n")

        for i in range(n_experiments):
            attempts = 0

            while attempts < max_attempts:
                init_state = random_initial_state(data["variables"])
                init_key = state_to_tuple(init_state)

                if init_key not in used_initial_states:
                    used_initial_states.add(init_key)
                    break

                attempts += 1

            if attempts == max_attempts:
                print("⚠ No more unique initial states available. Stopping experiments.")
                break

            mid_state = simulate_steps(init_state, data["update_functions"], k_mid)
            final_state = simulate_steps(mid_state, data["update_functions"], k_end - k_mid)

            f.write(generate_experiment_block(i, init_state, mid_state, final_state, k_mid, k_end))

        f.write(generate_global_blocks(data["variables"]))

    print("✔ Full pipeline completed successfully")


if __name__ == "__main__":
    main()