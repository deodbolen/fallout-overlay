import unittest
from unittest.mock import Mock,patch
from system_dashboard import SystemDashboard,cpu_percent,rate
from browser import Navigator
import curses


def sample(timestamp,cpu,rx,disk):
    return {'time':timestamp,'cpus':{'cpu':cpu,'cpu0':cpu},
            'memory':{'MemTotal':8*1024**3,'MemAvailable':2*1024**3,
                      'SwapTotal':2*1024**3,'SwapFree':1024**3},
            'networks':{'eth0':(rx,rx,0,0)},'disks':{'sda':(disk,disk,10+int(timestamp),100+int(timestamp)*20)},
            'tasks':{'ctxt':100+int(timestamp)*20,'processes':10+int(timestamp),'procs_running':2,'procs_blocked':0},
            'vm':{'pswpin':int(timestamp)*4096,'pswpout':0}}


class DashboardTests(unittest.TestCase):
    def test_cpu_and_counter_resets(self):
        first=[100,0,100,800,0,0,0,0]
        second=[150,0,150,850,50,0,0,0]
        self.assertEqual(cpu_percent(second,first),50)
        self.assertIsNone(cpu_percent(first,second))
        self.assertIsNone(rate(1,2,1))
        self.assertIsNone(rate(10,None,1))
        self.assertIsNone(rate(10,1,0))

    def test_snapshot_rates_memory_and_one_second_refresh(self):
        first=sample(0,[100,0,100,800,0,0,0,0],1024,0)
        second=sample(1,[150,0,150,850,50,0,0,0],3072,4096)
        with patch('system_dashboard.read',return_value=''),patch('system_dashboard.Path.glob',return_value=[]), \
             patch('system_dashboard.time.monotonic',side_effect=[0,1.1,1.2]):
            dashboard=SystemDashboard()
            with patch.object(dashboard,'sample',side_effect=[first,second]) as collect:
                self.assertIn('sampling…','\n'.join(dashboard.lines(120)))
                lines=dashboard.lines(120)
                output='\n'.join(lines)
                self.assertIn('50.0%',output)
                self.assertIn('75.0%',output)
                self.assertIn('6.0 GiB / 8.0 GiB',output)
                self.assertIn('1.0 GiB / 2.0 GiB',output)
                self.assertIn('RX 2.0 KiB/s',output)
                self.assertIn('R 4.0 KiB/s',output)
                self.assertEqual(dashboard.lines(120),lines)
                self.assertEqual(collect.call_count,2)

    def test_home_keeps_clock_and_power_section_context(self):
        screen=Mock(); screen.getmaxyx.return_value=(30,120)
        navigator=Navigator(screen); navigator.sound=Mock()
        navigator.dashboard=Mock()
        navigator.dashboard.lines.return_value=['CPU TOTAL','RAM']
        self.assertEqual(navigator.rows()[0],'dashboard')
        self.assertEqual(navigator.rows()[2],['CPU TOTAL','RAM'])
        self.assertTrue(navigator.switch_home_page(curses.KEY_LEFT))
        self.assertEqual(navigator.rows()[0],'clock')
        self.assertTrue(navigator.switch_home_page(curses.KEY_RIGHT))
        self.assertEqual(navigator.rows()[0],'dashboard')
        navigator.section=1
        self.assertFalse(navigator.switch_home_page(curses.KEY_RIGHT))


if __name__=='__main__': unittest.main()
