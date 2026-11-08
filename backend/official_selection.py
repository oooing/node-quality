"""Ask the official Windows UI to select, then independently verify its saved record."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.parse import quote

import yaml

from catalog import PanelError


def saved_selection(profile, group):
    record = yaml.safe_load((Path(profile['source_root']) / 'profiles.yaml').read_text(encoding='utf-8'))
    incompatible = 'Clash 的保存格式暂不兼容，请先在 Clash 中换用线路。'
    if not isinstance(record, dict) or not isinstance(record.get('items'), list):
        raise PanelError(incompatible)
    if record.get('current') != profile['source_uid']:
        raise PanelError('Clash 的线路列表已变化，请刷新后重试。')
    matches = [p for p in record['items'] if isinstance(p, dict) and p.get('uid') == profile['source_uid']]
    if len(matches) != 1:
        raise PanelError(incompatible)
    selected = matches[0].get('selected')
    if selected is None:
        selected = []
    if not isinstance(selected, list) or any(
        not isinstance(p, dict) or not {'name', 'now'}.issubset(p)
        or any(p[k] is not None and not isinstance(p[k], str) for k in ('name', 'now'))
        for p in selected
    ):
        raise PanelError(incompatible)
    targets = [p for p in selected if p['name'] == group]
    if len(targets) > 1:
        raise PanelError(incompatible)
    return targets[0]['now'] if targets else None


def helper_error(detail):
    if 'single Clash Verge instance' in detail:
        return '请确认只打开了一个 Clash Verge 窗口所属的客户端。'
    if 'not supported' in detail:
        return '这个客户端暂不支持保存换用结果，请在客户端中选择线路。'
    if 'Ambiguous control' in detail:
        return 'Clash 中有多个同名选项，无法准确定位，请在 Clash 中选择线路。'
    if 'Timed out' in detail or 'unavailable' in detail:
        return '未能找到 Clash 中的目标线路，请确认窗口可操作后重试。'
    return 'Clash 界面操作未完成，请确认它可正常打开后重试。'


class OfficialSelection:
    def __init__(self, helper_path=None, verify_timeout=5):
        directory = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[1] / 'resources/backend'
        self.helper_path = Path(helper_path) if helper_path else directory / 'clash-select.exe'
        self.verify_timeout = verify_timeout

    def _invoke(self, profile, group, node):
        if not self.helper_path.is_file():
            raise PanelError('缺少线路保存组件，请重新安装云鉴。')
        request = {'source_root': profile['source_root'], 'group': group, 'node': node, 'mode': 'select'}
        with tempfile.TemporaryDirectory(prefix='yunjian-select-') as temp:
            path = Path(temp) / 'request.json'
            path.write_text(json.dumps(request, ensure_ascii=False), encoding='utf-8')
            try:
                result = subprocess.run([str(self.helper_path), str(path)], capture_output=True,
                    encoding='utf-8-sig', timeout=35, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                response = json.loads(result.stdout)
            except subprocess.TimeoutExpired:
                raise PanelError('Clash 响应超时，请查看它是否已完成换用。') from None
            except (OSError, ValueError, UnicodeError):
                raise PanelError('线路保存组件未能正常运行，请重试。') from None
            if result.returncode or not response.get('ok'):
                raise PanelError(helper_error(str(response.get('error', ''))))

    def __call__(self, profile, group, node, controller):
        path = '/proxies/' + quote(group, safe='')

        def is_selected():
            running = controller.request('GET', path)
            return isinstance(running, dict) and running.get('type') == 'Selector' and running.get('now') == node

        try:
            # Validate the saved format before any UI action, including for new app versions.
            persisted = saved_selection(profile, group) == node
            if is_selected() and persisted:
                return {'persisted': True, 'already_saved': True}
        except (OSError, yaml.YAMLError):
            raise PanelError('无法读取 Clash 保存的线路，请稍后重试。') from None

        failure = None
        try:
            self._invoke(profile, group, node)
        except PanelError as error:
            failure = error
        until = time.monotonic() + (self.verify_timeout if failure is None else 0)
        selected = False
        while True:
            try:
                selected = is_selected()
                persisted = saved_selection(profile, group) == node
                if selected and persisted:
                    return {'persisted': True, 'already_saved': False}
            except (OSError, yaml.YAMLError, PanelError):
                pass
            if time.monotonic() >= until:
                break
            time.sleep(.1)
        if selected:
            raise PanelError('线路已换用，但未确认保存；请在 Clash 中重新选择，以便重启后保留。')
        if failure:
            raise failure
        raise PanelError('未确认成功换用，请到 Clash 查看当前线路。')
