# Chrome Web Store Listing — 云鉴 · 网页助手

Last Updated: 2026-11-09

**状态：源码随云鉴公开，使用“加载已解压的扩展程序”安装；未提交 Chrome Web Store。**

## Store Listing

- Extension Name: 云鉴 · 网页助手
- Short Description: 将 Ping0 结果自动回填到云鉴 PC 客户端或旧 Web 面板，必要验证由用户完成。
- Detailed Description: 从节点面板打开 Ping0 补查，网页显示结果后自动保存，不用复制风险值。必要验证仍由你手动完成。保存失败可以重试；旧 IP 的结果保留在对应历史中。
- Category: Developer Tools（仅预留）
- Single Purpose: 将用户从本机节点面板发起的 Ping0 网页补查结果回填到该面板。
- Primary Language: 简体中文

## Graphics & Assets

本地版未配置图标，使用浏览器默认图标。没有商店截图或宣传素材，未达到商店发布准备状态。

## Permissions Justification

| 范围 | 类型 | 用途 |
| --- | --- | --- |
| `http://127.0.0.1/*` | host_permissions | 将补查结果发送回本机节点面板；旧 Web 使用 17786 端口，PC 使用任务标记指定的本机端口；目标固定为回环地址的 `/api/ping0/result`，不接受任意 URL。 |
| `https://ping0.cc/ip/*` | content_scripts.matches | 在用户从面板打开的带任务标记的查询页读取已显示的 IPv4、风险值与说明。 |

没有 `permissions` 项。不申请 Cookie、tabs、storage、debugger、代理、webRequest 或所有网站权限。

## Privacy & Data Use

扩展读取任务对应 Ping0 页面内容，仅将任务号、目标 IPv4、风险值、说明和去除任务标记的页面 URL 传到本机面板。无扩展后台外部请求，无数据上传到云服务，无统计。用户打开 Ping0 网页本身会正常访问 Ping0，与扩展回填是两件事。

数据由本机面板按历史策略保存，扩展自身不持久化。任务号来自面板，不读取网站登录或认证资料。

- 数据不出售给第三方。
- 数据仅用于用户发起的节点补查回填。
- 数据不用于信用或借贷判断。

## Privacy Policy / Distribution / Developer Info

通过本机加载源码安装；无商店隐私政策 URL、商店发布者、支持邮箱或分发区域设置。商店所需信息及图标、截图应在未来明确授权提交商店时另行准备。本文件不授权提交商店。

## Version History

| Version | Date | Changes | Status |
| --- | --- | --- | --- |
| 0.2.2 | 2026-11-09 | 名称统一为“云鉴 · 网页助手”，说明与当前客户端同步；权限不变。 | 源码公开，未提交商店 |
| 0.2.0 | 2026-10-29 | 支持 PC 动态本机端口，保留旧 Web 回填兼容；权限不变。 | Local only |
| 0.1.0 | 2026-10-29 | 带任务标记的 Ping0 页面自动回填；失败仅重试本地保存。 | Local only |

## Review Notes

固定程序解析与回填均有本地测试；实际浏览器验收另记录。网站结构变化时可能无法识别结果；未读到明确的目标 IP 和唯一可见风险值时不保存成功。扩展不处理验证码。

0.2.1：统一网页提示为日常用语；权限、解析和保存流程不变。
