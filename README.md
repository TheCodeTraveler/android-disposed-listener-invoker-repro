# android-disposed-listener-invoker-repro

On .NET 11 Android with CoreCLR (the default), a Java callback into a `Java.Lang.Object` listener that the app already disposed builds the interface `Invoker` around the Java object. The Invoker calls the Java method again, which re-enters the same native callback, and the app dies with `Stack overflow.`. Mono throws a clear `NotSupportedException: Unable to activate instance of type ...` for the same situation.

Disposing a listener that Java still holds is an app error. The bug is that CoreCLR then dies with a stack overflow that cannot be caught, where Mono throws an exception that can. The OS can call a listener after the app disposed it: CommunityToolkit.Maui device tests hit this with `SpeechRecognizer` `onError` on API 34 and `AccessibilityManager` state listeners on API 27.

## Reproduce

Needs the .NET 11.0.100 SDK, the `android` workload set 11.0.100.1 (`dotnet workload install android --version 11.0.100.1`, Microsoft.NET.Sdk.Android 37.2.31; the Mono leg uses Android SDK 36.1.118 from the same set) and a running x86_64 emulator or device. On Apple Silicon emulators and on arm64 devices, add `-p:RuntimeIdentifier=android-arm64` (`RUNTIME_IDENTIFIER=android-arm64` for the scripts).

One command, on Linux or on macOS with coreutils (`gtimeout`):

```
bash ci/build.sh coreclr && bash ci/run-cases.sh coreclr && python3 -I ci/assert-results.py --runtime coreclr --expected ci/expected.json --results artifacts/coreclr
```

By hand (on an arm64 device use android-arm64 in both the build command and the APK path):

```
dotnet build src/Repro -c Release -p:ReproRuntime=coreclr -p:RuntimeIdentifier=android-x64
adb install -r src/Repro/bin/Release/net11.0-android/android-x64/com.example.disposedlistener-Signed.apk
adb logcat -c
adb shell am start -n com.example.disposedlistener/com.example.disposedlistener.MainActivity --es case runnable-plain
sleep 15
adb logcat -d -s ListenerRepro:I DOTNET:*
```

The `DOTNET` tag carries `Stack overflow.` and the looping frames; `-s ListenerRepro:I` alone shows only a START line.

What the app does: it creates a listener (`IRunnable`, or `AccessibilityManager.IAccessibilityStateChangeListener`), takes a JNI global reference that stands in for a Java caller that still holds the listener, disposes the managed peer, then calls the Java interface method through that reference. The `-plain` listeners have no leaf `(IntPtr, JniHandleOwnership)` constructor.

Cases:

- `runnable-plain`, `accessibility-plain`: the bug.
- `runnable-alive`, `accessibility-alive`: control. Same listener classes and the same JNI call, but no `Dispose()` before the call, so it differs from `-plain` only by the trigger.
- `runnable-ctor`, `accessibility-ctor`: app-side workaround (listener with a leaf `(IntPtr, JniHandleOwnership)` constructor).

## Observed vs expected

| Runtime | Case | Observed | Expected |
|---|---|---|---|
| CoreCLR (.NET 11) | `*-plain` | `Stack overflow.` and a `Repeated N times:` block (N about 600-700) of `I...Invoker.<Method>` -> `__n_<Method>` frames, no `RESULT` line | `NotSupportedException` naming the listener type |
| Mono (.NET 10) | `*-plain` | `NotSupportedException: Unable to activate instance of type ...` | same |
| both | `*-alive`, `*-ctor` | `RESULT ... outcome=returned` after a `CALLBACK` line | same |

## Legs and how CI proves them

[`.github/workflows/repro.yml`](.github/workflows/repro.yml) builds one APK per runtime and launches each case on API 34 and API 36 x86_64 emulators, on workload set 11.0.100.1 (overridable with the `workload-set` dispatch input). The job summary starts with a verdict line and the versions used. `ci/assert-results.py` compares the logcat with `ci/expected.json` and writes a table to the job summary.

- **coreclr bug legs** (`*-plain`): green only when the app's own process (pid from its START line) logs `E DOTNET: Stack overflow.`, at least 10 frames each of the case's Invoker method and its `__n_` method (a frame inside a `Repeated N times:` block counts N times), no `RESULT` and no `DONE` line.
- **coreclr control and workaround legs** (`*-alive`, `*-ctor`): green only when the `CALLBACK` and `RESULT outcome=returned` lines appear.
- **mono legs**: the .NET 11 SDK rejects Mono for Android (NETSDK1242), so these build `net10.0-android`. `*-plain` must report the `Unable to activate instance` exception naming the listener type, `*-alive` and `*-ctor` must return.
- Every case must print its `START` line with the expected runtime, so a case that never ran fails.

The run is green when every leg matches its expectation. The workflow does not cover `PublishAot` or the trimmable type map: by source they throw `NotSupportedException`, but that has not been run on a device.

CI: (run link added after the first run)

Upstream issue: (to be filed)

## Root cause and recommended fix

In `ReflectionJniValueManager` (`external/Java.Interop/src/Java.Interop/Java.Interop/JniRuntime.ReflectionJniValueManager.cs` L160-211, vendored in dotnet/android, identical in 37.2.31 and `release/11.0.1xx`), the walk over the Java class chain finds the managed listener type but cannot activate it, because `Type.GetConstructor` does not see the inherited activation constructor. It then falls back to the interface type, and `GetInvokerType` swaps in the Invoker. `JavaMarshalValueManager`, the CoreCLR default, has no `CreatePeer` override like Mono's `AndroidValueManager`, which goes through `TypeManager.CreateInstance` and throws.

Recommended fix: never fall back to the interface Invoker for a Java object whose class maps to a managed wrapper type. Throw `NotSupportedException` naming that type, as Mono does. `main` no longer has this value manager.

User-side workaround: do not `Dispose()` a listener that Java can still call, or add a leaf `(IntPtr, JniHandleOwnership)` constructor.
