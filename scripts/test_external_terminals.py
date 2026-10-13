import unittest
from unittest.mock import Mock
from external_terminals import is_external_terminal


class ExternalTerminalTests(unittest.TestCase):
    def window(self, group, instance, pid=100):
        return Mock(get_pid=lambda: pid, get_class_group_name=lambda: group,
                    get_class_instance_name=lambda: instance)

    def test_external_xfce_terminal(self):
        self.assertTrue(is_external_terminal(self.window('Xfce4-terminal', None), 200))

    def test_embedded_window_is_excluded(self):
        self.assertFalse(is_external_terminal(self.window('XTerm', 'xterm', 200), 200))

    def test_other_apps_and_missing_classes(self):
        self.assertFalse(is_external_terminal(self.window('Thunar', 'thunar'), 200))
        self.assertFalse(is_external_terminal(self.window(None, None), 200))


if __name__ == '__main__':
    unittest.main()
