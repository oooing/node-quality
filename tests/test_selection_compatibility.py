"""Reject changed save schemas before touching the official GUI; allow extra fields."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from catalog import PanelError
from official_selection import OfficialSelection


class SelectionCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'profiles.yaml'
        self.profile = {'source_root': self.temp.name, 'source_uid': 'one'}
        self.record = {'current': 'one', 'items': [{'uid': 'one', 'selected': [{'name': 'Proxy', 'now': 'A'}]}]}
        self.controller = Mock()
        self.controller.request.return_value = {'type': 'Selector', 'now': 'A'}
        self.selection = OfficialSelection(verify_timeout=.01)
        self.selection._invoke = Mock()

    def tearDown(self):
        self.temp.cleanup()

    def write(self, record):
        self.path.write_text(yaml.safe_dump(record, allow_unicode=True), encoding='utf-8')

    def test_unknown_save_layout_refuses_before_ui_and_preserves_files(self):
        for selected in ({'Proxy': 'A'}, '', False, [None], [{'group': 'Proxy', 'node': 'A'}],
                         [{'name': 'Proxy', 'now': 42}], [{'name': 'Proxy', 'now': 'A'}] * 2):
            with self.subTest(selected=selected):
                record = copy.deepcopy(self.record)
                record['items'][0]['selected'] = selected
                self.write(record)
                before = self.path.read_bytes()
                with self.assertRaisesRegex(PanelError, '保存格式暂不兼容'):
                    self.selection(self.profile, 'Proxy', 'B', self.controller)
                self.selection._invoke.assert_not_called()
                self.assertEqual(before, self.path.read_bytes())
        self.controller.request.assert_not_called()

    def test_new_metadata_fields_do_not_block_compatible_save_layout(self):
        self.record['future_metadata'] = {'version': 'future'}
        self.record['items'][0]['selected'][0]['extra'] = {'updated': 1}
        self.write(self.record)
        result = self.selection(self.profile, 'Proxy', 'A', self.controller)
        self.assertTrue(result['persisted'])
        self.assertTrue(result['already_saved'])
        self.selection._invoke.assert_not_called()

    def test_format_change_during_switch_is_partial_failure_not_success(self):
        self.write(self.record)

        def changed_format(*_):
            self.controller.request.return_value = {'type': 'Selector', 'now': 'B'}
            self.record['items'][0]['selected'] = {'Proxy': 'B'}
            self.write(self.record)

        self.selection._invoke.side_effect = changed_format
        with self.assertRaisesRegex(PanelError, '线路已换用，但未确认保存'):
            self.selection(self.profile, 'Proxy', 'B', self.controller)
        self.selection._invoke.assert_called_once()
        self.assertTrue(all(c.args[0] == 'GET' for c in self.controller.request.call_args_list))


if __name__ == '__main__':
    unittest.main()
