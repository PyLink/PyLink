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
import coreplugin

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
        # Uplink SID (filled in by protocol module)
        self.uplink = None

        self.serverdata = conf['servers'][netname]
        self.sid = self.serverdata["sid"]
        self.botdata = conf['bot']
        self.proto = proto
        self.pingfreq = self.serverdata.get('pingfreq') or 10
        self.pingtimeout = self.pingfreq * 2

        self.connection_thread = threading.Thread(target = self.connect)
        self.connection_thread.start()
        self.pingTimer = None
        self.lastping = time.time()

    def connect(self):
        ip = self.serverdata["ip"]
        port = self.serverdata["port"]
        while True:
            log.info("Connecting to network %r on %s:%s", self.name, ip, port)
            try:
                # Initial connection timeout is a lot smaller than the timeout after
                # we've connected; this is intentional.
                self.socket = socket.create_connection((ip, port), timeout=1)
                self.socket.setblocking(0)
                self.socket.settimeout(self.pingtimeout)
                self.proto.connect(self)
                self.spawnMain()
                self.schedulePing()
                self.run()
            except (socket.error, classes.ProtocolError, ConnectionError) as e:
                log.warning('(%s) Disconnected from IRC: %s: %s',
                            self.name, type(e).__name__, str(e))
                self.disconnect()
            autoconnect = self.serverdata.get('autoconnect')
            log.debug('(%s) Autoconnect delay set to %s seconds.', self.name, autoconnect)
            if autoconnect is not None and autoconnect >= 0:
                log.info('(%s) Going to auto-reconnect in %s seconds.', self.name, autoconnect)
                time.sleep(autoconnect)
            else:
                return


    def disconnect(self):
        log.debug('(%s) Canceling pingTimer at %s due to disconnect() call', self.name, time.time())
        self.connected.clear()
        try:
            self.socket.close()
            self.pingTimer.cancel()
        except:  # Socket timed out during creation; ignore
            pass

    def run(self):
        buf = ""
        data = ""
        while (time.time() - self.lastping) < self.pingtimeout:
            log.debug('(%s) time_since_last_ping: %s', self.name, (time.time() - self.lastping))
            log.debug('(%s) self.pingtimeout: %s', self.name, self.pingtimeout)
            data = self.socket.recv(2048).decode("utf-8")
            buf += data
            if not data:
                break
            while '\n' in buf:
                line, buf = buf.split('\n', 1)
                log.debug("(%s) <- %s", self.name, line)
                proto.handle_events(self, line)

    def send(self, data):
        # Safeguard against newlines in input!! Otherwise, each line gets
        # treated as a separate command, which is particularly nasty.
        data = data.replace('\n', ' ')
        data = data.encode("utf-8") + b"\n"
        log.debug("(%s) -> %s", self.name, data.decode("utf-8").strip("\n"))
        self.socket.send(data)

    def schedulePing(self):
        self.proto.pingServer(self)
        self.pingTimer = threading.Timer(self.pingfreq, self.schedulePing)
        self.pingTimer.daemon = True
        self.pingTimer.start()
        log.debug('(%s) Ping scheduled at %s', self.name, time.time())

    def spawnMain(self):
        nick = self.botdata.get('nick') or 'PyLink'
        ident = self.botdata.get('ident') or 'pylink'
        host = self.serverdata["hostname"]
        self.pseudoclient = self.proto.spawnClient(self, nick, ident, host, modes={("o", None)})
        for chan in self.serverdata['channels']:
            self.proto.joinClient(self, self.pseudoclient.uid, chan)

if __name__ == '__main__':
    log.info('PyLink starting...')
    if conf.conf['login']['password'] == 'changeme':
        log.critical("You have not set the login details correctly! Exiting...")
        sys.exit(2)
    protocols_folder = [os.path.join(os.getcwd(), 'protocols')]

    # Import plugins first globally, because they can listen for events
    # that happen before the connection phase.
    utils.plugins.append(coreplugin)
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

