import unittest
from metrics import rates, human, sample
class MetricsTests(unittest.TestCase):
    def test_rates(self):
        self.assertEqual(rates({'sda':[4096,8192]}, {'sda':[2048,4096]},2),[1024,2048])
    def test_reset_and_new_devices(self):
        self.assertEqual(rates({'sda':[1,2],'sdb':[200,400]}, {'sda':[100,200]},2),[0,0])
    def test_units(self):
        self.assertEqual(human(1024**3),'1G')
    def test_live_sample(self):
        value=sample(); self.assertGreater(sum(value['cpu']),0)
        self.assertNotIn('lo',value['net'])
if __name__=='__main__': unittest.main()
