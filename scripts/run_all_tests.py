#!/usr/bin/env python3
"""
统一测试运行器

运行所有测试：python3 run_all_tests.py
"""

import sys
import os
import unittest

# 添加 scripts 目录到 path
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)


def discover_and_run():
    """发现并运行所有测试"""
    loader = unittest.TestLoader()
    start_dir = os.path.join(SCRIPT_DIR, "tests")
    suite = loader.discover(start_dir, pattern="test_*.py")

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    return result.wasSuccessful()


if __name__ == "__main__":
    success = discover_and_run()
    sys.exit(0 if success else 1)
