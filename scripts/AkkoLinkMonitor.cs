using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("AKKO Link Monitor")]
[assembly: AssemblyProduct("AKKO Link Monitor")]
[assembly: AssemblyDescription("AKKO keyboard battery and link monitor")]
[assembly: AssemblyCompany("Jazzwind")]
[assembly: AssemblyVersion("0.7.0.0")]
[assembly: AssemblyFileVersion("0.7.0.0")]

internal static class Program {
    [STAThread]
    private static int Main(string[] args) {
        try {
            string root = Directory.GetParent(Path.GetDirectoryName(Assembly.GetExecutingAssembly().Location)).FullName;
            string script = Path.Combine(root, "scripts", "start-monitor.ps1");
            if (!File.Exists(script)) throw new FileNotFoundException("Keep the launcher inside the project's bin folder.", script);
            bool startup = Array.IndexOf(args, "--startup") >= 0;
            ProcessStartInfo info = new ProcessStartInfo("powershell.exe",
                "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\"" +
                (startup ? " -Startup" : ""));
            info.UseShellExecute = false; info.CreateNoWindow = true;
            info.WindowStyle = ProcessWindowStyle.Hidden; info.WorkingDirectory = root;
            using (Process process = Process.Start(info)) { process.WaitForExit(); return process.ExitCode; }
        } catch (Exception error) {
            MessageBox.Show(error.Message, "AKKO Link Monitor", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
