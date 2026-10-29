"""Read-only route selection. Bind only the app's own sockets to a physical adapter."""
import json
import subprocess
import time

from catalog import PanelError

SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$adapters = @(Get-NetAdapter -Physical | Where-Object Status -eq 'Up')
$routes = @(Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' | Where-Object { $_.InterfaceIndex -in $adapters.ifIndex })
$best = $routes | Sort-Object @{Expression={$_.RouteMetric + $_.InterfaceMetric}} | Select-Object -First 1
if ($best) { @{name=$best.InterfaceAlias;index=$best.InterfaceIndex} | ConvertTo-Json -Compress }
'''


class Network:
    def __init__(self):
        self.value, self.checked = None, 0

    def interface(self):
        if self.value and time.monotonic() - self.checked < 60:
            return self.value['name']
        try:
            result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', SCRIPT],
                                    capture_output=True, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
            value = json.loads(result.stdout.decode('utf-8-sig')) if result.returncode == 0 else None
            if not value or not value.get('name'):
                raise ValueError()
            self.value, self.checked = value, time.monotonic()
            return value['name']
        except (OSError, ValueError, subprocess.SubprocessError):
            self.value = None
            raise PanelError('没有确认到可用的物理网卡，自动检测暂缓。请检查 Wi-Fi 或有线网络。') from None
