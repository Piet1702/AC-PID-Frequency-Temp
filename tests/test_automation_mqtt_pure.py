"""Standalone tests for the broker-monitor policy, no Home Assistant required."""
from __future__ import annotations
import ast
from datetime import datetime, timedelta, timezone
import unittest
from pathlib import Path

source = Path(__file__).resolve().parents[1] / 'custom_components/ac_pid_frequency_temp/automation_mqtt.py'
module = ast.parse(source.read_text(encoding='utf-8'))
funcs = {node.name: node for node in module.body if isinstance(node, ast.FunctionDef)}
compiled = compile(ast.Module(body=[funcs['valid_automation_id'], funcs['classify_monitor']], type_ignores=[]), str(source), 'exec')
namespace = {'datetime': datetime}
exec(compiled, namespace)
valid = namespace['valid_automation_id']
check = namespace['classify_monitor']
NOW = datetime(2026, 11, 15, 9, 0, tzinfo=timezone.utc)

class TestMqttPolicy(unittest.TestCase):
    def test_entity_id(self):
        self.assertTrue(valid('automation.send_simulated_hvac_temperature'))
        self.assertFalse(valid('switch.test'))
        self.assertFalse(valid('automation.'))
        self.assertFalse(valid(None))
    def test_not_configured(self):
        self.assertEqual(check(automation_state=None,last_received=None,now=NOW,interval_s=5), 'automation_missing')
    def test_disabled(self):
        self.assertEqual(check(automation_state='off',last_received=None,now=NOW,interval_s=5), 'automation_off')
    def test_monitoring(self):
        self.assertEqual(check(automation_state='on',last_received=None,now=NOW,interval_s=5), 'monitoring')
    def test_receiving(self):
        self.assertEqual(check(automation_state='on',last_received=NOW-timedelta(seconds=5),now=NOW,interval_s=5), 'receiving')
    def test_delayed(self):
        self.assertEqual(check(automation_state='on',last_received=NOW-timedelta(seconds=21),now=NOW,interval_s=5), 'delayed')
    def test_longer_configured_interval(self):
        self.assertEqual(check(automation_state='on',last_received=NOW-timedelta(seconds=35),now=NOW,interval_s=20), 'receiving')

if __name__ == '__main__':
    unittest.main()
