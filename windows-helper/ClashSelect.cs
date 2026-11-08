using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Linq;
using System.Net;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Web.Script.Serialization;
using System.Windows;
using System.Windows.Automation;

class SelectOfficial {
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr window);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")] static extern bool ShowWindow(IntPtr window, int state);
    static Process process;
    static string group;
    static string node;
    static readonly Stopwatch elapsed = new Stopwatch();
    static readonly List<object> steps = new List<object>();
    static void RequestVisible(Dictionary<string, object> record) {
        var port = Convert.ToInt32(record["port"]);
        if (port < 1 || port > 65535) throw new Exception("Invalid local instance port");
        var request = (HttpWebRequest)WebRequest.Create("http://127.0.0.1:" + port + "/commands/visible");
        request.Proxy = null;
        request.Timeout = 3000;
        request.AllowAutoRedirect = false;
        request.Headers.Add("x-instance-token", (string)record["token"]);
        using (var response = (HttpWebResponse)request.GetResponse()) {
            if (response.StatusCode != HttpStatusCode.OK) throw new Exception("Clash window was not ready");
        }
    }
    static void Reveal(string sourceRoot) {
        var record = new JavaScriptSerializer().Deserialize<Dictionary<string, object>>(
            File.ReadAllText(Path.Combine(sourceRoot, "singleton-instance.json"), Encoding.UTF8));
        RequestVisible(record);
        var lastShow = Stopwatch.StartNew();
        int attempts = 1;
        Wait(() => {
            process.Refresh();
            var window = process.MainWindowHandle;
            if (window != IntPtr.Zero && IsWindowVisible(window) && !IsIconic(window)) return Root();
            // Official window activation has a 625 ms debounce. Retrying display is idempotent;
            // selecting a line below is still invoked exactly once.
            if (attempts < 3 && lastShow.ElapsedMilliseconds >= 750) {
                RequestVisible(record);
                attempts++;
                lastShow.Restart();
            }
            return null;
        }, "Clash window");
    }
    static AutomationElement Root() {
        process.Refresh();
        if (process.HasExited || process.MainWindowHandle == IntPtr.Zero)
            throw new Exception("Clash window is unavailable");
        return AutomationElement.FromHandle(process.MainWindowHandle);
    }
    static string Parents(AutomationElement el) {
        var values = new List<string>();
        for (int i=0; i<4; i++) {
            el = TreeWalker.ControlViewWalker.GetParent(el);
            if (el == null) break;
            values.Add(el.Current.ControlType.ProgrammaticName + ":" + el.Current.Name);
        }
        return String.Join(" > ", values);
    }
    static List<AutomationElement> Buttons(AutomationElement root) {
        return root.FindAll(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Button))
            .Cast<AutomationElement>().ToList();
    }
    static bool Visible(AutomationElement el) {
        return !el.Current.IsOffscreen && el.Current.IsEnabled && !el.Current.BoundingRectangle.IsEmpty;
    }
    static bool IsSidebar(AutomationElement el) {
        var parent = TreeWalker.ControlViewWalker.GetParent(el);
        return parent != null && parent.Current.ControlType == ControlType.ListItem;
    }
    static bool IsHeader(AutomationElement el, string name) {
        var text = el.Current.Name;
        return (text.StartsWith(name + " Selector ", StringComparison.Ordinal)
            || text.StartsWith(name + " " + name + " Selector ", StringComparison.Ordinal))
            && Buttons(el).Any(b => b.Current.Name == "过滤节点" || b.Current.Name == "Filter nodes");
    }
    static AutomationElement Unique(IEnumerable<AutomationElement> elements, string label) {
        var list = elements.ToList();
        if (list.Count > 1) throw new Exception("Ambiguous control: " + label);
        return list.Count == 1 ? list[0] : null;
    }
    static AutomationElement Wait(Func<AutomationElement> read, string label, int timeout = 8000) {
        var start = Stopwatch.StartNew();
        while (start.ElapsedMilliseconds < timeout) {
            try {
                AutomationElement result = read();
                if (result != null) return result;
            } catch (ElementNotAvailableException) {
                // Filtering replaces virtual-list controls while the tree is being read.
            }
            Thread.Sleep(75);
        }
        throw new TimeoutException("Timed out waiting for " + label);
    }
    static void Invoke(AutomationElement el, string label) {
        object pattern;
        if (!el.TryGetCurrentPattern(InvokePattern.Pattern, out pattern))
            throw new Exception("Control cannot be invoked: " + label);
        ((InvokePattern)pattern).Invoke();
        steps.Add(new {step=label, ms=elapsed.Elapsed.TotalMilliseconds});
    }
    static AutomationElement Header() {
        try {
            return Unique(Buttons(Root()).Where(b => IsHeader(b, group)), "group " + group);
        } catch (ElementNotAvailableException) {
            return null;
        }
    }
    static AutomationElement FilterInput() {
        var header = Header();
        if (header == null) return null;
        return Unique(header.FindAll(TreeScope.Descendants,
            new PropertyCondition(AutomationElement.ControlTypeProperty, ControlType.Edit))
            .Cast<AutomationElement>().Where(Visible), "filter input");
    }
    static void SetFilter(string value) {
        var input = Wait(FilterInput, "filter input");
        object pattern;
        if (!input.TryGetCurrentPattern(ValuePattern.Pattern, out pattern))
            throw new Exception("Filter has no value pattern");
        ((ValuePattern)pattern).SetValue(value);
        steps.Add(new {step="filter", ms=elapsed.Elapsed.TotalMilliseconds});
    }
    static AutomationElement Candidate() {
        var header = Header();
        if (header == null || !Visible(header)) return null;
        var rect = header.Current.BoundingRectangle;
        var all = Buttons(Root());
        var nextTop = all.Where(b => Visible(b) && b.Current.BoundingRectangle.Top >= rect.Bottom
            && b.Current.Name.Contains(" Selector ") && Buttons(b).Any(c => c.Current.Name == "过滤节点" || c.Current.Name == "Filter nodes"))
            .Select(b => b.Current.BoundingRectangle.Top).DefaultIfEmpty(double.MaxValue).Min();
        return Unique(all.Where(b => Visible(b)
            && b.Current.BoundingRectangle.Top >= rect.Bottom - 1
            && b.Current.BoundingRectangle.Top < nextTop
            && (b.Current.Name == node || b.Current.Name.StartsWith(node + " ", StringComparison.Ordinal))
            && Buttons(b).Count == 0), "target line in requested group");
    }
    static void Select() {
        var header = Header();
        if (header == null) {
            var tab = Wait(() => Unique(Buttons(Root()).Where(b => IsSidebar(b) &&
                (String.Concat(b.Current.Name.Where(c => !Char.IsWhiteSpace(c))) == "代理"
                    || b.Current.Name == "Proxies")), "Proxies navigation"), "Proxies navigation");
            Invoke(tab, "open_proxies");
        }
        header = Header();
        if (header == null || !Visible(header)) {
            var jump = Wait(() => Unique(Buttons(Root()).Where(b => b.Current.Name == group && Visible(b)),
                "group navigator"), "group navigator");
            Invoke(jump, "locate_group");
        }
        header = Wait(() => {var h=Header(); return h != null && Visible(h) ? h : null;}, "group header");
        if (FilterInput() != null) {
            var close = Unique(Buttons(header).Where(b => b.Current.Name == "过滤节点" || b.Current.Name == "Filter nodes"), "filter button");
            Invoke(close, "close_existing_filter");
            header = Wait(() => FilterInput() == null ? Header() : null, "filter closed");
        }
        var filter = Unique(Buttons(header).Where(b => b.Current.Name == "过滤节点" || b.Current.Name == "Filter nodes"), "filter button");
        if (filter == null) throw new Exception("Group filter unavailable");
        // Opening the official filter also expands a collapsed group.
        Invoke(filter, "open_filter");
        SetFilter(node);
        var target = Wait(Candidate, "exact line under requested group");
        // Re-read the candidate after filtering settles; never reuse an earlier tree index.
        Thread.Sleep(100);
        target = Wait(Candidate, "stable target after filtering");
        Invoke(target, "select_line");
    }
    [STAThread]
    static int Main(string[] args) {
        Console.OutputEncoding = new UTF8Encoding(false);
        elapsed.Start();
        var json = new JavaScriptSerializer();
        IntPtr foreground = IntPtr.Zero;
        bool restore = false, wasHidden = false, wasMinimized = false;
        try {
            var request = json.Deserialize<Dictionary<string, object>>(File.ReadAllText(args[0], Encoding.UTF8));
#if LAB
            process = Process.GetProcessById(Convert.ToInt32(request["pid"]));
            var expected = Path.GetFullPath((string)request["executable"]);
            // The validation helper cannot target the installed user's application.
            if (!expected.EndsWith(@"\clash-verge-source\target\debug\clash-verge.exe", StringComparison.OrdinalIgnoreCase)
                || !String.Equals(process.MainModule.FileName, expected, StringComparison.OrdinalIgnoreCase))
                throw new Exception("Refusing a process outside the isolated build");
#else
            var expectedRoot = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ApplicationData),
                "io.github.clash-verge-rev.clash-verge-rev");
            if (!String.Equals(Path.GetFullPath((string)request["source_root"]), expectedRoot, StringComparison.OrdinalIgnoreCase))
                throw new Exception("This client is not supported for durable selection");
            var candidates = new List<Process>();
            foreach (var item in Process.GetProcessesByName("clash-verge")) {
                try {
                    var version = item.MainModule.FileVersionInfo;
                    // Version numbers are not a compatibility contract. The UI capabilities and
                    // saved selection are checked on every explicit switch instead.
                    if (version.ProductName == "Clash Verge") candidates.Add(item);
                } catch (System.ComponentModel.Win32Exception) { }
            }
            if (candidates.Count != 1) throw new Exception("A single Clash Verge instance is required");
            process = candidates[0];
#endif
            group = (string)request["group"];
            node = (string)request["node"];
            var mode = (string)request["mode"];
#if !LAB
            if (mode != "select") throw new Exception("Unsupported operation");
#endif
            if (mode == "select" && request.ContainsKey("source_root")) {
                foreground = GetForegroundWindow();
                process.Refresh();
                var original = process.MainWindowHandle;
                wasHidden = original == IntPtr.Zero || !IsWindowVisible(original);
                wasMinimized = original != IntPtr.Zero && IsIconic(original);
                restore = true;
                Reveal((string)request["source_root"]);
            }
            if (mode == "dump") {
                var data = Buttons(Root()).Select(b => new {name=b.Current.Name,
                    offscreen=b.Current.IsOffscreen, rect=b.Current.BoundingRectangle.ToString(), parents=Parents(b),
                    invoke=(bool)b.GetCurrentPropertyValue(AutomationElement.IsInvokePatternAvailableProperty)}).ToList();
                Console.WriteLine(json.Serialize(new {ok=true, controls=data}));
                return 0;
            }
            if (mode == "minimize") {
                ((WindowPattern)Root().GetCurrentPattern(WindowPattern.Pattern)).SetWindowVisualState(WindowVisualState.Minimized);
            } else if (mode == "hide") {
                ShowWindow(process.MainWindowHandle, 0);
            } else if (mode == "collapse") {
                Invoke(Wait(Header, "group header"), "toggle_group");
            } else if (mode == "home") {
                var tab = Unique(Buttons(Root()).Where(b => String.Concat(b.Current.Name.Where(c => !Char.IsWhiteSpace(c))) == "首页"), "home");
                Invoke(tab, "home");
            } else if (mode == "select") {
                Select();
            } else throw new Exception("Unknown operation");
            Console.WriteLine(json.Serialize(new {ok=true, mode=mode, ms=elapsed.Elapsed.TotalMilliseconds, steps=steps}));
            return 0;
        } catch(Exception error) {
            Console.WriteLine(json.Serialize(new {ok=false, error=error.Message, type=error.GetType().FullName, trace=error.StackTrace, ms=elapsed.Elapsed.TotalMilliseconds, steps=steps}));
            return 1;
        } finally {
            if (restore && process != null && !process.HasExited) {
                process.Refresh();
                var window = process.MainWindowHandle;
                if (window != IntPtr.Zero) {
                    if (wasHidden) ShowWindow(window, 0);
                    else if (wasMinimized) ShowWindow(window, 6);
                }
                if (foreground != IntPtr.Zero && foreground != window) SetForegroundWindow(foreground);
            }
        }
    }
}
