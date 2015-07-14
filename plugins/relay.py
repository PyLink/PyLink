# relay.py: PyLink Relay plugin
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pickle
import sched
import threading
import time
import string
from collections import defaultdict

import utils
from log import log

dbname = "pylinkrelay.db"
relayusers = defaultdict(dict)
relayservers = defaultdict(dict)

def normalizeNick(irc, netname, nick, separator="/"):
    orig_nick = nick
    protoname = irc.proto.__name__
    maxnicklen = irc.maxnicklen
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
        nick = normalizeNick(irc, netname, orig_nick, separator=new_sep)
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
    scheduler.enter(30, 1, exportDB, argument=(scheduler,))
    log.debug("Relay: exporting links database to %s", dbname)
    with open(dbname, 'wb') as f:
        pickle.dump(db, f, protocol=4)

def getPrefixModes(irc, remoteirc, channel, user):
    modes = ''
    for pmode in ('owner', 'admin', 'op', 'halfop', 'voice'):
        if pmode not in remoteirc.cmodes:  # Mode not supported by IRCd
            continue
        if user in irc.channels[channel].prefixmodes[pmode+'s']:
            modes += remoteirc.cmodes[pmode]
    return modes

def findRelay(chanpair):
    if chanpair in db:  # This chanpair is a shared channel; others link to it
        return chanpair
    # This chanpair is linked *to* a remote channel
    for name, dbentry in db.items():
        if chanpair in dbentry['links']:
            return name

def findRemoteChan(remotenetname, query):
    chanpair = findRelay(query)
    if chanpair is None:
        return
    if chanpair[0] == remotenetname:
        return chanpair[1]
    else:
        for link in db[chanpair]['links']:
            if link[0] == remotenetname:
                return link[1]

def initializeChannel(irc, channel):
    # We're initializing a relay that already exists. This can be done at
    # ENDBURST, or on the LINK command.
    irc.proto.joinClient(irc, irc.pseudoclient.uid, channel)
    c = irc.channels[channel]
    relay = findRelay((irc.name, channel))
    log.debug('(%s) initializeChannel being called on %s', irc.name, channel)
    log.debug('(%s) initializeChannel: relay pair found to be %s', irc.name, relay)
    if relay:
        all_links = db[relay]['links'].copy()
        all_links.update((relay,))
        log.debug('(%s) initializeChannel: all_links: %s', irc.name, all_links)
        for link in all_links:
            remotenet, remotechan = link
            if remotenet == irc.name:
                continue
            remoteirc = utils.networkobjects[remotenet]
            rc = remoteirc.channels[remotechan]
            for user in remoteirc.channels[remotechan].users:
                if not utils.isInternalClient(remoteirc, user):
                    log.debug('(%s) initializeChannel: should be joining %s/%s to %s', irc.name, user, remotenet, channel)
                    remoteuser = relayusers[(remotenet, user)][irc.name]
                    irc.proto.joinClient(irc, remoteuser, channel)

    log.debug('(%s) initializeChannel: relay users: %s', irc.name, c.users)
    relayJoins(irc, channel, c.users, c.ts, c.modes)

def handle_join(irc, numeric, command, args):
    channel = args['channel']
    if not findRelay((irc.name, channel)):
        # No relay here, return.
        return
    modes = args['modes']
    ts = args['ts']
    users = set(args['users'])
    # users.update(irc.channels[channel].users)
    relayJoins(irc, channel, users, ts, modes)
utils.add_hook(handle_join, 'JOIN')

def handle_quit(irc, numeric, command, args):
    ouruser = numeric
    for netname, user in relayusers[(irc.name, numeric)].items():
        remoteirc = utils.networkobjects[netname]
        remoteirc.proto.quitClient(remoteirc, user, args['text'])
    del relayusers[(irc.name, ouruser)]
utils.add_hook(handle_quit, 'QUIT')

def handle_nick(irc, numeric, command, args):
    for netname, user in relayusers[(irc.name, numeric)].items():
        remoteirc = utils.networkobjects[netname]
        newnick = normalizeNick(remoteirc, irc.name, args['newnick'])
        remoteirc.proto.nickClient(remoteirc, user, newnick)
utils.add_hook(handle_nick, 'NICK')

def handle_part(irc, numeric, command, args):
    channel = args['channel']
    text = args['text']
    for netname, user in relayusers[(irc.name, numeric)].items():
        remotechan = findRemoteChan(netname, (irc.name, channel))
        remoteirc = utils.networkobjects[netname]
        remoteirc.proto.partClient(remoteirc, user, remotechan, text)
utils.add_hook(handle_part, 'PART')

def relayJoins(irc, channel, users, ts, modes):
    queued_users = []
    for user in users:
        try:
            if irc.users[user].remote:
                # Is the .remote attribute set? If so, don't relay already
                # relayed clients; that'll trigger an endless loop!
                continue
        except AttributeError:  # Nope, it isn't.
            pass
        if user == irc.pseudoclient.uid:
            # We don't need to clone the PyLink pseudoclient... That's
            # meaningless.
            continue
        userobj = irc.users[user]
        userpair_index = relayusers.get((irc.name, user))
        ident = userobj.ident
        host = userobj.host
        realname = userobj.realname
        log.debug('Okay, spawning %s/%s everywhere', user, irc.name)
        for name, remoteirc in utils.networkobjects.items():
            if name == irc.name:
                # Don't relay things to their source network...
                continue
            try:  # Spawn our pseudoserver first
                relayservers[remoteirc.name][irc.name] = sid = \
                    remoteirc.proto.spawnServer(remoteirc, '%s.relay' % irc.name,
                                                endburst=False)
                # We want to wait a little bit for the remote IRCd to send their users,
                # so we can join them as part of a burst on remote networks.
                # Because IRC is asynchronous, we can't really control how long
                # this will take.
                endburst_timer = threading.Timer(0.5, remoteirc.proto.endburstServer,
                                                 args=(remoteirc, sid))
                log.debug('(%s) Setting timer to BURST %s', remoteirc.name, sid)
                endburst_timer.start()
            except ValueError:
                # Server already exists (raised by the protocol module).
                sid = relayservers[remoteirc.name][irc.name]
            log.debug('(%s) Have we bursted %s yet? %s', remoteirc.name, sid,
                      remoteirc.servers[sid].has_bursted)
            nick = normalizeNick(remoteirc, irc.name, userobj.nick)
            # If the user (stored here as {(netname, UID):
            # {network1: UID1, network2: UID2}}) exists, don't spawn it
            # again!
            u = None
            if userpair_index is not None:
                u = userpair_index.get(remoteirc.name)
            if u is None:  # .get() returns None if not found
                u = remoteirc.proto.spawnClient(remoteirc, nick, ident=ident,
                                                host=host, realname=realname,
                                                server=sid).uid
                remoteirc.users[u].remote = irc.name
            relayusers[(irc.name, userobj.uid)][remoteirc.name] = u
            remoteirc.users[u].remote = irc.name
            remotechan = findRemoteChan(remoteirc.name, (irc.name, channel))
            if remotechan is None:
                continue
            if not remoteirc.servers[sid].has_bursted:
                # TODO: join users in batches with SJOIN, not one by one.
                prefix = getPrefixModes(irc, remoteirc, channel, user)
                remoteirc.proto.sjoinServer(remoteirc, sid, remotechan, [(prefix, u)], ts=ts)
            else:
                remoteirc.proto.joinClient(remoteirc, u, remotechan)

def removeChannel(irc, channel):
    if channel not in map(str.lower, irc.serverdata['channels']):
        irc.proto.partClient(irc, irc.pseudoclient.uid, channel)

def relay(homeirc, func, args):
    """<source IRC network object> <function name> <args>

    Relays a call to <function name>(<args>) to every IRC object's protocol
    module except the source IRC network's."""
    for name, irc in utils.networkobjects.items():
        if name == homeirc.name:
            continue
        f = getattr(irc.proto, func)
        f(*args)

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
    initializeChannel(irc, channel)
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
        removeChannel(irc, channel)
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
        initializeChannel(irc, localchan)
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
                        removeChannel(utils.networkobjects[remotenet], link[1])
    else:
        entry['links'].remove((irc.name, channel))
        removeChannel(irc, channel)
    utils.msg(irc, source, 'Done.')

def initializeAll(irc):
    utils.started.wait()
    for chanpair, entrydata in db.items():
        network, channel = chanpair
        initializeChannel(irc, channel)
        for link in entrydata['links']:
            network, channel = link
            initializeChannel(irc, channel)
def main():
    loadDB()
    utils.schedulers['relaydb'] = scheduler = sched.scheduler()
    scheduler.enter(30, 1, exportDB, argument=(scheduler,))
    # Thread this because exportDB() queues itself as part of its
    # execution, in order to get a repeating loop.
    thread = threading.Thread(target=scheduler.run)
    thread.daemon = True
    thread.start()
    '''
    for ircobj in utils.networkobjects.values():
        initializeAll(irc)

        # Same goes for all the other initialization stuff; we only
        # want it to happen once.
        for network, ircobj in utils.networkobjects.items():
            if ircobj.name != irc.name:
                irc.proto.spawnServer(irc, '%s.relay' % network)
    '''

def handle_endburst(irc, numeric, command, args):
    thread = threading.Thread(target=initializeAll, args=(irc,))
    thread.start()
utils.add_hook(handle_endburst, "ENDBURST")
