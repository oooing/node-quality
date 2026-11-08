#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::{io::{BufRead, BufReader}, os::windows::{io::AsRawHandle, process::CommandExt}, process::{Child, Command, Stdio}, sync::Mutex};
use tauri::{Manager, WebviewUrl, WebviewWindowBuilder};
use windows_sys::Win32::{Foundation::{CloseHandle, HANDLE}, System::JobObjects::{AssignProcessToJobObject, CreateJobObjectW, JobObjectExtendedLimitInformation, SetInformationJobObject, JOBOBJECT_EXTENDED_LIMIT_INFORMATION, JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE}, UI::WindowsAndMessaging::{MessageBoxW, MB_ICONERROR, MB_OK}};

// Closing or crashing the desktop also closes its backend and any running test core.
struct OwnedProcesses { child: Mutex<Child>, job: HANDLE }
unsafe impl Send for OwnedProcesses {}
unsafe impl Sync for OwnedProcesses {}
impl Drop for OwnedProcesses {
    fn drop(&mut self) {
        unsafe { CloseHandle(self.job); }
        if let Ok(child) = self.child.get_mut() { let _ = child.wait(); }
    }
}

fn make_job(child: &Child) -> std::io::Result<HANDLE> {
    unsafe {
        let job = CreateJobObjectW(std::ptr::null(), std::ptr::null());
        if job.is_null() { return Err(std::io::Error::last_os_error()); }
        let mut info: JOBOBJECT_EXTENDED_LIMIT_INFORMATION = std::mem::zeroed();
        info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
        if SetInformationJobObject(job, JobObjectExtendedLimitInformation, &info as *const _ as _, std::mem::size_of_val(&info) as u32) == 0
            || AssignProcessToJobObject(job, child.as_raw_handle() as HANDLE) == 0 {
            let error = std::io::Error::last_os_error(); CloseHandle(job); return Err(error);
        }
        Ok(job)
    }
}

fn main() {
    let result = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _, _| {
            if let Some(window) = app.get_webview_window("main") { let _ = window.show(); let _ = window.unminimize(); let _ = window.set_focus(); }
        }))
        .setup(|app| {
            let resources = app.path().resource_dir()?;
            let data = std::env::var_os("NODEQUALITY_DATA_DIR").map(std::path::PathBuf::from)
                .unwrap_or_else(|| std::path::PathBuf::from(std::env::var_os("LOCALAPPDATA").unwrap()).join("NodeQuality"));
            std::fs::create_dir_all(&data)?;
            let error_log = std::fs::OpenOptions::new().create(true).append(true).open(data.join("startup.log"))?;
            let mut command = Command::new(resources.join("backend/node-quality-service.exe"));
            command.args(["--data-dir"]).arg(&data).arg("--core").arg(resources.join("engine/mihomo.exe"))
                .arg("--ui").arg(resources.join("ui")).stdin(Stdio::piped()).stdout(Stdio::piped()).stderr(error_log).creation_flags(0x08000000);
            if std::env::var("NODEQUALITY_PAUSED").as_deref() == Ok("1") { command.arg("--paused"); }
            let mut child = command.spawn()?;
            let job = match make_job(&child) { Ok(job) => job, Err(error) => { let _ = child.kill(); return Err(error.into()); } };
            let output = child.stdout.take().unwrap();
            let owned = OwnedProcesses { child: Mutex::new(child), job };
            let mut line = String::new();
            BufReader::new(output).read_line(&mut line)?;
            let ready: serde_json::Value = serde_json::from_str(&line).map_err(|_| std::io::Error::other("检测服务启动失败，请查看 NodeQuality/startup.log"))?;
            let url = ready["url"].as_str().ok_or_else(|| std::io::Error::other("检测服务未就绪"))?.parse()?;
            app.manage(owned);
            WebviewWindowBuilder::new(app, "main", WebviewUrl::External(url)).title("云鉴")
                .inner_size(1180.0, 800.0).min_inner_size(780.0, 520.0).build()?;
            Ok(())
        })
        .run(tauri::generate_context!());
    if let Err(error) = result {
        let message: Vec<u16> = format!("云鉴启动失败：{error}\0").encode_utf16().collect();
        let title: Vec<u16> = "云鉴\0".encode_utf16().collect();
        unsafe { MessageBoxW(std::ptr::null_mut(), message.as_ptr(), title.as_ptr(), MB_OK | MB_ICONERROR); }
    }
}
