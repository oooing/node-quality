# 节点优选 · Node Quality

独立的 Windows 桌面应用，用来检查 Clash / Mihomo 订阅节点的**连通性、出口 IPv4 和 IP 风险**。自动读取已有订阅、更新和检测，帮助找到符合地区与风险要求的节点。

检测使用独立 Mihomo 进程，不切换 Clash 当前节点，不修改系统代理、DNS 或路由。

![节点优选界面，使用模拟数据](docs/screenshot.png)

*截图中的节点与 IP 均为测试数据。*

## 功能

- 自动发现 Clash Verge / Clash Verge Rev 的订阅，默认接入当前使用的订阅。
- 自动更新订阅，新节点和配置变化后重新检测；也支持手动检测与排队。
- 先检查连通性，再查询出口 IPv4 和 IPPure 风险，分别显示失败阶段。
- 候选节点优先显示，其他节点可以展开查看；可按地区、风险上限和记录时效筛选。
- 每个节点保留最近 10 次检查，显示 IP 变化和风险变化。
- 链接或 YAML 导入后可以独立工作，不要求 Clash 持续运行。

| 默认计划 | 间隔 |
| --- | --- |
| 订阅更新 | 6 小时 |
| 候选复检 | 6 小时 |
| 其他节点复检 | 24 小时 |

应用打开时运行，可以最小化；退出后停止，下次打开继续。检测按顺序执行，不做大流量下载测速。暂停自动检测不会取消手动队列。IPPure 限流或拒绝查询时等待 30 分钟，冷却时间跨重启保留。

## 运行与构建

当前版本为 **0.1.0 早期版本**，本仓库发布源码，不包含预编译安装包。

需要 Windows 10/11 x64、Python 3.13、Rust/MSVC 工具链、Visual Studio C++ Build Tools 与 Windows SDK，以及 WebView2。Windows 11 已实测。构建时需要访问 PyPI、crates.io 和 GitHub；检测不依赖 AI。

在 PowerShell 中执行：

```powershell
git clone https://github.com/oooing/node-quality.git
cd node-quality
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
cargo install tauri-cli --version 2.11.3 --locked
python scripts/fetch_engine.py
.\build.ps1
```

`fetch_engine.py` 下载官方 Mihomo **v1.19.32 compatible x64**，并校验固定 SHA-256；不读取或复制本机代理软件。也可自行构建相同版本，将引擎放在 `resources/engine/mihomo.exe`。

安装包输出到 `product/节点优选_0.1.0_x64-setup.exe`。安装后从桌面或开始菜单打开，无需运行命令或记住 Web 地址。已缓存 Rust 依赖时可用 `build.ps1 -Offline`；离线参数仅作用于 Cargo。

安装器默认按用户安装，并可在缺少 WebView2 时下载运行时。本项目不提供商业签名证书。

## 首次使用

1. 已安装 Clash Verge / Verge Rev：打开后自动发现标准 AppData 目录中的订阅，更新当前订阅并开始检测。
2. 在“订阅”中勾选其他订阅；未发现时可粘贴链接、导入 YAML 或指定配置目录。
3. 首页查看候选，点检测时间查看历史，点齿轮调整推荐条件与检测间隔。

风险值为 **0–100，越低越好**；不是封禁概率，也不代表带宽速度。推荐条件默认风险 ≤ 30、记录在 24 小时内。没有候选时会显示未检测、过期、风险过高等原因。

## 数据与网络边界

- 数据只存于 `%LOCALAPPDATA%\NodeQuality`：订阅副本、SQLite 历史和设置。不上传到项目服务器。
- 订阅文件包含凭据，**不要把数据目录、真实配置或日志上传到公开 Issue**。
- 应用只读取源客户端配置，不执行覆写脚本、不写回订阅，也没有切换当前节点的接口。
- 检测引擎只监听随机回环端口，关闭 TUN 和 DNS 接管，将检测连接绑定物理网卡。无法确认物理网卡时暂缓检测。
- 订阅下载可能沿用现有系统代理，但不会改变它。检测请求明确经过所选节点的独立引擎。
- 正常退出或桌面进程异常退出，都会关闭属于本应用的后台进程。

检测服务会看到被检测节点的出口 IP；查询仍消耗少量连接、CPU 和订阅流量。免费服务的可用性、频率限制及页面/API 变化由服务方决定。

## 当前范围

- 支持 Clash/Mihomo YAML 中的 `proxies`，以及 inline、可读取 file、可下载 HTTP YAML 代理集合。
- 自动发现范围是 Clash Verge Rev / 原 Clash Verge；其他客户端需手动导入。
- 不支持 Base64 通用订阅转换、链式节点，以及会创建专用隧道的部分协议。
- 只接 IPPure；暂不含 Ping0、登录自启、应用自身在线升级或自动切换节点。
- 本机真实验收使用 Windows 11、Clash TUN 关闭的环境；TUN 和第三方全局 VPN 尚未专项验收。

## 开发与测试

```powershell
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m playwright install chromium
python tests/acceptance_ui.py
```

这些测试使用临时订阅和模拟节点，不会查询你的真实节点。界面验收覆盖历史、地区筛选、持久化、排队、紧凑布局与轮询稳定性。

```text
backend/       订阅发现、计划执行、独立检测、推荐与历史
ui/            原生 HTML / CSS / JavaScript 界面
src-tauri/     Windows 窗口与后台进程生命周期
scripts/       校验并下载构建所需引擎
tests/         独立逻辑与界面测试
resources/     引擎版本信息与第三方许可证
```

## 开源许可

[GPL-3.0-only](LICENSE)。第三方组件保留各自许可，见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
