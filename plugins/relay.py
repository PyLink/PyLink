# relay.py: PyLink Relay plugin
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pickle
import sched
import threading
import time

import utils
from log import log

dbname = "pylinkrelay.db"

def loadDB():
    global db
    try:
        with open(dbname, "rb") as f:
            db = pickle.load(f)
    except (ValueError, IOError):
        log.exception("Relay: failed to load links database %s"
            ", creating a new one in memory...", dbname)
        db = {}

def exportDB():
    scheduler.enter(10, 1, exportDB)
    log.debug("Relay: exporting links database to "+dbname)
    with open(dbname, 'wb') as f:
        pickle.dump(db, f, protocol=4)

@utils.add_cmd
def create(irc, source, args):
    """<channel>

    Creates the channel <channel> over the relay."""
    try:
        channel = args[0].lower()
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 1: channel.")
        return 
    if not utils.isChannel(channel):
        utils.msg(irc, source, 'Error: invalid channel %r.' % channel)
        return
    if source not in irc.channels[channel]:
        utils.msg(irc, source, 'Error: you must be in %r to complete this operation.' % channel)
        return
    if not utils.isOper(irc, source):
        utils.msg(irc, source, 'Error: you must be opered in order to complete this operation.' % channel)
        return
    db[(irc.name, channel)] = {'claim': [irc.name], 'links': [], 'blocked_nets': []}
    irc.proto.joinClient(irc, irc.pseudoclient.uid, channel)
    utils.msg(irc, source, 'Done.')

@utils.add_cmd
def destroy(irc, source, args):
    """<channel>

    Destroys the channel <channel> over the relay."""
    try:
        channel = args[0].lower()
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 1: channel.")
        return 
    if not utils.isChannel(channel):
        utils.msg(irc, source, 'Error: invalid channel %r.' % channel)
        return
    if not utils.isOper(irc, source):
        utils.msg(irc, source, 'Error: you must be opered in order to complete this operation.' % channel)
        return

    if channel in db:
        del db[channel]
        if channel not in map(str.lower, irc.serverdata['channels']):
            irc.proto.partClient(irc, irc.pseudoclient.uid, channel)
        utils.msg(irc, source, 'Done.')
    else:
        utils.msg(irc, source, 'Error: no such relay %r exists.' % channel)

def main(irc):
    global scheduler
    scheduler = sched.scheduler()
    loadDB()
    scheduler.enter(60, 1, exportDB)
    thread = threading.Thread(target=scheduler.run)
    thread.start()
    for chanpair in db:
        network, channel = chanpair
        ircobj = utils.networkobjects[network]
        ircobj.proto.joinClient(ircobj, irc.pseudoclient.uid, channel)
    for network, ircobj in utils.networkobjects.items():
        if ircobj.name != irc.name:
            irc.proto.spawnServer(irc, '%s.relay' % network)
