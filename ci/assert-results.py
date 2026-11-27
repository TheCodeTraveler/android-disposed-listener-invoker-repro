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
parser.add_argument("--versions")
parser.add_argument("--api-level")
arguments = parser.parse_args()

expected = json.load(open(arguments.expected))[arguments.runtime]


def read(path):
    try:
        return open(path, encoding="utf-8", errors="replace").read()
    except OSError:
        return ""


LOGCAT_LINE = re.compile(r"^\S+\s+\S+\s+(\d+)\s+(\d+)\s+([A-Z])\s+(\S+)\s*: ?(.*)$")

# CoreCLR prints a recursive cycle only once, between two dashed lines under "Repeated N times:"
REPEATED_BLOCK_HEADER = re.compile(r"^Repeated (\d+) times:$")
REPEATED_BLOCK_EDGE = re.compile(r"^-{16,}$")

LISTENER_TYPE = {
    "runnable": "RunnableListenerWithoutActivationConstructor",
    "accessibility": "AccessibilityListenerWithoutActivationConstructor",
}

INVOKER_METHOD = {
    "runnable": "IRunnableInvoker.Run(",
    "accessibility": "IAccessibilityStateChangeListenerInvoker.OnAccessibilityStateChanged(",
}

MINIMUM_LOOPING_FRAMES = 10


def lines_of_pid(logcat, pid):
    """Only the app's own lines count: a whole-device logcat also holds other processes and their crashes."""
    for line in logcat.splitlines():
        match = LOGCAT_LINE.match(line)
        if match and match.group(1) == pid:
            yield match.group(2), match.group(3), match.group(4), match.group(5)


def count_looping_frames(app_lines, kind):
    invoker_interface = INVOKER_METHOD[kind].split(".")[0]
    invoker_frames = 0
    native_frames = 0
    largest_repeat = 0
    block_by_thread = {}
    for thread, _, tag, message in app_lines:
        if tag != "DOTNET":
            continue
        text = message.strip()
        repeats, phase = block_by_thread.get(thread, (1, "outside"))
        header = REPEATED_BLOCK_HEADER.match(text)
        if header:
            block_by_thread[thread] = (int(header.group(1)), "header")
            largest_repeat = max(largest_repeat, int(header.group(1)))
            continue
        if REPEATED_BLOCK_EDGE.match(text):
            block_by_thread[thread] = (repeats, "inside") if phase == "header" else (1, "outside")
            continue
        weight = repeats if phase == "inside" else 1
        if INVOKER_METHOD[kind] in text:
            invoker_frames += weight
        if "Invoker.__n_" in text and invoker_interface in text:
            native_frames += weight
    return invoker_frames, native_frames, largest_repeat


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

    pid_match = re.search(rf"^\S+\s+\S+\s+(\d+)\s+\d+\s+I ListenerRepro\s*: START case={case} ", logcat, re.MULTILINE)
    if not pid_match:
        return "did-not-run", problems + ["no START line with a process id in logcat.txt"], {}
    pid = pid_match.group(1)
    app_lines = list(lines_of_pid(logcat, pid))
    kind = case.split("-")[0]
    done = any(tag == "ListenerRepro" and message.startswith(f"DONE case={case}") for _, _, tag, message in app_lines)

    details = {"runtimeReported": start.group(1), "callbackSeen": callback, "appPid": pid, "doneSeen": done}

    stack_overflow = any(level == "E" and tag == "DOTNET" and message.startswith("Stack overflow.") for _, level, tag, message in app_lines)
    invoker_frames, native_frames, largest_repeat = count_looping_frames(app_lines, kind)
    details.update({"stackOverflowFromAppPid": stack_overflow, "invokerFrames": invoker_frames, "nativeInvokerFrames": native_frames, "largestRepeatedBlock": largest_repeat})

    if result is None:
        if stack_overflow and not done and invoker_frames >= MINIMUM_LOOPING_FRAMES and native_frames >= MINIMUM_LOOPING_FRAMES:
            return "stack-overflow", problems, details
        return "crashed-without-signature", problems + [
            f"no RESULT line, and no 'Stack overflow.' from pid {pid} with at least {MINIMUM_LOOPING_FRAMES} {INVOKER_METHOD[kind]} and __n_ frames (a frame inside 'Repeated N times:' counts N times)"], details

    details["resultLine"] = result.group(0)
    if result.group(1) == "returned":
        return ("returned" if callback else "returned-without-callback"), problems, details
    if "activationFailure=True" in result.group(2):
        exception_text = " ".join(message for _, level, tag, message in app_lines if tag == "ListenerRepro" and level == "E") + result.group(2)
        if LISTENER_TYPE[kind] not in exception_text:
            return "activation-failure-other-type", problems + [f"exception text does not name {LISTENER_TYPE[kind]}"], details
        return "activation-failure", problems, details
    return "other-exception", problems, details


rows = []
failed = False
if not os.path.isdir(f"{arguments.results}/cases"):
    print("build or emulator step produced no results: no cases/ folder")
for case, want in expected.items():
    folder = f"{arguments.results}/cases/{case}"
    if not os.path.isdir(folder):
        got, problems, details = "did-not-run", ["build or emulator step produced no results"], {}
    else:
        got, problems, details = observe(case, folder)
    match = got == want and not problems
    failed |= not match
    rows.append({"case": case, "expected": want, "observed": got, "match": match, "problems": problems, **details})

os.makedirs(arguments.results, exist_ok=True)
json.dump({"runtime": arguments.runtime, "cases": rows}, open(f"{arguments.results}/results.json", "w"), indent=2)

VERDICT = {
    "coreclr": "Bug reproduced: both -plain cases died with a stack overflow looping in the Invoker; all controls and workarounds returned",
    "mono": "Contrast as expected: -plain cases threw \"Unable to activate instance\" naming the listener; all controls and workarounds returned",
}
wrong = [row["case"] for row in rows if not row["match"]]
verdict = VERDICT.get(arguments.runtime, "Matches expected") if not wrong else f"NOT as expected: {', '.join(wrong)}"
versions = read(arguments.versions).strip().replace("\n", "; ") if arguments.versions else ""

heading = arguments.runtime + (f" api{arguments.api_level}" if arguments.api_level else "")
lines = [f"### {heading}", "", f"**{verdict}**", ""]
if versions:
    lines += [f"Versions: {versions}", ""]
lines += ["| Case | Expected | Observed | Match | Notes |", "|---|---|---|---|---|"]
for row in rows:
    notes = "; ".join(row["problems"]) or row.get("resultLine", "")
    lines.append(f"| {row['case']} | {row['expected']} | {row['observed']} | {'yes' if row['match'] else 'NO'} | {notes.replace('|', '/')} |")
table = "\n".join(lines) + "\n"
print(table)
if arguments.summary:
    open(arguments.summary, "a").write(table)

sys.exit(1 if failed else 0)
