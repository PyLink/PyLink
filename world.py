"""
world.py: Stores global variables for PyLink, including lists of active IRC objects and plugins.
"""

from collections import defaultdict
import threading
import subprocess
import os

# Global variable to indicate whether we're being ran directly, or imported
# for a testcase. This defaults to True.
testing = True

# Sets the default protocol module to use with tests.
testing_ircd = 'inspircd'

global commands, hooks
# This should be a mapping of command names to functions
commands = defaultdict(list)
hooks = defaultdict(list)
networkobjects = {}
plugins = {}
whois_handlers = []
started = threading.Event()

plugins_folder = os.path.join(os.getcwd(), 'plugins')
protocols_folder = os.path.join(os.getcwd(), 'protocols')

version = "<unknown>"
source = "https://github.com/GLolol/PyLink"  # CHANGE THIS IF YOU'RE FORKING!!

# Only run this once.
if version == "<unknown>":
    # Get version from Git tags.
    try:
        version = 'v' + subprocess.check_output(['git', 'describe', '--tags']).decode('utf-8').strip()
    except Exception as e:
        print('ERROR: Failed to get version from "git describe --tags": %s: %s' % (type(e).__name__, e))
