import unittest
from quantities import durations, clocks

class Quantities(unittest.TestCase):
    def test_half_hours(self):
        for text,minutes in [("一个半小时",90),("两个半小时",150),("1.5小时",90),("半小时",30),
                             ("推迟半个小时",30),("一小时二十分钟",80),("三刻钟",45),("2个小时",120)]:
            self.assertEqual(durations(text),[minutes],text)

    def test_quarter_clock(self):
        self.assertEqual(clocks("三点一刻")[0][2],"03:15")
        self.assertEqual(clocks("下午三点三刻")[0][2],"15:45")
        self.assertEqual(clocks("九点半")[0][2],"09:30")

if __name__=="__main__":
    unittest.main()
