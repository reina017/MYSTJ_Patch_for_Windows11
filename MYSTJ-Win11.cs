using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
using System.Windows.Forms;

internal static class MystJWin11 {
    static string Quote(string value) { return "\"" + value + "\""; }
    [STAThread]
    static void Main() {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        try {
            string runtime = Path.Combine(root, "runtime", "scummvm.exe");
            string user = Path.Combine(root, "userdata");
            if (!File.Exists(runtime) || !File.Exists(Path.Combine(root, "data", "MYST.DAT")))
                throw new FileNotFoundException("MYSTJの導入先に必要なファイルがありません。Install.cmdで再導入してください。");
            Directory.CreateDirectory(Path.Combine(user, "saves"));
            Directory.CreateDirectory(Path.Combine(user, "screenshots"));
            using (var mutex = new Mutex(false, "Local\\MYSTJWin11Launcher")) {
                if (!mutex.WaitOne(0)) return;
                try {
                    string args = "--config=" + Quote(Path.Combine(user, "scummvm.ini"))
                        + " --logfile=" + Quote(Path.Combine(user, "scummvm.log"))
                        + " --savepath=" + Quote(Path.Combine(user, "saves"))
                        + " --screenshotpath=" + Quote(Path.Combine(user, "screenshots"))
                        + " --path=" + Quote(Path.Combine(root, "data")) + " mystj";
                    var start = new ProcessStartInfo(runtime, args);
                    start.WorkingDirectory = user;
                    start.UseShellExecute = false;
                    start.CreateNoWindow = true;
                    using (var process = Process.Start(start)) process.WaitForExit();
                } finally { mutex.ReleaseMutex(); }
            }
        } catch (Exception error) {
            MessageBox.Show(error.Message, "MYSTJ Windows 11", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
