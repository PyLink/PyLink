# world.py: global state variables go here

from collections import defaultdict
import threading

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
