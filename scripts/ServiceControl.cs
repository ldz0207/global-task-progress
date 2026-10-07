using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading.Tasks;
using System.Web.Script.Serialization;
using System.Windows.Forms;

public class ProgressControl : Form {
    readonly Dictionary<string,string> options = new Dictionary<string,string>();
    readonly Label status = new Label(), endpoint = new Label(), detail = new Label();
    readonly Button start = new Button(), stop = new Button(), open = new Button(), refresh = new Button();
    readonly Timer timer = new Timer();
    bool busy, checking;
    string url;

    [STAThread]
    public static void Main(string[] args) {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        try { Application.Run(new ProgressControl(args)); }
        catch(Exception error) { MessageBox.Show(error.Message,"任务进度服务",MessageBoxButtons.OK,MessageBoxIcon.Error); }
    }

    public ProgressControl(string[] args) {
        for(int i=0;i<args.Length;i+=2) {
            if(i+1>=args.Length || !args[i].StartsWith("--")) throw new ArgumentException("桌面入口参数不完整，请重新安装快捷方式。");
            options.Add(args[i],args[i+1]);
        }
        foreach(string key in new[]{"--controller","--state-dir","--backend-script","--python"})
            if(!options.ContainsKey(key) || !Path.IsPathRooted(options[key])) throw new ArgumentException("桌面入口缺少绝对路径："+key);
        Text="任务进度服务";
        ClientSize=new Size(650,335);
        FormBorderStyle=FormBorderStyle.FixedDialog;
        MaximizeBox=false;
        StartPosition=FormStartPosition.CenterScreen;
        AutoScaleMode=AutoScaleMode.Dpi;
        Font=new Font("Microsoft YaHei UI",10);
        BackColor=Color.FromArgb(245,248,246);
        Icon=SystemIcons.Application;
        Label heading=new Label {Text="统一任务进度服务",Location=new Point(24,20),Size=new Size(600,40),Font=new Font(Font.FontFamily,19,FontStyle.Bold)};
        Controls.Add(heading);
        status.Location=new Point(24,77);status.Size=new Size(600,31);status.Font=new Font(Font.FontFamily,14,FontStyle.Bold);status.Text="正在核对服务状态…";
        endpoint.Location=new Point(24,113);endpoint.Size=new Size(600,25);
        detail.Location=new Point(24,144);detail.Size=new Size(600,43);detail.ForeColor=Color.FromArgb(85,100,91);
        Controls.AddRange(new Control[]{status,endpoint,detail});
        Button[] buttons={start,stop,open,refresh};string[] names={"启动服务","停止服务","打开看板","刷新状态"};
        for(int i=0;i<buttons.Length;i++) {
            buttons[i].Text=names[i];buttons[i].Location=new Point(24+i*154,199);buttons[i].Size=new Size(140,42);
            buttons[i].Enabled=false;Controls.Add(buttons[i]);
        }
        Label note=new Label {Text="关闭此窗口不会停止服务；停止看板后，后台任务仍继续。\n新任务接入时可能按需重新启动服务。",Location=new Point(24,263),Size=new Size(603,50),ForeColor=Color.FromArgb(85,100,91)};
        Controls.Add(note);
        start.Click+=async(sender,e)=>await RunAction("start");
        stop.Click+=async(sender,e)=>await RunAction("stop");
        refresh.Click+=async(sender,e)=>await RefreshStatus();
        open.Click+=(sender,e)=> { try { Process.Start(new ProcessStartInfo(url){UseShellExecute=true}); } catch(Exception error){ShowError(error.Message);} };
        Shown+=async(sender,e)=>await RefreshStatus();
        timer.Interval=5000;timer.Tick+=async(sender,e)=>await RefreshStatus();timer.Start();
        FormClosed+=(sender,e)=>timer.Dispose();
    }

    static Dictionary<string,object> ReadJson(string text) {return new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(text);}
    static Dictionary<string,object> ReadFile(string path) {return File.Exists(path)?ReadJson(File.ReadAllText(path,Encoding.UTF8)):null;}
    static object Value(Dictionary<string,object> record,string key) {object value;return record!=null&&record.TryGetValue(key,out value)?value:null;}
    static bool SamePath(object a,string b) {try{return String.Equals(Path.GetFullPath(Convert.ToString(a)).TrimEnd('\\','/'),Path.GetFullPath(b).TrimEnd('\\','/'),StringComparison.OrdinalIgnoreCase);}catch{return false;}}
    static int Port(object value) {
        string text=Convert.ToString(value,CultureInfo.InvariantCulture);int number;
        if(!Regex.IsMatch(text??"","^\\d+$") || !Int32.TryParse(text,out number) || number<1 || number>65535)throw new ArgumentException("端口必须是1至65535的整数。");return number;
    }
    int CurrentPort() {
        if(options.ContainsKey("--port")) return Port(options["--port"]);
        string environment=Environment.GetEnvironmentVariable("TASK_PROGRESS_PORT");if(!String.IsNullOrEmpty(environment))return Port(environment);
        foreach(string name in new[]{"服务配置.json","服务状态.json"}) {
            var record=ReadFile(Path.Combine(options["--state-dir"],name));if(record==null)continue;
            if(Convert.ToString(Value(record,"identity"))!="agent-global-progress-v1")throw new ArgumentException("服务配置身份不匹配："+name);
            return Port(Value(record,"port"));
        }
        return 8790;
    }
    static Dictionary<string,object> Health(int port) {
        var request=(HttpWebRequest)WebRequest.Create("http://127.0.0.1:"+port+"/api/health");request.Proxy=null;request.Timeout=1000;request.ReadWriteTimeout=1000;
        try {using(var response=request.GetResponse())using(var reader=new StreamReader(response.GetResponseStream(),Encoding.UTF8))return ReadJson(reader.ReadToEnd());}catch{return null;}
    }
    bool Owned(Dictionary<string,object> health,int port) {return health!=null&&Convert.ToString(Value(health,"identity"))=="agent-global-progress-v1"&&Convert.ToString(Value(health,"port"))==port.ToString()&&SamePath(Value(health,"state_dir"),options["--state-dir"]);}
    static bool Listening(int port) {using(var client=new TcpClient())try{var pending=client.BeginConnect("127.0.0.1",port,null,null);if(!pending.AsyncWaitHandle.WaitOne(250))return false;client.EndConnect(pending);return true;}catch{return false;}}
    Dictionary<string,object> FetchStatus() {
        int port=CurrentPort();var metadata=ReadFile(Path.Combine(options["--state-dir"],"服务状态.json"));
        if(metadata!=null&&Convert.ToString(Value(metadata,"identity"))=="agent-global-progress-v1"&&Port(Value(metadata,"port"))!=port) {
            int oldPort=Port(Value(metadata,"port"));if(Owned(Health(oldPort),oldPort))return new Dictionary<string,object>{{"status","port_mismatch"},{"url","http://127.0.0.1:"+oldPort+"/"},{"message","原服务仍在另一端口运行，请先沿用原端口再进行控制。"}};
        }
        var health=Health(port);string state="stopped",message="服务已停止";
        if(Owned(health,port)) {
            bool verified=metadata!=null&&Convert.ToString(Value(metadata,"identity"))=="agent-global-progress-v1"&&Convert.ToString(Value(metadata,"pid"))==Convert.ToString(Value(health,"pid"))&&Convert.ToString(Value(metadata,"port"))==port.ToString()&&SamePath(Value(metadata,"script"),options["--backend-script"]);
            state=verified?"running":"unverified";message=verified?"当前服务 PID："+Value(health,"pid"):"看板在线，但启动记录或服务脚本不匹配，不能通过此入口停止。";
        } else if(health!=null||Listening(port)) {state="conflict";message="端口被其他程序占用，或服务尚未通过身份核对。";}
        return new Dictionary<string,object>{{"status",state},{"message",message},{"url","http://127.0.0.1:"+port+"/"}};
    }
    void SetButtons(bool canStart,bool canStop,bool canOpen) {start.Enabled=canStart&&!busy;stop.Enabled=canStop&&!busy;open.Enabled=canOpen&&!busy;refresh.Enabled=!busy;}
    void Apply(Dictionary<string,object> record) {
        string state=Convert.ToString(Value(record,"status"));url=Convert.ToString(Value(record,"url"));endpoint.Text="看板入口："+url;detail.Text=Convert.ToString(Value(record,"message"));
        status.Text=state=="running"?"● 服务运行中":state=="stopped"?"○ 服务已停止":"! 需要核对";
        status.ForeColor=state=="running"?Color.FromArgb(25,106,76):state=="stopped"?Color.FromArgb(100,110,105):Color.FromArgb(157,53,42);
        SetButtons(state=="stopped",state=="running",state=="running"||state=="unverified"||state=="port_mismatch");
    }
    void ShowError(string message) {status.Text="! 操作未完成";status.ForeColor=Color.FromArgb(157,53,42);detail.Text=message;SetButtons(false,false,false);}
    async Task RefreshStatus() {
        if(busy||checking||IsDisposed)return;checking=true;
        try {var record=await Task.Run(()=>FetchStatus());if(!IsDisposed&&!busy)Apply(record);}catch(Exception error){if(!IsDisposed&&!busy)ShowError(error.Message);}finally{checking=false;}
    }
    public static string Quote(string value) {return "\""+Regex.Replace(Regex.Replace(value,@"(\\*)""","$1$1\\\""),@"(\\+)$","$1$1")+"\"";}
    Dictionary<string,object> InvokeControl(string action) {
        var arguments=new List<string>{"-NoProfile","-NonInteractive","-ExecutionPolicy","Bypass","-File",options["--controller"],"-Action",action,"-StateDir",options["--state-dir"],"-BackendScript",options["--backend-script"],"-PythonPath",options["--python"]};
        if(options.ContainsKey("--port")){arguments.Add("-Port");arguments.Add(options["--port"]);}
        var quoted=arguments.ConvertAll(Quote);
        var info=new ProcessStartInfo(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System),"WindowsPowerShell\\v1.0\\powershell.exe"),String.Join(" ",quoted.ToArray())){UseShellExecute=false,CreateNoWindow=true,RedirectStandardOutput=true,RedirectStandardError=true,StandardOutputEncoding=Encoding.UTF8,StandardErrorEncoding=Encoding.UTF8};
        using(var process=Process.Start(info)) {
            // Read both pipes concurrently; the controller itself has bounded network/process waits.
            Task<string> output=process.StandardOutput.ReadToEndAsync(),errors=process.StandardError.ReadToEndAsync();
            if(!process.WaitForExit(30000))throw new Exception("控制命令超时，请刷新状态核对结果。");
            Task.WaitAll(output,errors);var record=ReadJson(output.Result.Trim());
            if(process.ExitCode!=0)throw new Exception(Convert.ToString(Value(record,"message")));
            return record;
        }
    }
    async Task RunAction(string action) {
        if(busy)return;busy=true;SetButtons(false,false,false);status.Text=action=="start"?"正在启动服务…":"正在停止服务…";
        try {var record=await Task.Run(()=>InvokeControl(action));if(!IsDisposed){busy=false;Apply(record);}}
        catch(Exception error){if(!IsDisposed){busy=false;ShowError(error.Message);}}
        finally{busy=false;}
    }
}
