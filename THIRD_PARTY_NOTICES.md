# Licensing and third-party components

Node Quality (节点优选), Copyright (C) 2026 oooing and contributors.

The application source is licensed under **GPL-3.0-only**, except where an included third-party file states otherwise. See [LICENSE](LICENSE). The program is provided without warranty.

| Component | Use | License / source |
| --- | --- | --- |
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

Rust dependency versions are recorded in `src-tauri/Cargo.lock`. Their original licenses remain applicable. Python build dependencies are recorded in `requirements.txt`.

IPPure is an external detection service, not code included in this repository. This project is not affiliated with or endorsed by IPPure, Clash Verge, or Mihomo. IPPure data and access remain subject to the provider's terms and availability.

The UI screenshot uses synthetic node names and a documentation IP address. No private subscription, credentials, or real detection history is included.
