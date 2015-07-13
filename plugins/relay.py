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
    if source not in irc.channels[channel].users:
        utils.msg(irc, source, 'Error: you must be in %r to complete this operation.' % channel)
        return
    if not utils.isOper(irc, source):
        utils.msg(irc, source, 'Error: you must be opered in order to complete this operation.')
        return
    db[(irc.name, channel)] = {'claim': [irc.name], 'links': set(), 'blocked_nets': set()}
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
        utils.msg(irc, source, 'Error: you must be opered in order to complete this operation.')
        return

    if (irc.name, channel) in db:
        del db[(irc.name, channel)]
        if channel not in map(str.lower, irc.serverdata['channels']):
            irc.proto.partClient(irc, irc.pseudoclient.uid, channel)
        utils.msg(irc, source, 'Done.')
    else:
        utils.msg(irc, source, 'Error: no such relay %r exists.' % channel)
        return

@utils.add_cmd
def link(irc, source, args):
    """<remotenet> <channel> <local channel>

    Links channel <channel> on <remotenet> over the relay to <local channel>.
    If <local channel> is not specified, it defaults to the same name as
    <channel>."""
    try:
        channel = args[1].lower()
        remotenet = args[0].lower()
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 2-3: remote netname, channel, local channel name (optional).")
        return
    try:
        localchan = args[2].lower()
    except IndexError:
        localchan = channel
    for c in (channel, localchan):
        if not utils.isChannel(c):
            utils.msg(irc, source, 'Error: invalid channel %r.' % c)
            return
    if source not in irc.channels[localchan].users:
        utils.msg(irc, source, 'Error: you must be in %r to complete this operation.' % localchan)
        return
    if not utils.isOper(irc, source):
        utils.msg(irc, source, 'Error: you must be opered in order to complete this operation.')
        return
    if remotenet not in utils.networkobjects:
        utils.msg(irc, source, 'Error: no network named %r exists.' % remotenet)
        return
    if (irc.name, localchan) in db:
        utils.msg(irc, source, 'Error: channel %r is already part of a relay.' % localchan)
        return
    for dbentry in db.values():
        if (irc.name, localchan) in dbentry['links']:
            utils.msg(irc, source, 'Error: channel %r is already part of a relay.' % localchan)
            return
    try:
        entry = db[(remotenet, channel)]
    except KeyError:
        utils.msg(irc, source, 'Error: no such relay %r exists.' % channel)
        return
    else:
        entry['links'].add((irc.name, localchan))
        utils.msg(irc, source, 'Done.')

@utils.add_cmd
def delink(irc, source, args):
    """<local channel> [<network>]

    Delinks channel <local channel>. <network> must and can only be specified
    if you are on the host network for <local channel>, and allows you to
    pick which network to delink. To remove all networks from a relay, use the
    'destroy' command instead."""
    try:
        channel = args[0].lower()
    except IndexError:
        utils.msg(irc, source, "Error: not enough arguments. Needs 1-2: channel, remote netname (optional).")
        return
    try:
        remotenet = args[1].lower()
    except IndexError:
        remotenet = None
    if not utils.isOper(irc, source):
        utils.msg(irc, source, 'Error: you must be opered in order to complete this operation.')
        return
    if not utils.isChannel(channel):
        utils.msg(irc, source, 'Error: invalid channel %r.' % channel)
        return
    for dbentry in db.values():
        if (irc.name, channel) in dbentry['links']:
            entry = dbentry
            break
    if (irc.name, channel) in db:  # We own this channel
        if remotenet is None:
            utils.msg(irc, source, "Error: you must select a network to delink, or use the 'destroy' command no remove this relay entirely.")
            return
        else:
            for entry in db.values():
                for link in entry['links'].copy():
                    if link[0] == remotenet:
                        entry['links'].remove(link)
    else:
        entry['links'].remove((irc.name, channel))
    utils.msg(irc, source, 'Done.')

def relay(homeirc, func, args):
    """<source IRC network object> <function name> <args>

    Relays a call to <function name>(<args>) to every IRC object's protocol
    module except the source IRC network's."""
    for name, irc in utils.networkobjects.items():
        if name == homeirc.name:
            continue
        f = getattr(irc.proto, func)
        f(*args)

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
