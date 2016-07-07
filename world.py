"""
world.py: Stores global variables for PyLink, including lists of active IRC objects and plugins.
"""

from collections import defaultdict
import threading

# This indicates whether we're running in tests modes. What it actually does
# though is control whether IRC connections should be threaded or not.
testing = False

# Statekeeping for our hooks list, IRC objects, loaded plugins, and initialized
# service bots.
hooks = defaultdict(list)
networkobjects = {}
plugins = {}
services = {}

# Registered extarget handlers. This maps exttarget names (strings) to handling functions.
exttarget_handlers = {}

started = threading.Event()

source = "https://github.com/GLolol/PyLink"  # CHANGE THIS IF YOU'RE FORKING!!
