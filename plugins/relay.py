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

def getRemoteUser(irc, remoteirc, user):
    # If the user (stored here as {(netname, UID):
    # {network1: UID1, network2: UID2}}) exists, don't spawn it
    # again!
    try:
        u = relayusers[(irc.name, user)][remoteirc.name]
    except KeyError:
        userobj = irc.users[user]
        nick = normalizeNick(remoteirc, irc.name, userobj.nick)
        ident = userobj.ident
        host = userobj.host
        realname = userobj.realname
        u = remoteirc.proto.spawnClient(remoteirc, nick, ident=ident,
                                        host=host, realname=realname).uid
        remoteirc.users[u].remote = irc.name
    relayusers[(irc.name, user)][remoteirc.name] = u
    remoteirc.users[u].remote = irc.name
    return u

def findRelay(chanpair):
    if chanpair in db:  # This chanpair is a shared channel; others link to it
        return chanpair
    # This chanpair is linked *to* a remote channel
    for name, dbentry in db.items():
        if chanpair in dbentry['links']:
            return name

def findRemoteChan(irc, remoteirc, channel):
    query = (irc.name, channel)
    remotenetname = remoteirc.name
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
    queued_users = []
    if relay:
        all_links = db[relay]['links'].copy()
        all_links.update((relay,))
        log.debug('(%s) initializeChannel: all_links: %s', irc.name, all_links)
        for link in all_links:
            modes = []
            remotenet, remotechan = link
            if remotenet == irc.name:
                continue
            remoteirc = utils.networkobjects[remotenet]
            rc = remoteirc.channels[remotechan]
            for user in remoteirc.channels[remotechan].users:
                # Don't spawn our pseudoclients again.
                if not utils.isInternalClient(remoteirc, user):
                    log.debug('(%s) initializeChannel: should be joining %s/%s to %s', irc.name, user, remotenet, channel)
                    remoteuser = getRemoteUser(remoteirc, irc, user)
                    userpair = (getPrefixModes(remoteirc, irc, remotechan, user), remoteuser)
                    log.debug('(%s) initializeChannel: adding %s to queued_users for %s', irc.name, userpair, channel)
                    queued_users.append(userpair)
            if queued_users:
                irc.proto.sjoinServer(irc, irc.sid, channel, queued_users, ts=rc.ts)

    log.debug('(%s) initializeChannel: joining our users: %s', irc.name, c.users)
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
        remoteirc = utils.networkobjects[netname]
        remotechan = findRemoteChan(irc, remoteirc, channel)
        remoteirc.proto.partClient(remoteirc, user, remotechan, text)
utils.add_hook(handle_part, 'PART')

def handle_kick(irc, source, command, args):
    channel = args['channel']
    target = args['target']
    text = args['text']
    kicker = source
    kicker_modes = getPrefixModes(irc, irc, channel, kicker)
    relay = findRelay((irc.name, channel))
    if relay is None:
        return
    for name, remoteirc in utils.networkobjects.items():
        if irc.name == name:
            continue
        remotechan = findRemoteChan(irc, remoteirc, channel)
        log.debug('(%s) Relay kick: remotechan for %s on %s is %s', irc.name, channel, name, remotechan)
        if remotechan is None:
            continue
        real_kicker = getRemoteUser(irc, remoteirc, kicker)
        log.debug('(%s) Relay kick: real kicker for %s on %s is %s', irc.name, kicker, name, real_kicker)
        if not utils.isInternalClient(irc, target):
            log.debug('(%s) Relay kick: target %s is NOT an internal client', irc.name, target)
            # Both the target and kicker are external clients; i.e.
            # they originate from the same network. We shouldn't have
            # to process this any further, because the uplink IRCd
            # will handle this appropriately, and we'll just follow.
            real_target = getRemoteUser(irc, remoteirc, target)
            log.debug('(%s) Relay kick: real target for %s is %s', irc.name, target, real_target)
            remoteirc.proto.kickClient(remoteirc, real_kicker,
                                       remotechan, real_target, args['text'])
        else:
            log.debug('(%s) Relay kick: target %s is an internal client, going to look up the real user', irc.name, target)
            # Our target is an internal client, which means someone
            # is kicking a remote user over the relay.
            # We have to find the real target for the KICK. This is like
            # findRemoteUser, but in reverse.
            # First, iterate over everyone!
            for k, v in relayusers.items():
                log.debug('(%s) Relay kick: processing %s, %s in relayusers', irc.name, k, v)
                if k[0] == irc.name:
                    # We don't need to do anything if the target users is on
                    # the same network as us.
                    log.debug('(%s) Relay kick: skipping %s since the target network matches the source network.', irc.name, k)
                    continue
                if v[irc.name] == target:
                    # If the stored pseudoclient UID for the kicked user on
                    # this network matches the target we have, set that user
                    # as the one we're kicking! It's a handful, but remember
                    # we're mapping (home network, UID) pairs to their
                    # respective relay pseudoclients on other networks.
                    real_target = k[1]
                    log.debug('(%s) Relay kick: found %s to correspond to %s.', irc.name, v, k)
                    break
            log.debug('(%s) Relay kick: kicker_modes are %r', irc.name, kicker_modes)
            if irc.name not in db[relay]['links'] and not \
                    any([mode in kicker_modes for mode in ('q', 'a', 'o', 'h')]):
                log.debug('(%s) Relay kick: kicker %s is not opped... We should rejoin the target user %s', irc.name, kicker, real_target)
                # Home network is not in the channel's claim AND the kicker is not
                # opped. We won't propograte the kick then.
                # TODO: make the check slightly more advanced: i.e. halfops can't
                # kick ops, admins can't kick owners, etc.
                modes = getPrefixModes(remoteirc, irc, remotechan, real_target)
                # Join the kicked client back with its respective modes.
                irc.proto.sjoinServer(irc, irc.sid, remotechan, [(modes, target)])
                utils.msg(irc, kicker, "This channel is claimed; your kick has "
                                       "to %s been blocked because you are not "
                                       "(half)opped." % channel, notice=True)
            else:
                # Propogate the kick!
                log.debug('(%s) Relay kick: Kicking %s from channel %s via %s on behalf of %s/%s', irc.name, real_target, remotechan, real_kicker, kicker, irc.name)
                remoteirc.proto.kickClient(remoteirc, real_kicker,
                                           remotechan, real_target, args['text'])                
utils.add_hook(handle_kick, 'KICK')

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
        log.debug('Okay, spawning %s/%s everywhere', user, irc.name)
        for name, remoteirc in utils.networkobjects.items():
            if name == irc.name:
                # Don't relay things to their source network...
                continue
            u = getRemoteUser(irc, remoteirc, user)
            remotechan = findRemoteChan(irc, remoteirc, channel)
            if remotechan is None or u is None:
                continue
            ts = irc.channels[channel].ts
            # TODO: join users in batches with SJOIN, not one by one.
            prefixes = getPrefixModes(irc, remoteirc, channel, user)
            userpair = (prefixes, u)
            log.debug('(%s) relayJoin: joining %s to %s%s', irc.name, userpair, remoteirc.name, remotechan)
            remoteirc.proto.sjoinServer(remoteirc, remoteirc.sid, remotechan, [userpair], ts=ts)

def relayPart(irc, channel, user):
    for name, remoteirc in utils.networkobjects.items():
        if name == irc.name:
            # Don't relay things to their source network...
            continue
        remotechan = findRemoteChan(irc, remoteirc, channel)
        log.debug('(%s) relayPart: looking for %s/%s on %s', irc.name, user, irc.name, remoteirc.name)
        log.debug('(%s) relayPart: remotechan found as %s', irc.name, remotechan)
        remoteuser = getRemoteUser(irc, remoteirc, user)
        log.debug('(%s) relayPart: remoteuser for %s/%s found as %s', irc.name, user, irc.name, remoteuser)
        if remotechan is None:
            continue
        remoteirc.proto.partClient(remoteirc, remoteuser, remotechan, 'Channel delinked.')

def removeChannel(irc, channel):
    if channel not in map(str.lower, irc.serverdata['channels']):
        irc.proto.partClient(irc, irc.pseudoclient.uid, channel)
    relay = findRelay((irc.name, channel))
    if relay:
        all_links = db[relay]['links'].copy()
        all_links.update((relay,))
        log.debug('(%s) removeChannel: all_links: %s', irc.name, all_links)
        for user in irc.channels[channel].users:
            if not utils.isInternalClient(irc, user):
                relayPart(irc, channel, user)
        for link in all_links:
            if link[0] == irc.name:
                # Don't relay things to their source network...
                continue
            remotenet, remotechan = link
            remoteirc = utils.networkobjects[remotenet]
            rc = remoteirc.channels[remotechan]
            for user in remoteirc.channels[remotechan].users.copy():
                log.debug('(%s) removeChannel: part user %s/%s from %s', irc.name, user, remotenet, remotechan)
                if not utils.isInternalClient(remoteirc, user):
                    relayPart(remoteirc, remotechan, user)

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

    entry = (irc.name, channel)
    if entry in db:
        for link in db[entry]['links']:
            removeChannel(utils.networkobjects[link[0]], link[1])
        removeChannel(irc, channel)
        del db[entry]
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
    localentry = findRelay((irc.name, localchan))
    if localentry:
        utils.msg(irc, source, 'Error: channel %r is already part of a relay.' % localchan)
        return
    try:
        entry = db[(remotenet, channel)]
    except KeyError:
        utils.msg(irc, source, 'Error: no such relay %r exists.' % channel)
        return
    else:
        for link in entry['links']:
            if link[0] == irc.name:
                utils.msg(irc, source, "Error: remote channel '%s%s' is already"
                                       " linked here as %r." % (remotenet,
                                                                channel, link[1]))
                return
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
    entry = findRelay((irc.name, channel))
    if entry:
        if entry[0] == irc.name:  # We own this channel.
            if remotenet is None:
                utils.msg(irc, source, "Error: you must select a network to delink, or use the 'destroy' command no remove this relay entirely.")
                return
            else:
                for entry in db.values():
                    for link in entry['links'].copy():
                        if link[0] == remotenet:
                            removeChannel(utils.networkobjects[remotenet], link[1])
                            entry['links'].remove(link)
        else:
            removeChannel(irc, channel)
            db[entry]['links'].remove((irc.name, channel))
        utils.msg(irc, source, 'Done.')
    else:
        utils.msg(irc, source, 'Error: no such relay %r.' % channel)

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
