"""Compares the observed outcome of each case with ci/expected.json, writes results.json and a Markdown table.

Every case must show its START line, so a case that never ran fails instead of passing vacuously.
"""
import argparse
import json
import os
import re
import sys

parser = argparse.ArgumentParser()
parser.add_argument("--runtime", required=True)
parser.add_argument("--expected", required=True)
parser.add_argument("--results", required=True)
parser.add_argument("--summary")
arguments = parser.parse_args()

expected = json.load(open(arguments.expected))[arguments.runtime]


def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


def observe(case, folder):
    repro = read(f"{folder}/repro.txt")
    logcat = read(f"{folder}/logcat.txt")
    start = re.search(rf"START case={case} .*runtime=(\w+)", repro)
    result = re.search(rf"RESULT case={case} outcome=(\w+)(.*)", repro)
    callback = f"CALLBACK case={case}" in repro
    problems = []

    if not start:
        return "did-not-run", ["no START line: the app did not run this case"], {}
    if start.group(1) != arguments.runtime:
        problems.append(f"app reports runtime {start.group(1)}, expected {arguments.runtime}")

    details = {"runtimeReported": start.group(1), "callbackSeen": callback}
    stack_overflow = re.search(r"stack overflow", logcat, re.IGNORECASE) is not None
    invoker_frames = len(re.findall(r"Invoker", logcat))
    details.update({"stackOverflowInLogcat": stack_overflow, "invokerMentions": invoker_frames})

    if result is None:
        if stack_overflow and invoker_frames >= 2:
            return "stack-overflow", problems, details
        return "crashed-without-signature", problems + ["no RESULT line and no stack overflow with Invoker frames in logcat"], details

    details["resultLine"] = result.group(0)
    if result.group(1) == "returned":
        return ("returned" if callback else "returned-without-callback"), problems, details
    if "activationFailure=True" in result.group(2):
        return "activation-failure", problems, details
    return "other-exception", problems, details


rows = []
failed = False
for case, want in expected.items():
    folder = f"{arguments.results}/cases/{case}"
    got, problems, details = observe(case, folder)
    match = got == want and not problems
    failed |= not match
    rows.append({"case": case, "expected": want, "observed": got, "match": match, "problems": problems, **details})

os.makedirs(arguments.results, exist_ok=True)
json.dump({"runtime": arguments.runtime, "cases": rows}, open(f"{arguments.results}/results.json", "w"), indent=2)

lines = [f"### {arguments.runtime}", "", "| Case | Expected | Observed | Match | Notes |", "|---|---|---|---|---|"]
for row in rows:
    notes = "; ".join(row["problems"]) or row.get("resultLine", "")
    lines.append(f"| {row['case']} | {row['expected']} | {row['observed']} | {'yes' if row['match'] else 'NO'} | {notes.replace('|', '/')} |")
table = "\n".join(lines) + "\n"
print(table)
if arguments.summary:
    open(arguments.summary, "a").write(table)

sys.exit(1 if failed else 0)
