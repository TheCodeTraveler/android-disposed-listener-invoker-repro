using Android.Runtime;
using Android.Views.Accessibility;

namespace Repro;

// Without a leaf (IntPtr, JniHandleOwnership) constructor, the runtime cannot recreate this type from a Java object
sealed class RunnableListenerWithoutActivationConstructor : Java.Lang.Object, Java.Lang.IRunnable
{
    public void Run() => Log.Line("CALLBACK", "runnable-plain");
}

sealed class RunnableListenerWithActivationConstructor : Java.Lang.Object, Java.Lang.IRunnable
{
    public RunnableListenerWithActivationConstructor()
    {
    }

    public RunnableListenerWithActivationConstructor(IntPtr handle, JniHandleOwnership transfer) : base(handle, transfer)
    {
    }

    public void Run() => Log.Line("CALLBACK", "runnable-ctor");
}

sealed class AccessibilityListenerWithoutActivationConstructor : Java.Lang.Object, AccessibilityManager.IAccessibilityStateChangeListener
{
    public void OnAccessibilityStateChanged(bool enabled) => Log.Line("CALLBACK", "accessibility-plain", ("enabled", enabled.ToString()));
}

sealed class AccessibilityListenerWithActivationConstructor : Java.Lang.Object, AccessibilityManager.IAccessibilityStateChangeListener
{
    public AccessibilityListenerWithActivationConstructor()
    {
    }

    public AccessibilityListenerWithActivationConstructor(IntPtr handle, JniHandleOwnership transfer) : base(handle, transfer)
    {
    }

    public void OnAccessibilityStateChanged(bool enabled) => Log.Line("CALLBACK", "accessibility-ctor", ("enabled", enabled.ToString()));
}
