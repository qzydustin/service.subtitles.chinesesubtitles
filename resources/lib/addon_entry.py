# -*- coding: utf-8 -*-
"""Kodi subtitle addon entry point."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from kodi.plugin import run

run()
