# Frontend runtime licenses · 0.3.0

Installed package versions were checked against `frontend/node_modules` and `frontend/package-lock.json`. License files are preserved verbatim. This inventory includes direct and transitive runtime packages; tree-shaking may omit unused code.

| Package | Version | License | Original text |
| --- | --- | --- | --- |
| @astryxdesign/core | 0.7.11 | MIT | [astryxdesign-core-LICENSE.txt](astryxdesign-core-LICENSE.txt) |
| @astryxdesign/theme-neutral | 0.7.11 | MIT | [astryxdesign-theme-neutral-LICENSE.txt](astryxdesign-theme-neutral-LICENSE.txt) |
| @stylexjs/stylex | 0.19.1 | MIT | [stylexjs-stylex-LICENSE.txt](stylexjs-stylex-LICENSE.txt) |
| lucide-react | 1.18.0 | ISC | [lucide-react-LICENSE.txt](lucide-react-LICENSE.txt) |
| react | 19.3.1 | MIT | [react-LICENSE.txt](react-LICENSE.txt) |
| react-dom | 19.3.1 | MIT | [react-dom-LICENSE.txt](react-dom-LICENSE.txt) |
| scheduler | 0.28.0 | MIT | [scheduler-LICENSE.txt](scheduler-LICENSE.txt) |
| intl-messageformat | 11.2.15 | BSD-3-Clause | [intl-messageformat-LICENSE.txt](intl-messageformat-LICENSE.txt) |
| @formatjs/fast-memoize | 3.1.7 | MIT | [formatjs-fast-memoize-LICENSE.txt](formatjs-fast-memoize-LICENSE.txt) |
| @formatjs/icu-messageformat-parser | 3.5.18 | MIT | [formatjs-icu-messageformat-parser-LICENSE.txt](formatjs-icu-messageformat-parser-LICENSE.txt) |
| @formatjs/icu-skeleton-parser | 2.1.11 | MIT | [formatjs-icu-skeleton-parser-LICENSE.txt](formatjs-icu-skeleton-parser-LICENSE.txt) |
| css-mediaquery | 0.1.2 | BSD | [css-mediaquery-LICENSE.txt](css-mediaquery-LICENSE.txt) |
| invariant | 2.2.4 | MIT | [invariant-LICENSE.txt](invariant-LICENSE.txt) |
| loose-envify | 1.4.0 | MIT | [loose-envify-LICENSE.txt](loose-envify-LICENSE.txt) |
| js-tokens | 4.0.0 | MIT | [js-tokens-LICENSE.txt](js-tokens-LICENSE.txt) |
| styleq | 0.2.1 | MIT | [styleq-LICENSE.txt](styleq-LICENSE.txt) |

`manifest.json` records source paths or URLs and SHA-256 hashes. Astryx core and StyleX do not ship a package-level license file in these npm releases; their MIT licenses were retrieved from the official [Astryx](https://raw.githubusercontent.com/meta/astryx/main/LICENSE) and [StyleX](https://raw.githubusercontent.com/facebook/stylex/main/LICENSE) repositories on 2026-11-09. All other texts were copied from the installed packages. `css-mediaquery` declares BSD; its included text is the three-clause BSD license.

Vite is used only during the build; its dependency lock is retained in the source repository. The existing Python, Rust and engine notices remain in `THIRD_PARTY_NOTICES.md`.
