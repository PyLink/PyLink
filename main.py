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

class IrcUser():
    def __init__(self, nick, timestamp, data={'uid': None}):
        self.nick = nick
        self.data = data
        self.timestamp = timestamp

class Irc():
    def __init__(self):
        # Initialize some variables
        self.socket = socket.socket()
        self.connected = False
        self.users = {}
        self.name = conf['server']['netname']

        self.serverdata = conf['server']
        ip = self.serverdata["ip"]
        port = self.serverdata["port"]
        self.sid = self.serverdata["sid"]
        print("Connecting to network %r on %s:%s" % (self.name, ip, port))

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
        self.connected = True
        self.run()

    def run(self):
        while self.connected:
            try:
                data = self.socket.recv(1024)
                if data:
                    buf = data.decode("utf-8")
                    for line in buf.split("\n"):
                        print("<- {}".format(line))
                        self.proto.handle_events(self, line)
            except socket.error:
                print('Received socket.error: %s, exiting.' % str(e))
                self.connected = False

    def send(self, data):
        data = data.encode("utf-8") + b"\n"
        print("-> {}".format(data.decode("utf-8").strip("\n")))
        self.socket.send(data)

irc_obj = Irc()
