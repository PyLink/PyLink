#!/usr/bin/python3

import imp
import os
import socket
import time
import sys
from collections import defaultdict
import threading

from log import log
import conf
import classes
import utils

class Irc():
    def __init__(self, netname, proto, conf):
        # Initialize some variables
        self.connected = threading.Event()
        self.name = netname.lower()
        self.conf = conf
        # Server, channel, and user indexes to be populated by our protocol module
        self.servers = {}
        self.users = {}
        self.channels = defaultdict(classes.IrcChannel)
        # Sets flags such as whether to use halfops, etc. The default RFC1459
        # modes are implied.
        self.cmodes = {'op': 'o', 'secret': 's', 'private': 'p',
                       'noextmsg': 'n', 'moderated': 'm', 'inviteonly': 'i',
                       'topiclock': 't', 'limit': 'l', 'ban': 'b',
                       'voice': 'v', 'key': 'k',
                       # Type A, B, and C modes
                       '*A': 'b',
                       '*B': 'k',
                       '*C': 'l',
                       '*D': 'imnpstr'}
        self.umodes = {'invisible': 'i', 'snomask': 's', 'wallops': 'w',
                       'oper': 'o',
                       '*A': '', '*B': '', '*C': 's', '*D': 'iow'}
        # This nicklen value is only a default, and SHOULD be set by the
        # protocol module as soon as the relevant capability information is
        # received from the uplink. Plugins that depend on maxnicklen being
        # set MUST call "irc.connected.wait()", which blocks until the
        # capability information is received. This handling of irc.connected
        # is also dependent on the protocol module.
        self.maxnicklen = 30
        self.prefixmodes = 'ov'

        self.serverdata = conf['servers'][netname]
        self.sid = self.serverdata["sid"]
        self.botdata = conf['bot']
        self.proto = proto
        self.connection_thread = threading.Thread(target = self.connect)
        self.connection_thread.start()

    def connect(self):
        ip = self.serverdata["ip"]
        port = self.serverdata["port"]
        log.info("Connecting to network %r on %s:%s", self.name, ip, port)
        try:
            # Initial connection timeout is a lot smaller than the timeout after
            # we've connected; this is intentional.
            self.socket = socket.create_connection((ip, port), timeout=10)
            self.socket.setblocking(0)
            self.socket.settimeout(180)
            self.proto.connect(self)
        except (socket.error, classes.ProtocolError, ConnectionError) as e:
            log.warning('(%s) Failed to connect to IRC: %s: %s',
                        self.name, type(e).__name__, str(e))
            self.disconnect()
        else:
            self.run()

    def disconnect(self):
        self.connected.clear()
        try:
            self.socket.close()
        except:  # Socket timed out during creation; ignore
            pass
        autoconnect = self.serverdata.get('autoconnect')
        if autoconnect is not None and autoconnect >= 0:
            log.info('(%s) Going to auto-reconnect in %s seconds.', self.name, autoconnect)
            time.sleep(autoconnect)
            self.connect()

    def run(self):
        buf = ""
        data = ""
        while True:
            try:
                data = self.socket.recv(2048).decode("utf-8")
                buf += data
                if not data:
                    break
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    log.debug("(%s) <- %s", self.name, line)
                    proto.handle_events(self, line)
            except (socket.error, classes.ProtocolError, ConnectionError) as e:
                log.warning('(%s) Disconnected from IRC: %s: %s',
                           self.name, type(e).__name__, str(e))
                break
        self.disconnect()

    def send(self, data):
        # Safeguard against newlines in input!! Otherwise, each line gets
        # treated as a separate command, which is particularly nasty.
        data = data.replace('\n', ' ')
        data = data.encode("utf-8") + b"\n"
        log.debug("(%s) -> %s", self.name, data.decode("utf-8").strip("\n"))
        try:
            self.socket.send(data)
        except (socket.error, classes.ProtocolError, ConnectionError) as e:
            log.warning('(%s) Disconnected from IRC: %s: %s',
                        self.name, type(e).__name__, str(e))
            self.disconnect()

if __name__ == '__main__':
    log.info('PyLink starting...')
    if conf.conf['login']['password'] == 'changeme':
        log.critical("You have not set the login details correctly! Exiting...")
        sys.exit(2)
    protocols_folder = [os.path.join(os.getcwd(), 'protocols')]

    # Import plugins first globally, because they can listen for events
    # that happen before the connection phase.
    to_load = conf.conf['plugins']
    plugins_folder = [os.path.join(os.getcwd(), 'plugins')]
    # Here, we override the module lookup and import the plugins
    # dynamically depending on which were configured.
    for plugin in to_load:
        try:
            moduleinfo = imp.find_module(plugin, plugins_folder)
            pl = imp.load_source(plugin, moduleinfo[1])
            utils.plugins.append(pl)
        except ImportError as e:
            if str(e).startswith('No module named'):
                log.error('Failed to load plugin %r: the plugin could not be found.', plugin)
            else:
                log.error('Failed to load plugin %r: import error %s', plugin, str(e))
        else:
            if hasattr(pl, 'main'):
                log.debug('Calling main() function of plugin %r', pl)
                pl.main()

    for network in conf.conf['servers']:
        protoname = conf.conf['servers'][network]['protocol']
        try:
            moduleinfo = imp.find_module(protoname, protocols_folder)
            proto = imp.load_source(protoname, moduleinfo[1])
        except ImportError as e:
            if str(e).startswith('No module named'):
                log.critical('Failed to load protocol module %r: the file could not be found.', protoname)
            else:
                log.critical('Failed to load protocol module: import error %s', protoname, str(e))
            sys.exit(2)
        else:
            utils.networkobjects[network] = Irc(network, proto, conf.conf)
    utils.started.set()
    log.info("loaded plugins: %s", utils.plugins)

