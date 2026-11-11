# Licensing and third-party components

Yunjian (云鉴, formerly Node Quality), Copyright (C) 2026 oooing and contributors.

The application source is licensed under **GPL-3.0-only**, except where an included third-party file states otherwise. See [LICENSE](LICENSE). The program is provided without warranty.

| Component | Use | License / source |
| --- | --- | --- |
| Astryx / Neutral 0.7.11 | React UI components and theme | MIT; [frontend license inventory](resources/licenses/frontend/README.md), [source](https://github.com/meta/astryx) |
| React / React DOM 19.3.1 | UI runtime | MIT; [license](resources/licenses/frontend/react-LICENSE.txt), [source](https://github.com/facebook/react) |
| StyleX 0.19.1 | Astryx styling runtime | MIT; [license](resources/licenses/frontend/stylexjs-stylex-LICENSE.txt), [source](https://github.com/facebook/stylex) |
| Lucide React 1.18.0 | Unified UI icons | ISC; [license](resources/licenses/frontend/lucide-react-LICENSE.txt), [source](https://github.com/lucide-icons/lucide) |
| Mihomo v1.19.32 | Separate engine process; unmodified upstream binary downloaded during setup | [GPL v3](resources/licenses/Mihomo-GPL-3.0.txt), [source](https://github.com/MetaCubeX/mihomo/tree/v1.19.32), [source archive](https://github.com/MetaCubeX/mihomo/archive/refs/tags/v1.19.32.zip) |
| Tauri 2 / plugins | Native Windows shell | MIT or Apache-2.0; [Tauri MIT license](resources/licenses/Tauri-LICENSE-MIT.txt), [source](https://github.com/tauri-apps/tauri) |
| Python 3.13 | Packaged backend runtime | [Python license](resources/licenses/Python-LICENSE.txt) |
| Requests | HTTP client | [Apache-2.0](resources/licenses/requests-LICENSE) |
| PyYAML | Subscription parsing | [MIT](resources/licenses/PyYAML-LICENSE) |
| urllib3 | HTTP transport | [MIT](resources/licenses/urllib3-LICENSE.txt) |
| idna | Hostname processing | [BSD-style license](resources/licenses/idna-LICENSE.md) |
| charset-normalizer | Encoding detection | [MIT](resources/licenses/charset-normalizer-LICENSE) |
| certifi | TLS trust roots | [MPL-2.0](resources/licenses/certifi-LICENSE) |
| PyInstaller | Backend packaging | [GPL with distribution exception](resources/licenses/pyinstaller-COPYING.txt) |

The 0.3.0 frontend runtime dependency versions, original license texts, origins and SHA-256 hashes are recorded in [the frontend inventory](resources/licenses/frontend/README.md) and [manifest](resources/licenses/frontend/manifest.json). These files are bundled with the installer. Most texts are copied unchanged from installed npm packages. Astryx core and StyleX omit a package-level LICENSE in these releases; their MIT texts were retrieved from their official source repositories on 2026-11-09. Vite 7.3.7 is a build tool, not a runtime dependency shipped in the web bundle. All resolved frontend versions are locked in `frontend/package-lock.json`. Historical Lucide SVG license files remain for archived interfaces.

Rust dependency versions are recorded in `src-tauri/Cargo.lock`. Their original licenses remain applicable. Python build dependencies are recorded in `requirements.txt`.

IPPure and Ping0 are external detection services, not code included in this repository. This project is not affiliated with or endorsed by IPPure, Ping0, Clash Verge, or Mihomo. Their data and access remain subject to the providers' terms and availability.

The Windows selection helper is built from this project's C# source with the installed .NET Framework compiler and uses Windows UI Automation. It does not bundle or modify the Clash Verge application. The isolated upstream source and toolchains used for local validation are not part of this distribution.

The UI screenshot uses synthetic node names and a documentation IP address. No private subscription, credentials, or real detection history is included.
