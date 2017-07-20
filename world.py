"""
world.py: Stores global variables for PyLink, including lists of active IRC objects and plugins.
"""

from collections import defaultdict, deque
import threading
import time

# This indicates whether we're running in tests mode. What it actually does
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

# Trigger to be set when all IRC objects are initially created.
started = threading.Event()
start_ts = time.time()

# Source address.
source = "https://github.com/GLolol/PyLink"  # CHANGE THIS IF YOU'RE FORKING!!

# Fallback hostname used in various places internally when hostname isn't configured.
fallback_hostname = 'pylink.int'

# Defines messages to be logged as soon as the log system is set up, for modules like conf that are
# initialized before log. This is processed (and then not used again) when the log module loads.
log_queue = deque()

# Determines whether we have a PID file that needs to be removed.
_should_remove_pid = False
