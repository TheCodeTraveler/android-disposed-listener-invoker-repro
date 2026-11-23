#!/usr/bin/env bash
set -uo pipefail

runtime="${1:?usage: build.sh <coreclr|mono>}"
artifacts="artifacts/$runtime"
mkdir -p "$artifacts"

extra_arguments=()
if [ -n "${ANDROID_HOME:-}" ]; then
    extra_arguments+=("-p:AndroidSdkDirectory=$ANDROID_HOME")
fi

# A stale obj folder from the other runtime would be reused by an incremental build
rm -rf src/Repro/obj src/Repro/bin

dotnet build src/Repro -c Release -p:ReproRuntime="$runtime" -p:RuntimeIdentifier=android-x64 ${extra_arguments[@]+"${extra_arguments[@]}"} \
    -bl:"$artifacts/build.binlog" | tee "$artifacts/build.txt"
if [ "${PIPESTATUS[0]}" -ne 0 ]; then
    echo "::error::Build for $runtime failed."
    exit 1
fi

apk=$(ls src/Repro/bin/Release/*/android-x64/*-Signed.apk | head -1)
listing=$(unzip -l "$apk")
# An APK with the wrong runtime would make a leg pass or fail for the wrong reason
case "$runtime" in
    coreclr)
        grep -q "libcoreclr.so" <<< "$listing" || { echo "::error::APK has no CoreCLR."; exit 1; }
        grep -q "libmonosgen-2.0.so" <<< "$listing" && { echo "::error::APK contains Mono."; exit 1; }
        ;;
    mono)
        grep -q "libmonosgen-2.0.so" <<< "$listing" || { echo "::error::APK has no Mono."; exit 1; }
        grep -q "libcoreclr.so" <<< "$listing" && { echo "::error::APK contains CoreCLR."; exit 1; }
        ;;
esac
echo "APK check passed: $apk"
