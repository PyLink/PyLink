"""
log.py - PyLink logging module.

This module contains the logging portion of the PyLink framework. Plugins can
access the global logger object by importing "log" from this module
(from log import log).
"""

import logging
import logging.handlers
import os

from . import world, conf

# Stores a list of active file loggers.
fileloggers = []

logdir = os.path.join(os.getcwd(), 'log')
os.makedirs(logdir, exist_ok=True)

# TODO: perhaps make this format configurable?
_format = '%(asctime)s [%(levelname)s] %(message)s'
logformatter = logging.Formatter(_format)

def _get_console_log_level():
    """
    Returns the configured console log level.
    """
    logconf = conf.conf['logging']
    return logconf.get('console', logconf.get('stdout')) or 'INFO'

# Set up logging to STDERR
world.console_handler = logging.StreamHandler()
world.console_handler.setFormatter(logformatter)
world.console_handler.setLevel(_get_console_log_level())

# Get the main logger object; plugins can import this variable for convenience.
log = logging.getLogger()
log.addHandler(world.console_handler)

# This is confusing, but we have to set the root logger to accept all events. Only this way
# can other loggers filter out events on their own, instead of having everything dropped by
# the root logger. https://stackoverflow.com/questions/16624695
log.setLevel(1)

def _make_file_logger(filename, level=None):
    """
    Initializes a file logging target with the given filename and level.
    """
    # Use log names specific to the current instance, to prevent multiple
    # PyLink instances from overwriting each others' log files.
    target = os.path.join(logdir, '%s-%s.log' % (conf.confname, filename))

    logrotconf = conf.conf.get('logging', {}).get('filerotation', {})

    # Max amount of bytes per file, before rotation is done. Defaults to 50 MiB.
    maxbytes = logrotconf.get('max_bytes', 52428800)

    # Amount of backups to make (e.g. pylink-debug.log, pylink-debug.log.1, pylink-debug.log.2, ...)
    # Defaults to 5.
    backups = logrotconf.get('backup_count', 5)

    filelogger = logging.handlers.RotatingFileHandler(target, maxBytes=maxbytes, backupCount=backups, encoding='utf-8')
    filelogger.setFormatter(logformatter)

    # If no log level is specified, use the same one as the console logger.
    level = level or _get_console_log_level()
    filelogger.setLevel(level)

    log.addHandler(filelogger)
    global fileloggers
    fileloggers.append(filelogger)

    return filelogger

def _stop_file_loggers():
    """
    De-initializes all file loggers.
    """
    global fileloggers
    for handler in fileloggers.copy():
        handler.close()
        log.removeHandler(handler)
        fileloggers.remove(handler)

# Set up file logging now, creating a file logger for each block.
files = conf.conf['logging'].get('files')
if files:
    for filename, config in files.items():
        if isinstance(config, dict):
            _make_file_logger(filename, config.get('loglevel'))
        else:
            log.warning('Got invalid file logging pair %r: %r; are your indentation and block '
                        'commenting consistent?', filename, config)

log.debug("log: Emptying _log_queue")
# Process and empty the log queue
while world._log_queue:
    level, text = world._log_queue.popleft()
    log.log(level, text)
log.debug("log: Emptied _log_queue")

class PyLinkChannelLogger(logging.Handler):
    """
    Log handler to log to channels in PyLink.
    """
    def __init__(self, irc, channel, level=None):
        super(PyLinkChannelLogger, self).__init__()
        self.irc = irc
        self.channel = channel

        # Set whether we've been called already. This is used to prevent recursive
        # loops when logging.
        self.called = False

        # Use a slightly simpler message formatter - logging to IRC doesn't need
        # logging the time.
        formatter = logging.Formatter('[%(levelname)s] %(message)s')
        self.setFormatter(formatter)

        # HACK: Use setLevel twice to first coerse string log levels to ints,
        # for easier comparison.
        level = level or log.getEffectiveLevel()
        self.setLevel(level)

        # Log level has to be at least 20 (INFO) to prevent loops due
        # to outgoing messages being logged
        loglevel = max(self.level, 20)
        self.setLevel(loglevel)

    def emit(self, record):
        """
        Logs a record to the configured channels for the network given.
        """
        # Only start logging if we're finished bursting, and our main client is in
        # a stable condition.
        # 1) irc.pseudoclient must be initialized already
        # 2) IRC object must be finished bursting
        # 3) Target channel must exist
        # 4) This function hasn't been called already (prevents recursive loops).
        if self.irc.pseudoclient and self.irc.connected.is_set() \
                and self.channel in self.irc.channels and not self.called:

            self.called = True
            msg = self.format(record)

            # Send the message. If this fails, abort. No more messages will be
            # sent from this logger until the next sending succeeds.
            for line in msg.splitlines():
                try:
                    self.irc.msg(self.channel, line)
                except:
                    return
                else:
                    self.called = False

