# relay.py: PyLink Relay plugin
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pickle
import sched
import threading
import time
import string

import utils
from log import log

dbname = "pylinkrelay.db"

def normalizeNick(irc, nick, separator="/"):
    orig_nick = nick
    protoname = irc.proto.__name__
    maxnicklen = irc.maxnicklen
    netname = irc.name
    if protoname == 'charybdis':
        # Charybdis doesn't allow / in usernames, and will quit with
        # a protocol violation if there is one.
        separator = separator.replace('/', '|')
        nick = nick.replace('/', '|')
    if nick.startswith(tuple(string.digits)):
        # On TS6 IRCd-s, nicks that start with 0-9 are only allowed if
        # they match the UID of the originating server. Otherwise, you'll
        # get nasty protocol violations!
        nick = '_' + nick
    tagnicks = True

    suffix = separator + netname
    nick = nick[:maxnicklen]
    # Maximum allowed length of a nickname.
    allowedlength = maxnicklen - len(suffix)
    # If a nick is too long, the real nick portion must be cut off, but the
    # /network suffix must remain the same.

    nick = nick[:allowedlength]
    nick += suffix
    while utils.nickToUid(irc, nick):
        # The nick we want exists? Darn, create another one then.
        # Increase the separator length by 1 if the user was already tagged,
        # but couldn't be created due to a nick conflict.
        # This can happen when someone steals a relay user's nick.
        new_sep = separator + separator[-1]
        nick = normalizeNick(irc, orig_nick, separator=new_sep)
    finalLength = len(nick)
    assert finalLength <= maxnicklen, "Normalized nick %r went over max " \
        "nick length (got: %s, allowed: %s!" % (nick, finalLength, maxnicklen)

    return nick

def loadDB():
    global db
    try:
        with open(dbname, "rb") as f:
            db = pickle.load(f)
    except (ValueError, IOError):
        log.exception("Relay: failed to load links database %s"
            ", creating a new one in memory...", dbname)
        db = {}

def exportDB(scheduler):
    scheduler.enter(60, 1, exportDB, argument=(scheduler,))
    log.debug("Relay: exporting links database to %s", dbname)
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

    loadDB()
    # HACK: we only want to schedule this once globally, because
    # exportDB will otherwise be called by every network that loads this
    # plugin.
    if 'relaydb' not in utils.schedulers:
        utils.schedulers['relaydb'] = scheduler = sched.scheduler()
        scheduler.enter(30, 1, exportDB, argument=(scheduler,))
        # Thread this because exportDB() queues itself as part of its
        # execution, in order to get a repeating loop.
        thread = threading.Thread(target=scheduler.run)
        thread.start()
    for chanpair in db:
        network, channel = chanpair
        ircobj = utils.networkobjects[network]
        ircobj.proto.joinClient(ircobj, irc.pseudoclient.uid, channel)
    for network, ircobj in utils.networkobjects.items():
        if ircobj.name != irc.name:
            irc.proto.spawnServer(irc, '%s.relay' % network)
