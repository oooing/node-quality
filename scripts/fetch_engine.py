"""Fetch a pinned official Mihomo release without reading any local VPN configuration."""
import argparse
import hashlib
import io
import json
from pathlib import Path
from urllib.request import Request, urlopen
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'resources' / 'engine' / 'mihomo.exe')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'resources' / 'engine' / 'manifest.json').read_text(encoding='utf-8'))
    request = Request(manifest['url'], headers={'User-Agent': 'node-quality-build'})
    print(f"Downloading {manifest['asset']}...")
    with urlopen(request, timeout=120) as response:
        archive = response.read()
    if hashlib.sha256(archive).hexdigest() != manifest['sha256']:
        raise SystemExit('Mihomo archive checksum mismatch; no engine was installed.')
    with zipfile.ZipFile(io.BytesIO(archive)) as package:
        entries = [n for n in package.namelist() if n.lower().endswith('.exe')]
        if len(entries) != 1:
            raise SystemExit('Unexpected Mihomo archive contents; no engine was installed.')
        binary = package.read(entries[0])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.output.with_suffix('.download')
    temporary.write_bytes(binary)
    temporary.replace(args.output)
    print(f"Verified SHA-256. Saved {args.output.name} ({len(binary):,} bytes).")


if __name__ == '__main__':
    main()
