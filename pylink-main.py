#!/usr/bin/python3

import yaml
import imp
import os
import importlib
import sys

print('PyLink starting...')

with open("config.yml", 'r') as f:
    conf = yaml.load(f)

# if conf['login']['password'] == 'changeme':
#     print("You have not set the login details correctly! Exiting...")

global networkobjects
networkobjects = {}

class irc:
    def __init__(self, network):
        self.netname = network
        self.networkdata = conf['networks'][network]
        protoname = self.networkdata['protocol']
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
        self.connect()
    
    def connect(self):
        self.proto.connect(self.netname, self.networkdata)

for network in conf['networks']:
    print('Creating IRC Object for: %s' % network)
    networkobjects[network] = irc(network)
    
    # mod = sys.modules[plugin]
    

