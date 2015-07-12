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
        self.connected = False
        self.name = netname
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
        self.maxnicklen = 30
        self.prefixmodes = 'ov'

        self.serverdata = conf['servers'][netname]
        self.sid = self.serverdata["sid"]
        self.botdata = conf['bot']
        self.proto = proto
        self.connect()

    def connect(self):
        ip = self.serverdata["ip"]
        port = self.serverdata["port"]
        log.info("Connecting to network %r on %s:%s", self.name, ip, port)
        self.socket = socket.socket()
        self.socket.setblocking(0)
        self.socket.settimeout(180)
        self.socket.connect((ip, port))
        self.proto.connect(self)
        self.loaded = []
        reading_thread = threading.Thread(target = self.run)
        self.connected = True
        reading_thread.start()

    def disconnect(self):
        self.connected = False
        self.socket.close()

    def run(self):
        buf = ""
        data = ""
        while self.connected:
            try:
                data = self.socket.recv(2048).decode("utf-8")
                buf += data
                if not data:
                    break
                while '\n' in buf:
                    line, buf = buf.split('\n', 1)
                    log.debug("(%s) <- %s", self.name, line)
                    proto.handle_events(self, line)
            except (socket.error, classes.ProtocolError) as e:
                log.error('Disconnected from network %r: %s: %s, exiting.',
                          self.name, type(e).__name__, str(e))
                self.disconnect()

    def send(self, data):
        # Safeguard against newlines in input!! Otherwise, each line gets
        # treated as a separate command, which is particularly nasty.
        data = data.replace('\n', ' ')
        data = data.encode("utf-8") + b"\n"
        log.debug("(%s) -> %s", self.name, data.decode("utf-8").strip("\n"))
        self.socket.send(data)

    def load_plugins(self):
        to_load = conf.conf['plugins']
        plugins_folder = [os.path.join(os.getcwd(), 'plugins')]
        # Here, we override the module lookup and import the plugins
        # dynamically depending on which were configured.
        for plugin in to_load:
            try:
                moduleinfo = imp.find_module(plugin, plugins_folder)
                self.loaded.append(imp.load_source(plugin, moduleinfo[1]))
            except ImportError as e:
                if str(e).startswith('No module named'):
                    log.error('Failed to load plugin %r: the plugin could not be found.', plugin)
                else:
                    log.error('Failed to load plugin %r: import error %s', plugin, str(e))
        log.info("loaded plugins: %s", self.loaded)

if __name__ == '__main__':
    log.info('PyLink starting...')
    if conf.conf['login']['password'] == 'changeme':
        log.critical("You have not set the login details correctly! Exiting...")
        sys.exit(2)
    protocols_folder = [os.path.join(os.getcwd(), 'protocols')]
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
            utils.networkobjects[network] = irc = Irc(network, proto, conf.conf)
            irc.load_plugins()
