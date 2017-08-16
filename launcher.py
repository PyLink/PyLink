#!/usr/bin/env python3
"""
PyLink IRC Services launcher.
"""

import os
import sys
from pylinkirc import world, conf, __version__, real_version

try:
    import psutil
except ImportError:
    psutil = None

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Starts an instance of PyLink IRC Services.')
    parser.add_argument('config', help='specifies the path to the config file (defaults to pylink.yml)', nargs='?', default='pylink.yml')
    parser.add_argument("-v", "--version", help="displays the program version and exits", action='store_true')
    parser.add_argument("-c", "--check-pid", help="no-op; kept for compatiblity with PyLink 1.x", action='store_true')
    parser.add_argument("-n", "--no-pid", help="skips generating and checking PID files", action='store_true')
    args = parser.parse_args()

    if args.version:  # Display version and exit
        print('PyLink %s (in VCS: %s)' % (__version__, real_version))
        sys.exit()

    # FIXME: we can't pass logging on to conf until we set up the config...
    conf.loadConf(args.config)

    from pylinkirc.log import log
    from pylinkirc import classes, utils, coremods
    log.info('PyLink %s starting...', __version__)

    # Set terminal window title. See https://bbs.archlinux.org/viewtopic.php?id=85567
    # and https://stackoverflow.com/questions/7387276/
    if os.name == 'nt':
        import ctypes
        ctypes.windll.kernel32.SetConsoleTitleW("PyLink %s" % __version__)
    elif os.name == 'posix':
        sys.stdout.write("\x1b]2;PyLink %s\x07" % __version__)

    # Write and check for an existing PID file unless specifically told not to.
    if not args.no_pid:
        pidfile = '%s.pid' % conf.confname
        if os.path.exists(pidfile):

            has_stale_pid = False
            if psutil is not None and os.name == 'posix':
                # FIXME: Haven't tested this on other platforms, so not turning it on by default.
                with open(pidfile) as f:
                    try:
                        pid = int(f.read())
                        proc = psutil.Process(pid)
                    except psutil.NoSuchProcess:  # Process doesn't exist!
                        has_stale_pid = True
                        log.info("Ignoring stale PID %s from PID file %r: no such process exists.", pid, pidfile)
                    else:
                        # This PID got reused for something that isn't us?
                        if not any('pylink' in arg.lower() for arg in proc.cmdline()):
                            log.info("Ignoring stale PID %s from PID file %r: process command line %r is not us", pid, pidfile, proc.cmdline())
                            has_stale_pid = True

            if not has_stale_pid:
                log.error("PID file exists %r; aborting!", pidfile)
                if psutil is None:
                    log.error("If PyLink didn't shut down cleanly last time it ran, or you're upgrading "
                              "from PyLink < 1.1-dev, delete %r and start the server again.", pidfile)
                    if os.name == 'posix':
                        log.error("Alternatively, you can install psutil for Python 3 (pip3 install psutil), "
                                  "which will allow this launcher to detect stale PID files and ignore them.")
                sys.exit(1)

        with open(pidfile, 'w') as f:
            f.write(str(os.getpid()))
        world._should_remove_pid = True

    # Import plugins first globally, because they can listen for events
    # that happen before the connection phase.
    to_load = conf.conf['plugins']
    utils.resetModuleDirs()
    # Here, we override the module lookup and import the plugins
    # dynamically depending on which were configured.
    for plugin in to_load:
        try:
            world.plugins[plugin] = pl = utils.loadPlugin(plugin)
        except Exception as e:
            log.exception('Failed to load plugin %r: %s: %s', plugin, type(e).__name__, str(e))
        else:
            if hasattr(pl, 'main'):
                log.debug('Calling main() function of plugin %r', pl)
                pl.main()

    # Initialize all the networks one by one
    for network, sdata in conf.conf['servers'].items():

        try:
            protoname = sdata['protocol']
        except (KeyError, TypeError):
            log.error("(%s) Configuration error: No protocol module specified, aborting.", network)
        else:
            # Fetch the correct protocol module.
            proto = utils.getProtocolModule(protoname)

            # Create and connect the network.
            world.networkobjects[network] = irc = proto.Class(network)
            log.debug('Connecting to network %r', network)
            irc.connect()

    world.started.set()
    log.info("Loaded plugins: %s", ', '.join(sorted(world.plugins.keys())))

    coremods.permissions.reset_permissions()  # XXX we should probably move this to run on import
