"""
control.py - Implements SHUTDOWN and REHASH functionality.
"""
import signal
import os

from pylinkirc import world, utils, conf, classes
from pylinkirc.log import log, makeFileLogger, stopFileLoggers
from . import permissions

def remove_network(ircobj):
    """Removes a network object from the pool."""
    # Disable autoconnect first by setting the delay negative.
    ircobj.serverdata['autoconnect'] = -1
    ircobj.disconnect()
    del world.networkobjects[ircobj.name]

def _shutdown(irc=None):
    """Shuts down the Pylink daemon."""
    for name, plugin in world.plugins.items():
        # Before closing connections, tell all plugins to shutdown cleanly first.
        if hasattr(plugin, 'die'):
            log.debug('coremods.control: Running die() on plugin %s due to shutdown.', name)
            try:
                plugin.die(irc)
            except:  # But don't allow it to crash the server.
                log.exception('coremods.control: Error occurred in die() of plugin %s, skipping...', name)

    # Remove our main PyLink bot as well.
    utils.unregisterService('pylink')

    for ircobj in world.networkobjects.copy().values():
        # Disconnect all our networks.
        remove_network(ircobj)

def sigterm_handler(signo, stack_frame):
    """Handles SIGTERM and SIGINT gracefully by shutting down the PyLink daemon."""
    log.info("Shutting down on signal %s." % signo)
    _shutdown()

signal.signal(signal.SIGTERM, sigterm_handler)
signal.signal(signal.SIGINT, sigterm_handler)

def _rehash():
    """Rehashes the PyLink daemon."""
    old_conf = conf.conf.copy()
    fname = conf.fname
    new_conf = conf.loadConf(fname, errors_fatal=False)
    new_conf = conf.validateConf(new_conf)
    conf.conf = new_conf

    # Reset any file logger options.
    stopFileLoggers()
    files = new_conf['logging'].get('files')
    if files:
        for filename, config in files.items():
            makeFileLogger(filename, config.get('loglevel'))

    # Reset permissions.
    log.debug('rehash: resetting permissions.')
    permissions.resetPermissions()

    for network, ircobj in world.networkobjects.copy().items():
        # Server was removed from the config file, disconnect them.
        log.debug('rehash: checking if %r is in new conf still.', network)
        if network not in new_conf['servers']:
            log.debug('rehash: removing connection to %r (removed from config).', network)
            remove_network(ircobj)
        else:
            ircobj.conf = new_conf
            ircobj.serverdata = new_conf['servers'][network]
            ircobj.botdata = new_conf['bot']

            # Clear the IRC object's channel loggers and replace them with
            # new ones by re-running logSetup().
            while ircobj.loghandlers:
                log.removeHandler(ircobj.loghandlers.pop())

            ircobj.logSetup()

            # TODO: update file loggers here too.

    for network, sdata in new_conf['servers'].items():
        # Connect any new networks or disconnected networks if they aren't already.
        if (network not in world.networkobjects) or (not world.networkobjects[network].connection_thread.is_alive()):
            proto = utils.getProtocolModule(sdata['protocol'])
            world.networkobjects[network] = classes.Irc(network, proto, new_conf)

if os.name == 'posix':
    # Only register SIGHUP on *nix.
    def sighup_handler(_signo, _stack_frame):
        """Handles SIGHUP by rehashing the PyLink daemon."""
        log.info("SIGHUP received, reloading config.")
        _rehash()

    signal.signal(signal.SIGHUP, sighup_handler)
