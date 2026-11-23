namespace Repro;

static class Log
{
    public const string Tag = "ListenerRepro";

    // The -alive cases reuse the -plain listener classes, so the listener cannot hard-code its case name
    public static string CurrentCase { get; set; } = "unknown";

    public static void Line(string marker, string caseName, params (string Name, string Value)[] fields)
    {
        var text = $"{marker} case={caseName}";
        foreach (var (name, value) in fields)
        {
            var clean = value.Replace('"', '\'').ReplaceLineEndings(" ");
            text += clean.Contains(' ') ? $" {name}=\"{clean}\"" : $" {name}={clean}";
        }

        Android.Util.Log.Info(Tag, text);
    }
}
