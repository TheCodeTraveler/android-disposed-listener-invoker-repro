#!/usr/bin/env bash
# One launch per case. A crash in one case must not stop the others, so there is no `set -e`.
set -u -o pipefail

runtime="${1:?usage: run-cases.sh <coreclr|mono>}"
package=com.example.disposedlistener
artifacts="artifacts/$runtime/cases"
mkdir -p "$artifacts"

# The .NET runtime's stack overflow trace (tag DOTNET) is long and would push the START line out of the 256 KB default buffer
adb logcat -G 16M

# macOS has no GNU timeout; without it the commands run unbounded
if ! command -v timeout > /dev/null 2>&1; then
    if command -v gtimeout > /dev/null 2>&1; then
        timeout() { gtimeout "$@"; }
    else
        timeout() { shift; "$@"; }
    fi
fi

apk=$(ls src/Repro/bin/Release/*/android-x64/*-Signed.apk | head -1)
timeout 300 adb install -r "$apk" > "artifacts/$runtime/install.txt" 2>&1 || { sleep 10; timeout 300 adb install -r "$apk" > "artifacts/$runtime/install.txt" 2>&1; } \
    || { echo "Install failed"; cat "artifacts/$runtime/install.txt"; exit 1; }

wait_for_end() {
    local waited=0
    while [ "$waited" -lt 120 ]; do
        adb logcat -d -s ListenerRepro:I | grep -q ' DONE ' && return 0
        if [ "$waited" -gt 10 ] && [ -z "$(adb shell pidof "$package" | tr -d '\r')" ]; then
            echo "Process gone without DONE: it crashed."
            return 1
        fi
        sleep 2
        waited=$((waited + 2))
    done
    echo "Timed out."
    return 1
}

for case_name in runnable-plain accessibility-plain runnable-alive accessibility-alive runnable-ctor accessibility-ctor; do
    folder="$artifacts/$case_name"
    mkdir -p "$folder"

    adb logcat -c
    adb logcat -b crash -c
    timeout 60 adb shell am start -W -n "$package/com.example.disposedlistener.MainActivity" --es case "$case_name" > "$folder/am-start.txt" 2>&1

    wait_for_end > "$folder/wait.txt" 2>&1
    echo "$case_name: $(cat "$folder/wait.txt")"

    adb logcat -d > "$folder/logcat.txt"
    adb logcat -d -s ListenerRepro:I > "$folder/repro.txt"
    adb logcat -d -b crash > "$folder/crash.txt"
    adb shell am force-stop "$package"
done

echo "emulator API level $(adb shell getprop ro.build.version.sdk | tr -d '\r')" >> "artifacts/$runtime/versions.txt"
