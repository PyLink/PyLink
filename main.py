#!/usr/bin/python3

import imp
import os
import socket
import time
import sys
from collections import defaultdict

from log import log
import conf
import classes

class Irc():
    def __init__(self, proto, conf):
        # Initialize some variables
        self.connected = False
        self.name = conf['server']['netname']
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

        self.serverdata = conf['server']
        self.sid = self.serverdata["sid"]
        self.botdata = conf['bot']
        self.proto = proto
        self.connect()

    def connect(self):
        ip = self.serverdata["ip"]
        port = self.serverdata["port"]
        log.info("Connecting to network %r on %s:%s", self.name, ip, port)
        self.socket = socket.socket()
        self.socket.connect((ip, port))
        self.proto.connect(self)
        self.loaded = []
        self.load_plugins()
        self.connected = True
        self.run()

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
                    log.debug("<- %s", line)
                    proto.handle_events(self, line)
            except socket.error as e:
                log.error('Received socket.error: %s, exiting.', str(e))
                break
        sys.exit(1)

    def send(self, data):
        data = data.encode("utf-8") + b"\n"
        log.debug("-> %s", data.decode("utf-8").strip("\n"))
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

    protoname = conf.conf['server']['protocol']
    protocols_folder = [os.path.join(os.getcwd(), 'protocols')]
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
        irc_obj = Irc(proto, conf.conf)
