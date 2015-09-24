# world.py: global state variables go here

from collections import defaultdict
import threading
import subprocess

# Global variable to indicate whether we're being ran directly, or imported
# for a testcase.
testing = True

global bot_commands, command_hooks
# This should be a mapping of command names to functions
bot_commands = defaultdict(list)
command_hooks = defaultdict(list)
networkobjects = {}
schedulers = {}
plugins = []
whois_handlers = []
started = threading.Event()

version = "<unknown>"
source = "https://github.com/GLolol/PyLink"  # CHANGE THIS IF YOU'RE FORKING!!

# Only run this once.
if version == "<unknown>":
    # Get version from Git tags.
    try:
        version = 'v' + subprocess.check_output(['git', 'describe', '--tags']).decode('utf-8').strip()
    except Exception as e:
        print('ERROR: Failed to get version from "git describe --tags": %s: %s' % (type(e).__name__, e))
