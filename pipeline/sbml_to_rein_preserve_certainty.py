from pathlib import Path
import json
import xml.etree.ElementTree as ET

QUAL_NS = "{http://www.sbml.org/sbml/level3/version1/qual/version1}"
MATH_NS = "{http://www.w3.org/1998/Math/MathML}"
CORE_NS = "{http://www.sbml.org/sbml/level3/version1/core}"

# ========================
# MathML parsing
# ========================

def parse_mathml(node):
    if node.tag == f"{MATH_NS}apply":
        op = node[0].tag.replace(MATH_NS, "")

        if op in {"and", "or"}:
            return {"op": op, "args": [parse_mathml(c) for c in node[1:]]}

        if op == "not":
            return {"op": "not", "arg": parse_mathml(node[1])}

        if op == "eq":
            var = node[1].text
            return {"var": var}

        raise ValueError(f"Unsupported MathML operator: {op}")

    raise ValueError(f"Unexpected MathML node: {node.tag}")


# ========================
# AST → logical string
# ========================

def ast_to_string(expr, parent_prec=0):
    if "var" in expr:
        return expr["var"]

    if expr["op"] == "not":
        return "!" + ast_to_string(expr["arg"], parent_prec=3)

    if expr["op"] in {"and", "or"}:
        prec = 2 if expr["op"] == "and" else 1
        op_symbol = " & " if expr["op"] == "and" else " | "
        parts = [ast_to_string(a, parent_prec=prec) for a in expr["args"]]
        s = op_symbol.join(parts)
        return f"({s})" if prec < parent_prec else s

    raise ValueError(f"Unsupported AST node: {expr}")


# ========================
# SBML parsing
# ========================

def parse_sbml(file_path: Path):
    tree = ET.parse(file_path)
    root = tree.getroot()

    model = root.find(f"{CORE_NS}model")
    if model is None:
        raise ValueError("SBML <model> element not found")

    variables = []
    los = model.find(f"{QUAL_NS}listOfQualitativeSpecies")
    if los is None:
        raise ValueError("No listOfQualitativeSpecies found")

    for qs in los:
        variables.append(qs.attrib[f"{QUAL_NS}id"])

    update_functions = {}
    regulations = []

    transitions = model.find(f"{QUAL_NS}listOfTransitions")
    if transitions is not None:
        for tr in transitions:
            output = tr.find(f"{QUAL_NS}listOfOutputs")[0]
            target = output.attrib[f"{QUAL_NS}qualitativeSpecies"]

            inputs = tr.find(f"{QUAL_NS}listOfInputs")
            if inputs is not None:
                for inp in inputs:
                    src = inp.attrib[f"{QUAL_NS}qualitativeSpecies"]
                    sign = inp.attrib.get(f"{QUAL_NS}sign", "unknown")

                    # ---- Preserve certainty ----
                    if sign == "unknown":
                        # uncertain sign => allow both signs as optional
                        regulations.append({
                            "src": src, "dst": target,
                            "sign": "positive", "optional": True
                        })
                        regulations.append({
                            "src": src, "dst": target,
                            "sign": "negative", "optional": True
                        })
                    else:
                        # certain sign => definite interaction (non-optional)
                        regulations.append({
                            "src": src, "dst": target,
                            "sign": sign, "optional": False
                        })

            fterms = tr.find(f"{QUAL_NS}listOfFunctionTerms")
            if fterms is not None:
                for ft in fterms:
                    if ft.tag.endswith("functionTerm"):
                        math = ft.find(f"{MATH_NS}math")
                        ast = parse_mathml(math[0])
                        update_functions[target] = ast_to_string(ast)

    # -------- Inputs --------
    incoming = {v: set() for v in variables}
    for r in regulations:
        incoming[r["dst"]].add(r["src"])

    # detect inputs based on update_functions (like AEON)
    inputs = [
        v for v in variables
        if v not in update_functions and len(incoming[v]) == 0
    ]

    return variables, update_functions, inputs, regulations


# ========================
# RE:IN writing
# ========================

def write_rein(variables, regulations, inputs, file_path: Path):
    with open(file_path, "w", encoding="utf-8") as f:
        f.write("// Synchronous dynamics\n")
        f.write("directive updates sync;\n\n")
        f.write("// Default regulation conditions\n")
        f.write("directive regulation legacy;\n\n")

        for v in variables:
            f.write(f"{v}[-+] (0..17); ")
        f.write("\n\n")

        # ---- Preserve certainty in output ----
        for r in regulations:
            if r["optional"]:
                f.write(f"{r['src']} {r['dst']} {r['sign']} optional;\n")
            else:
                f.write(f"{r['src']} {r['dst']} {r['sign']};\n")

        # inputs: keep your existing approach
        for v in inputs:
            f.write(f"{v} {v} positive optional;\n")


# ========================
# JSON writing
# ========================

def write_json(variables, update_functions, inputs, regulations, file_path: Path):
    data = {
        "variables": variables,
        "update_functions": update_functions,
        "inputs": inputs,
        "regulations": regulations
    }

    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


# ========================
# Pipeline
# ========================

def sbml_to_rein_pipeline(sbml_file: Path, rein_file: Path, json_file: Path):
    variables, update_functions, inputs, regulations = parse_sbml(sbml_file)
    write_rein(variables, regulations, inputs, rein_file)
    write_json(variables, update_functions, inputs, regulations, json_file)


# ========================
# Script mode
# ========================

if __name__ == "__main__":
    BASE_DIR = Path(__file__).resolve().parent
    MODEL_NAME = "example"

    SBML_FILE = BASE_DIR / "sbml" / f"{MODEL_NAME}.sbml"
    REIN_FILE = BASE_DIR / "rein" / f"{MODEL_NAME}.rein"
    JSON_FILE = BASE_DIR / "rein" / f"{MODEL_NAME}.json"

    sbml_to_rein_pipeline(SBML_FILE, REIN_FILE, JSON_FILE)