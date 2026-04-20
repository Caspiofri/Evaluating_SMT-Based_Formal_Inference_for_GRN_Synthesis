"""
Convert an AEON Boolean network model into a RE:IN model and a JSON intermediate format.
The JSON is used later for simulation-based experiment generation.

Default behavior: preserve certainty from the AEON file
- interactions with '?' become optional in RE:IN
- interactions without '?' become definite in RE:IN

Use --all-optional to force all interactions to be optional.
"""
import argparse
import json
import re
from pathlib import Path
from typing import Dict, List, Set


# =========================
# AEON parsing
# =========================

def parse_aeon(file_path: Path, preserve_certainty: bool):
    variables: Set[str] = set()
    update_functions: Dict[str, str] = {}
    regulations: List[Dict] = []

    with file_path.open() as f:
        for raw_line in f:
            line = raw_line.split("//")[0].strip()
            if not line:
                continue

            # Update function
            if line.startswith("$"):
                var, expr = line[1:].split(":", 1)
                var = var.strip()
                expr = expr.strip()
                update_functions[var] = expr
                variables.add(var)
                variables |= extract_vars_from_expr(expr)
                continue

            # Regulation parsing
            regs = parse_regulation(line, preserve_certainty)
            if regs:
                regulations.extend(regs)
                for r in regs:
                    variables.add(r["src"])
                    variables.add(r["dst"])

    return variables, update_functions, regulations


def extract_vars_from_expr(expr: str) -> Set[str]:
    return set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr))


def parse_regulation(line: str, preserve_certainty: bool):
    """
    Returns a list of regulation dict(s), each dict always contains:
      src, dst, sign, optional (bool)

    If preserve_certainty is False: all returned regulations have optional=True.
    If preserve_certainty is True:
      - interactions with '?' => optional=True
      - interactions without '?' => optional=False
    """
    line = line.replace(" ", "")

    # (symbol, kind, has_question_mark)
    patterns = [
        ("->?", "positive", True),
        ("?->", "positive", True),
        ("-|?", "negative", True),
        ("?-|", "negative", True),
        ("?-",  "both",     True),
        ("-??", "both",     True),  # dataset quirk (treat as uncertain both)
        ("-?",  "both",     True),
        ("->",  "positive", False),
        ("-|",  "negative", False),
    ]

    for symbol, kind, is_uncertain in patterns:
        if symbol in line:
            src, dst = line.split(symbol)

            optional = True if not preserve_certainty else is_uncertain

            if kind == "both":
                return [
                    {"src": src, "dst": dst, "sign": "positive", "optional": optional},
                    {"src": src, "dst": dst, "sign": "negative", "optional": optional},
                ]

            return [{
                "src": src,
                "dst": dst,
                "sign": kind,
                "optional": optional
            }]

    return []


# =========================
# Input detection
# =========================

def detect_inputs(variables, update_functions, regulations):
    incoming = {v: 0 for v in variables}
    for r in regulations:
        incoming[r["dst"]] += 1

    return [
        v for v in variables
        if v not in update_functions and incoming[v] == 0
    ]


def add_input_self_loops(regulations, inputs):
    # Inputs get a positive optional self-loop to enable stable input dynamics in RE:IN.
    for v in inputs:
        regulations.append({
            "src": v,
            "dst": v,
            "sign": "positive",
            "optional": True
        })


# =========================
# Writing RE:IN
# =========================

def write_rein(rein_path: Path, variables, regulations):
    with rein_path.open("w") as f:
        # Header
        f.write("// Synchronous dynamics\n")
        f.write("directive updates sync;\n\n")
        f.write("// Default regulation conditions\n")
        f.write("directive regulation legacy;\n\n")

        # Variables
        parts = [f"{v}[-+] (0..17)" for v in sorted(variables)]
        f.write("; ".join(parts) + ";\n\n")

        # Regulations
        for r in regulations:
            if r["optional"]:
                f.write(f"{r['src']} {r['dst']} {r['sign']} optional;\n")
            else:
                f.write(f"{r['src']} {r['dst']} {r['sign']};\n")


# =========================
# Writing JSON
# =========================

def write_json(json_path: Path, variables, update_functions, inputs, regulations):
    data = {
        "variables": sorted(variables),
        "update_functions": update_functions,
        "inputs": sorted(inputs),
        "regulations": regulations
    }

    with json_path.open("w") as f:
        json.dump(data, f, indent=2)


# =========================
# Public pipeline function (used by rein_add_experiments)
# =========================

def aeon_to_rein_pipeline(aeon_file: Path,
                          rein_file: Path,
                          json_file: Path,
                          preserve_certainty: bool = True):
    variables, update_functions, regulations = parse_aeon(aeon_file, preserve_certainty)
    inputs = detect_inputs(variables, update_functions, regulations)
    add_input_self_loops(regulations, inputs)

    write_rein(rein_file, variables, regulations)
    write_json(json_file, variables, update_functions, inputs, regulations)


# =========================
# CLI
# =========================

def parse_args():
    parser = argparse.ArgumentParser(description="Convert an AEON model to RE:IN + JSON.")
    parser.add_argument(
        "--model-name",
        default="example",
        help="Model base name without extension (e.g., '023')."
    )
    parser.add_argument(
        "--all-optional",
        action="store_true",
        help="Make all interactions optional (ignore certainty from the AEON file)."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    BASE_DIR = Path(__file__).resolve().parent
    aeon_file = BASE_DIR / "aeon" / f"{args.model_name}.aeon"
    rein_file = BASE_DIR / "rein" / f"{args.model_name}.rein"
    json_file = BASE_DIR / "rein" / f"{args.model_name}.json"

    aeon_to_rein_pipeline(
        aeon_file,
        rein_file,
        json_file,
        preserve_certainty=not args.all_optional
    )