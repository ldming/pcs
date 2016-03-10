from __future__ import (
    absolute_import,
    division,
    print_function,
    unicode_literals,
)

import unittest


from pcs import utils

class MiscTest(unittest.TestCase):
    def test_get_timeout_seconds(self):
        self.assertEqual(utils.get_timeout_seconds("10"), 10)
        self.assertEqual(utils.get_timeout_seconds("10s"), 10)
        self.assertEqual(utils.get_timeout_seconds("10sec"), 10)
        self.assertEqual(utils.get_timeout_seconds("10m"), 600)
        self.assertEqual(utils.get_timeout_seconds("10min"), 600)
        self.assertEqual(utils.get_timeout_seconds("10h"), 36000)
        self.assertEqual(utils.get_timeout_seconds("10hr"), 36000)

        self.assertEqual(utils.get_timeout_seconds("1a1s"), None)
        self.assertEqual(utils.get_timeout_seconds("10mm"), None)
        self.assertEqual(utils.get_timeout_seconds("10mim"), None)
        self.assertEqual(utils.get_timeout_seconds("aaa"), None)
        self.assertEqual(utils.get_timeout_seconds(""), None)

        self.assertEqual(utils.get_timeout_seconds("1a1s", True), "1a1s")
        self.assertEqual(utils.get_timeout_seconds("10mm", True), "10mm")
        self.assertEqual(utils.get_timeout_seconds("10mim", True), "10mim")
        self.assertEqual(utils.get_timeout_seconds("aaa", True), "aaa")
        self.assertEqual(utils.get_timeout_seconds("", True), "")


if __name__ == "__main__":
    unittest.main()
