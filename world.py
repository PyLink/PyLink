"""
world.py: Stores global variables for PyLink, including lists of active IRC objects and plugins.
"""

from collections import defaultdict
import threading
import subprocess
import os

# This indicates whether we're running in tests modes. What it actually does
# though is control whether IRC connections should be threaded or not.
testing = False

# Statekeeping for our hooks list, IRC objects, loaded plugins, and initialized
# service bots.
hooks = defaultdict(list)
networkobjects = {}
plugins = {}
services = {}

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
