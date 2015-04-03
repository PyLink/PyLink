#!/usr/bin/python3

import yaml
import imp
import os
import threading
import socket
import asyncio

print('PyLink starting...')

with open("config.yml", 'r') as f:
    conf = yaml.load(f)

# if conf['login']['password'] == 'changeme':
#     print("You have not set the login details correctly! Exiting...")

global networkobjects
networkobjects = {}

class irc(asyncio.Protocol):
    def __init__(self, network, loop):
        asyncio.Protocol.__init__(self)
        self.authenticated = False
        self.connected = False
        self.socket = socket.socket()
        self.loop = loop

        self.serverdata = conf['networks'][network]
        ip = self.serverdata["ip"]
        port = self.serverdata["port"]
        self.sid = self.serverdata["sid"]
        print("[+] New thread started for %s:%s" % (ip, port))

        self.name = network
        protoname = self.serverdata['protocol']
        # With the introduction of Python 3, relative imports are no longer
        # allowed from normal applications ran from the command line. Instead,
        # these imported libraries must be installed as a package using distutils
        # or something similar.
        #
        # But I don't want that! Where PyLink is at right now (a total WIP), it is
        # a lot more convenient to run the program directly from the source folder.
        protocols_folder = [os.path.join(os.getcwd(), 'protocols')]
        # Here, we override the module lookup and import the protocol module
        # dynamically depending on which module was configured.
        moduleinfo = imp.find_module(protoname, protocols_folder)
        self.proto = imp.load_source(protoname, moduleinfo[1])
        self.socket = socket.socket()
        self.socket.connect((ip, port))
        self.proto.connect(self)

    # def collect_incoming_data(self, data):

    @asyncio.coroutine
    def handle_read(self):
        data = self.socket.recv(2048)
        buf = data.decode("utf-8")
        for line in buf.split("\n"):
            print("<- {}".format(line))
            self.proto.handle_events(self, line)

    def send(self, data):
        data = data.encode("utf-8") + b"\n"
        print("-> {}".format(data.decode("utf-8").strip("\n")))
        self.socket.send(data)

for network in conf['networks']:
    print('Creating IRC Object for: %s' % network)
    networkobjects[network] = irc(network)
    loop = asyncio.get_event_loop()
    loop.run_forever(networkobjects[network].handle_read())
