"""
control.py - Implements SHUTDOWN and REHASH functionality.
"""
import atexit
import os
import signal
import threading

from pylinkirc import conf, utils, world  # Do not import classes, it'll import loop
from pylinkirc.log import _get_console_log_level, _make_file_logger, _stop_file_loggers, log

from . import login

__all__ = ['remove_network', 'shutdown', 'rehash']


def remove_network(ircobj):
    """Removes a network object from the pool."""
    # Disable autoconnect first by setting the delay negative.
    ircobj.serverdata['autoconnect'] = -1
    ircobj.disconnect()
    del world.networkobjects[ircobj.name]

def _print_remaining_threads():
    log.debug('shutdown(): Remaining threads: %s', ['%s/%s' % (t.name, t.ident) for t in threading.enumerate()])

def _remove_pid():
    pidfile = "%s.pid" % conf.confname
    if world._should_remove_pid:
        # Remove our pid file.
        log.info("Removing PID file %r.", pidfile)
        try:
            os.remove(pidfile)
        except OSError:
            log.exception("Failed to remove PID file %r, ignoring..." % pidfile)
    else:
        log.debug('Not removing PID file %s as world._should_remove_pid is False.' % pidfile)

def _kill_plugins(irc=None):
    if not world.plugins:
        # No plugins were loaded or we were in a pre-initialized state, ignore.
        return

    log.info("Shutting down plugins.")
    for name, plugin in world.plugins.items():
        # Before closing connections, tell all plugins to shutdown cleanly first.
        if hasattr(plugin, 'die'):
            log.debug('coremods.control: Running die() on plugin %s due to shutdown.', name)
            try:
                plugin.die(irc=irc)
            except:  # But don't allow it to crash the server.
                log.exception('coremods.control: Error occurred in die() of plugin %s, skipping...', name)

# We use atexit to register certain functions so that when PyLink cleans up after itself if it
# shuts down because all networks have been disconnected.
atexit.register(_remove_pid)
atexit.register(_kill_plugins)

def shutdown(irc=None):
    """Shuts down the Pylink daemon."""
    if world.shutting_down.is_set():  # We froze on shutdown last time, so immediately abort.
        _print_remaining_threads()
        raise KeyboardInterrupt("Forcing shutdown.")

    world.shutting_down.set()

    # HACK: run the _kill_plugins trigger with the current IRC object. XXX: We should really consider removing this
    # argument, since no plugins actually use it to do anything.
    atexit.unregister(_kill_plugins)
    _kill_plugins(irc=irc)

    # Remove our main PyLink bot as well.
    utils.unregister_service('pylink')

    for ircobj in world.networkobjects.copy().values():
        # Disconnect all our networks.
        try:
            remove_network(ircobj)
        except NotImplementedError:
            continue

    log.info("Waiting for remaining threads to stop; this may take a few seconds. If PyLink freezes "
             "at this stage, press Ctrl-C to force a shutdown.")
    _print_remaining_threads()

    # Done.

def _sigterm_handler(signo, stack_frame):
    """Handles SIGTERM and SIGINT gracefully by shutting down the PyLink daemon."""
    log.info("Shutting down on signal %s." % signo)
    shutdown()

signal.signal(signal.SIGTERM, _sigterm_handler)
signal.signal(signal.SIGINT, _sigterm_handler)

def rehash():
    """Rehashes the PyLink daemon."""
    log.info('Reloading PyLink configuration...')
    old_conf = conf.conf.copy()
    fname = conf.fname
    new_conf = conf.load_conf(fname, errors_fatal=False, logger=log)
    conf.conf = new_conf

    # Reset any file logger options.
    _stop_file_loggers()
    files = new_conf['logging'].get('files')
    if files:
        for filename, config in files.items():
            _make_file_logger(filename, config.get('loglevel'))

    log.debug('rehash: updating console log level')
    world.console_handler.setLevel(_get_console_log_level())
    login._make_cryptcontext()  # refresh password hashing settings

    for network, ircobj in world.networkobjects.copy().items():
        # Server was removed from the config file, disconnect them.
        log.debug('rehash: checking if %r is still in new conf.', network)
        if ircobj.has_cap('virtual-server') or hasattr(ircobj, 'virtual_parent'):
            log.debug('rehash: not removing network %r since it is a virtual server.', network)
            continue

        if network not in new_conf['servers']:
            log.debug('rehash: removing connection to %r (removed from config).', network)
            remove_network(ircobj)
        else:
            # XXX: we should really just add abstraction to Irc to update config settings...
            ircobj.serverdata = new_conf['servers'][network]

            ircobj.autoconnect_active_multiplier = 1

            # Clear the IRC object's channel loggers and replace them with
            # new ones by re-running log_setup().
            while ircobj.loghandlers:
                log.removeHandler(ircobj.loghandlers.pop())

            ircobj.log_setup()

    utils._reset_module_dirs()

    for network, sdata in new_conf['servers'].items():
        # Connect any new networks or disconnected networks if they aren't already.
        if network not in world.networkobjects:
            try:
                proto = utils._get_protocol_module(sdata['protocol'])

                # API note: 2.0.x style of starting network connections
                world.networkobjects[network] = newirc = proto.Class(network)
                newirc.connect()
            except:
                log.exception('Failed to initialize network %r, skipping it...', network)

    log.info('Finished reloading PyLink configuration.')

if os.name == 'posix':
    # Only register SIGHUP/SIGUSR1 on *nix.
    def _sighup_handler(signo, _stack_frame):
        """Handles SIGHUP/SIGUSR1 by rehashing the PyLink daemon."""
        log.info("Signal %s received, reloading config." % signo)
        rehash()

    signal.signal(signal.SIGHUP, _sighup_handler)
    signal.signal(signal.SIGUSR1, _sighup_handler)
