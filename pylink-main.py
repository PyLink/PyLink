#!/usr/bin/python3

import yaml
import imp
import os
import threading
import socket
import multiprocessing
import time

print('PyLink starting...')

with open("config.yml", 'r') as f:
    conf = yaml.load(f)

# if conf['login']['password'] == 'changeme':
#     print("You have not set the login details correctly! Exiting...")

global networkobjects
networkobjects = {}

class irc(multiprocessing.Process):
    def __init__(self, network):
        multiprocessing.Process.__init__(self)
        self.authenticated = False
        self.connected = False
        self.socket = socket.socket()
        self.kill_received = False

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

    def run(self):
        while not self.kill_received:
            try:
                data = self.socket.recv(1024)
                if data:
                    buf = data.decode("utf-8")
                    for line in buf.split("\n"):
                        print("<- {}".format(line))
                        self.proto.handle_events(self, line)
            except socket.error:
                self.restart()
                break

    def send(self, data):
        data = data.encode("utf-8") + b"\n"
        print("-> {}".format(data.decode("utf-8").strip("\n")))
        self.socket.send(data)
    
    def restart(self):
        print('Disconnected... Restarting IRC Object for: %s' % network)
        time.sleep(1)
        del networkobjects[network]
        networkobjects[network] = irc(network)

    def relay(self, line):
        for network in networkobjects.values():
            self.proto.handle_events(self, line)

for network in conf['networks']:
    print('Creating IRC Object for: %s' % network)
    networkobjects[network] = irc(network)
    networkobjects[network].start()
