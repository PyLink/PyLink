"""
world.py: Stores global variables for PyLink, including lists of active IRC objects and plugins.
"""

import threading
import time
from collections import defaultdict, deque

__all__ = ['testing', 'hooks', 'networkobjects', 'plugins', 'services',
           'exttarget_handlers', 'started', 'start_ts', 'shutting_down',
           'source', 'fallback_hostname', 'daemon']

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

# Global daemon starting time.
start_ts = time.time()

# Trigger to set on shutdown.
shutting_down = threading.Event()

# Source address.
source = "https://github.com/jlu5/PyLink"  # CHANGE THIS IF YOU'RE FORKING!!

# Fallback hostname used in various places internally when hostname isn't configured.
fallback_hostname = 'pylink.int'

# Defines messages to be logged as soon as the log system is set up, for modules like conf that are
# initialized before log. This is processed (and then not used again) when the log module loads.
_log_queue = deque()

# Determines whether we have a PID file that needs to be removed.
_should_remove_pid = False

# Determines whether we're daemonized.
daemon = False
