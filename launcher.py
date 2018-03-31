#!/usr/bin/env python3
"""
PyLink IRC Services launcher.
"""

import os
import sys
import signal
import time
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
    parser.add_argument("-c", "--check-pid", help="no-op; kept for compatibility with PyLink <= 1.2.x", action='store_true')
    parser.add_argument("-n", "--no-pid", help="skips generating and checking PID files", action='store_true')
    parser.add_argument("-r", "--restart", help="restarts the PyLink instance with the given config file", action='store_true')
    parser.add_argument("-s", "--stop", help="stops the PyLink instance with the given config file", action='store_true')
    parser.add_argument("-R", "--rehash", help="rehashes the PyLink instance with the given config file", action='store_true')
    parser.add_argument("-d", "--daemonize", help="[experimental] daemonizes the PyLink instance on POSIX systems", action='store_true')
    args = parser.parse_args()

    if args.version:  # Display version and exit
        print('PyLink %s (in VCS: %s)' % (__version__, real_version))
        sys.exit()

    # XXX: repetitive
    elif args.no_pid and (args.restart or args.stop or args.rehash):
        print('ERROR: --no-pid cannot be combined with --restart or --stop')
        sys.exit(1)
    elif args.rehash and os.name != 'posix':
        print('ERROR: Rehashing via the command line is not supported outside Unix.')
        sys.exit(1)

    # FIXME: we can't pass logging on to conf until we set up the config...
    conf.loadConf(args.config)

    from pylinkirc.log import log
    from pylinkirc import classes, utils, coremods

    # Write and check for an existing PID file unless specifically told not to.
    if not args.no_pid:
        pidfile = '%s.pid' % conf.confname
        has_pid = False
        pid = None
        if os.path.exists(pidfile):

            has_pid = True
            if psutil is not None and os.name == 'posix':
                # FIXME: Haven't tested this on other platforms, so not turning it on by default.
                with open(pidfile) as f:
                    try:
                        pid = int(f.read())
                        proc = psutil.Process(pid)
                    except psutil.NoSuchProcess:  # Process doesn't exist!
                        has_pid = False
                        log.info("Ignoring stale PID %s from PID file %r: no such process exists.", pid, pidfile)
                    else:
                        # This PID got reused for something that isn't us?
                        if not any('pylink' in arg.lower() for arg in proc.cmdline()):
                            log.info("Ignoring stale PID %s from PID file %r: process command line %r is not us", pid, pidfile, proc.cmdline())
                            has_pid = False

        if has_pid:
            if args.rehash:
                os.kill(pid, signal.SIGUSR1)
                log.info('OK, rehashed PyLink instance %s (config %r)', pid, args.config)
                sys.exit()
            elif args.stop or args.restart:  # Handle --stop and --restart options
                os.kill(pid, signal.SIGTERM)

                log.info("Waiting for PyLink instance %s (config %r) to stop...", pid, args.config)
                while os.path.exists(pidfile):
                    # XXX: this is ugly, but os.waitpid() only works on non-child processes on Windows
                    time.sleep(0.2)
                log.info("Successfully killed PID %s for config %r.", pid, args.config)

                if args.stop:
                    sys.exit()
            else:
                log.error("PID file %r exists; aborting!", pidfile)

                if psutil is None:
                    log.error("If PyLink didn't shut down cleanly last time it ran, or you're upgrading "
                              "from PyLink < 1.1-dev, delete %r and start the server again.", pidfile)
                    if os.name == 'posix':
                        log.error("Alternatively, you can install psutil for Python 3 (pip3 install psutil), "
                                  "which will allow this launcher to detect stale PID files and ignore them.")
                sys.exit(1)

        elif args.stop or args.restart or args.rehash:  # XXX: also repetitive
            # --stop and --restart should take care of stale PIDs.
            if pid:
                world._should_remove_pid = True
                log.error('Cannot stop/rehash PyLink: no process with PID %s exists.', pid)
            else:
                log.error('Cannot stop/rehash PyLink: PID file %r does not exist.', pidfile)
            sys.exit(1)

        world._should_remove_pid = True

    log.info('PyLink %s starting...', __version__)

    world.daemon = args.daemonize
    if args.daemonize:
        if args.no_pid:
            print('ERROR: Combining --no-pid and --daemonize is not supported.')
            sys.exit(1)
        elif os.name != 'posix':
            print('ERROR: Daemonization is not supported outside POSIX systems.')
            sys.exit(1)
        else:
            log.info('Forking into the background.')
            log.removeHandler(world.console_handler)

            # Adapted from https://stackoverflow.com/questions/5975124/
            if os.fork():
                # Fork and exit the parent process.
                os._exit(0)

            os.setsid()  # Decouple from our lovely terminal
            if os.fork():
                # Fork again to prevent starting zombie apocalypses.
                os._exit(0)
    else:
        # For foreground sessions, set the terminal window title.
        # See https://bbs.archlinux.org/viewtopic.php?id=85567 &
        #     https://stackoverflow.com/questions/7387276/
        if os.name == 'nt':
            import ctypes
            ctypes.windll.kernel32.SetConsoleTitleW("PyLink %s" % __version__)
        elif os.name == 'posix':
            sys.stdout.write("\x1b]2;PyLink %s\x07" % __version__)

    # Write the PID file only after forking.
    with open(pidfile, 'w') as f:
        f.write(str(os.getpid()))

    # Load configured plugins
    to_load = conf.conf['plugins']
    utils.resetModuleDirs()

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
            try:
                proto = utils.getProtocolModule(protoname)

                # Create and connect the network.
                log.debug('Connecting to network %r', network)
                world.networkobjects[network] = classes.Irc(network, proto, conf.conf)
            except:
                log.exception('(%s) Failed to connect to network %r, skipping it...',
                              network, network)
                continue

    world.started.set()
    log.info("Loaded plugins: %s", ', '.join(sorted(world.plugins.keys())))

    from pylinkirc import coremods
    coremods.permissions.resetPermissions()  # Future note: this is moved to run on import in 2.0
