using Android.App;
using Android.OS;
using Android.Runtime;

namespace Repro;

[Activity(Name = "com.example.disposedlistener.MainActivity", MainLauncher = true, Exported = true)]
public class MainActivity : Activity
{
    static int caseStarted;

    protected override void OnCreate(Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);

        // A configuration change right after emulator boot relaunches the activity and would run the case twice
        if (Interlocked.Exchange(ref caseStarted, 1) == 1)
        {
            return;
        }

        var caseName = Intent?.GetStringExtra("case") ?? "runnable-plain";
        new Thread(() => RunCase(caseName)).Start();
    }

    void RunCase(string caseName)
    {
        Log.CurrentCase = caseName;
        Log.Line("START", caseName, ("runtime", DetectRuntime()), ("dotnet", Environment.Version.ToString()));

        try
        {
            CallDisposedListener(caseName);
            Log.Line("RESULT", caseName, ("outcome", "returned"));
        }
        catch (Exception exception)
        {
            var text = exception.ToString();
            Log.Line("RESULT", caseName,
                ("outcome", "exception"),
                ("type", exception.GetType().FullName ?? "unknown"),
                ("activationFailure", text.Contains("Unable to activate instance", StringComparison.Ordinal).ToString()),
                ("message", exception.Message));
            Android.Util.Log.Error(Log.Tag, text);
        }

        Log.Line("DONE", caseName);
        RunOnUiThread(FinishAndRemoveTask);
    }

    // A Java caller (for example AccessibilityManager or SpeechRecognizer) can still hold the listener after the app disposed it, so the global reference stands in for that caller
    static void CallDisposedListener(string caseName)
    {
        var (listener, methodName, signature, arguments) = CreateListener(caseName);

        // The -alive cases differ from the -plain cases only here: the managed peer is still alive when Java calls
        var disposeBeforeCall = !caseName.EndsWith("-alive", StringComparison.Ordinal);

        var javaCaller = JNIEnv.NewGlobalRef(listener.Handle);
        try
        {
            if (disposeBeforeCall)
            {
                listener.Dispose();
            }

            var javaClass = JNIEnv.GetObjectClass(javaCaller);
            try
            {
                var method = JNIEnv.GetMethodID(javaClass, methodName, signature);
                JNIEnv.CallVoidMethod(javaCaller, method, arguments);
            }
            finally
            {
                JNIEnv.DeleteLocalRef(javaClass);
            }
        }
        finally
        {
            JNIEnv.DeleteGlobalRef(javaCaller);
            listener.Dispose();
        }
    }

    static (Java.Lang.Object Listener, string MethodName, string Signature, JValue[] Arguments) CreateListener(string caseName) => caseName switch
    {
        "runnable-plain" => (new RunnableListenerWithoutActivationConstructor(), "run", "()V", []),
        "runnable-alive" => (new RunnableListenerWithoutActivationConstructor(), "run", "()V", []),
        "accessibility-alive" => (new AccessibilityListenerWithoutActivationConstructor(), "onAccessibilityStateChanged", "(Z)V", [new JValue(true)]),
        "runnable-ctor" => (new RunnableListenerWithActivationConstructor(), "run", "()V", []),
        "accessibility-plain" => (new AccessibilityListenerWithoutActivationConstructor(), "onAccessibilityStateChanged", "(Z)V", [new JValue(true)]),
        "accessibility-ctor" => (new AccessibilityListenerWithActivationConstructor(), "onAccessibilityStateChanged", "(Z)V", [new JValue(true)]),
        _ => throw new ArgumentOutOfRangeException(nameof(caseName), caseName, "Unknown case"),
    };

    // Mono.Runtime does not exist in the .NET 10 Mono CoreLib, so the loaded native runtime library is the reliable signal
    static string DetectRuntime()
    {
        var maps = File.ReadAllText("/proc/self/maps");
        if (maps.Contains("libmonosgen-2.0.so", StringComparison.Ordinal))
        {
            return "mono";
        }

        return maps.Contains("libcoreclr.so", StringComparison.Ordinal) ? "coreclr" : "unknown";
    }
}
