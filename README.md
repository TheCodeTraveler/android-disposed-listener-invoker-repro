# android-disposed-listener-invoker-repro

On .NET 11 Android with CoreCLR (the default), a Java callback into a `Java.Lang.Object` listener that the app already disposed builds the interface `Invoker` around the Java object. The Invoker calls the Java method again, which re-enters the same native callback, and the app dies with `Stack overflow.`. Mono throws a clear `NotSupportedException: Unable to activate instance of type ...` for the same situation.

## Reproduce

Needs the .NET 11.0.100 SDK, the `android` workload (37.2.31) and a running x86_64 emulator or device:

```
dotnet build src/Repro -c Release -p:ReproRuntime=coreclr -p:RuntimeIdentifier=android-x64
adb install -r src/Repro/bin/Release/net11.0-android/android-x64/com.example.disposedlistener-Signed.apk
adb shell am start -n com.example.disposedlistener/com.example.disposedlistener.MainActivity --es case runnable-plain
adb logcat -d -s ListenerRepro:I
```

Cases: `runnable-plain`, `accessibility-plain` (bug), `runnable-ctor`, `accessibility-ctor` (control and fix).

## Observed vs expected

| Runtime | Case | Observed | Expected |
|---|---|---|---|
| CoreCLR (.NET 11) | `*-plain` | `Stack overflow.`, looping `I...Invoker.<Method>` and `n_<Method>` frames, no `RESULT` line | `NotSupportedException` naming the listener type |
| Mono (.NET 10) | `*-plain` | `NotSupportedException: Unable to activate instance of type ...` | same |
| both | `*-ctor` | `RESULT ... outcome=returned` after a `CALLBACK` line | same |

## What the app does

1. Creates a listener (`IRunnable`, or `AccessibilityManager.IAccessibilityStateChangeListener`).
2. Takes a JNI global reference, which stands in for a Java caller that still holds the listener, and disposes the managed peer.
3. Calls the Java interface method through that reference.

The `-plain` listeners have no leaf `(IntPtr, JniHandleOwnership)` constructor. The `-ctor` listeners have one: the control, and the user-code fix.

## Legs and how CI proves them

[`.github/workflows/repro.yml`](.github/workflows/repro.yml) builds one APK per runtime and launches each case on an API 34 x86_64 emulator. `ci/assert-results.py` compares the logcat with `ci/expected.json` and writes a table to the job summary.

- **coreclr bug legs** (`*-plain`): green only when logcat shows `Stack overflow` plus Invoker frames and there is no `RESULT` line.
- **coreclr control and fix legs** (`*-ctor`): green only when the `CALLBACK` and `RESULT outcome=returned` lines appear.
- **mono legs**: Mono was removed in .NET 11 (NETSDK1242), so these build `net10.0-android`. `*-plain` must report the `Unable to activate instance` exception, `*-ctor` must return.
- Every case must print its `START` line with the expected runtime, so a case that never ran fails.

The run is green when every leg matches its expectation. The workflow does not cover `PublishAot` or the trimmable type map: by source they throw `NotSupportedException`, but that has not been run on a device.

CI: (run link added after the first run)

Upstream issue: (to be filed)

## Root cause and recommended fix

In `ReflectionJniValueManager.CreatePeerInstance` (Java.Interop, vendored in dotnet/android, identical in 37.2.31 and `release/11.0.1xx`), the walk over the Java class chain finds the managed listener type but cannot activate it, because `Type.GetConstructor` does not see the inherited activation constructor. It then falls back to the interface type, and `GetInvokerType` swaps in the Invoker. `JavaMarshalValueManager`, the CoreCLR default, has no `CreatePeer` override like Mono's `AndroidValueManager`, which goes through `TypeManager.CreateInstance` and throws.

Recommended fix: never fall back to the interface Invoker for a Java object whose class maps to a managed wrapper type. Throw `NotSupportedException` naming that type, as Mono does. `main` no longer has this value manager.

User-side workaround: do not `Dispose()` a listener that Java can still call, or add a leaf `(IntPtr, JniHandleOwnership)` constructor.
