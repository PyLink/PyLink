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
    # Block until we know the IRC network's nick length (after capabilities
    # are sent)
    irc.connected.wait()

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
    # TODO: factorize
    while utils.nickToUid(irc, nick) and not utils.isInternalClient(irc, utils.nickToUid(irc, nick)):
        # The nick we want exists? Darn, create another one then, but only if
        # the target isn't an internal client!
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
        if user == remoteirc.pseudoclient.uid:
            return irc.pseudoclient.uid
        if user == irc.pseudoclient.uid:
            return remoteirc.pseudoclient.uid
    except AttributeError:  # Network hasn't been initialized yet?
        pass
    try:
        u = relayusers[(irc.name, user)][remoteirc.name]
    except KeyError:
        userobj = irc.users.get(user)
        if userobj is None or not remoteirc.connected:
            # The query wasn't actually a valid user, or the network hasn't
            # been connected yet... Oh well!
            return
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

def getLocalUser(irc, user):
    # Our target is an internal client, which means someone
    # is kicking a remote user over the relay.
    # We have to find the real target for the KICK. This is like
    # findRemoteUser, but in reverse.
    # First, iterate over everyone!
    for k, v in relayusers.items():
        log.debug('(%s) getLocalUser: processing %s, %s in relayusers', irc.name, k, v)
        if k[0] == irc.name:
            # We don't need to do anything if the target users is on
            # the same network as us.
            log.debug('(%s) getLocalUser: skipping %s since the target network matches the source network.', irc.name, k)
            continue
        if v.get(irc.name) == user:
            # If the stored pseudoclient UID for the kicked user on
            # this network matches the target we have, set that user
            # as the one we're kicking! It's a handful, but remember
            # we're mapping (home network, UID) pairs to their
            # respective relay pseudoclients on other networks.
            remoteuser = k
            log.debug('(%s) getLocalUser: found %s to correspond to %s.', irc.name, v, k)
            return remoteuser

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
            if not (remoteirc.connected and findRemoteChan(remoteirc, irc, remotechan)):
                continue  # They aren't connected, don't bother!
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
            relayModes(remoteirc, irc, remoteirc.sid, remotechan)
            relayModes(irc, remoteirc, irc.sid, channel)

    log.debug('(%s) initializeChannel: joining our users: %s', irc.name, c.users)
    relayJoins(irc, channel, c.users, c.ts, c.modes)
    remoteirc = utils.networkobjects[relay[0]]
    topic = remoteirc.channels[relay[1]].topic
    # XXX: find a more elegant way to do this
    # Only update the topic if it's different from what we already have.
    if topic and topic != irc.channels[channel].topic:
        irc.proto.topicServer(irc, irc.sid, channel, topic)

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

def handle_squit(irc, numeric, command, args):
    users = args['users']
    for user in users:
        log.debug('(%s) relay handle_squit: sending handle_quit on %s', irc.name, user)
        handle_quit(irc, user, command, {'text': '*.net *.split'})
utils.add_hook(handle_squit, 'SQUIT')

def handle_nick(irc, numeric, command, args):
    for netname, user in relayusers[(irc.name, numeric)].items():
        remoteirc = utils.networkobjects[netname]
        newnick = normalizeNick(remoteirc, irc.name, args['newnick'])
        if remoteirc.users[user].nick != newnick:
            remoteirc.proto.nickClient(remoteirc, user, newnick)
utils.add_hook(handle_nick, 'NICK')

def handle_part(irc, numeric, command, args):
    channel = args['channel']
    text = args['text']
    for netname, user in relayusers.copy()[(irc.name, numeric)].items():
        remoteirc = utils.networkobjects[netname]
        remotechan = findRemoteChan(irc, remoteirc, channel)
        remoteirc.proto.partClient(remoteirc, user, remotechan, text)
        if not remoteirc.users[user].channels:
            remoteirc.proto.quitClient(remoteirc, user, 'Left all shared channels.')
            del relayusers[(irc.name, numeric)][remoteirc.name]
utils.add_hook(handle_part, 'PART')

def handle_privmsg(irc, numeric, command, args):
    notice = (command == 'NOTICE')
    target = args['target']
    text = args['text']
    for netname, user in relayusers[(irc.name, numeric)].items():
        remoteirc = utils.networkobjects[netname]
        if utils.isChannel(target):
            real_target = findRemoteChan(irc, remoteirc, target)
            if not real_target:
                continue
        else:
            try:
                real_target = getLocalUser(irc, target)[1]
            except TypeError:
                real_target = getRemoteUser(irc, remoteirc, target)
        if notice:
            remoteirc.proto.noticeClient(remoteirc, user, real_target, text)
        else:
            remoteirc.proto.messageClient(remoteirc, user, real_target, text)
utils.add_hook(handle_privmsg, 'PRIVMSG')
utils.add_hook(handle_privmsg, 'NOTICE')

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
        if real_kicker is None or not utils.isInternalClient(irc, target):
            log.debug('(%s) Relay kick: target %s is NOT an internal client', irc.name, target)
            # Both the target and kicker are external clients; i.e.
            # they originate from the same network. We shouldn't have
            # to process this any further, because the uplink IRCd
            # will handle this appropriately, and we'll just follow.
            real_target = getRemoteUser(irc, remoteirc, target)
            log.debug('(%s) Relay kick: real target for %s is %s', irc.name, target, real_target)
            if real_kicker:
                remoteirc.proto.kickClient(remoteirc, real_kicker,
                                           remotechan, real_target, text)
            else: # Kick originated from a server, not a client.
                try:
                    text = "(%s@%s) %s" % (irc.servers[kicker].name, irc.name, text)
                except (KeyError, AttributeError):
                    text = "(<unknown server>@%s) %s" % (irc.name, text)
                remoteirc.proto.kickServer(remoteirc, remoteirc.sid,
                                           remotechan, real_target, text)
        else:
            log.debug('(%s) Relay kick: target %s is an internal client, going to look up the real user', irc.name, target)
            real_target = getLocalUser(irc, target)[1]
            log.debug('(%s) Relay kick: kicker_modes are %r', irc.name, kicker_modes)
            if irc.name not in db[relay]['claim'] and not \
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

def handle_chgclient(irc, source, command, args):
    target = args['target']
    if args.get('newhost'):
        field = 'HOST'
        text = args['newhost']
    elif args.get('newident'):
        field = 'IDENT'
        text = args['newident']
    elif args.get('newgecos'):
        field = 'GECOS'
        text = args['newgecos']
    if field:
        for netname, user in relayusers[(irc.name, target)].items():
            remoteirc = utils.networkobjects[netname]
            try:
                remoteirc.proto.updateClient(remoteirc, user, field, text)
            except ValueError:  # IRCd doesn't support changing the field we want
                logging.debug('(%s) Error raised changing field %r of %s on %s (for %s/%s)', irc.name, field, user, target, remotenet, irc.name)
                continue

for c in ('CHGHOST', 'CHGNAME', 'CHGIDENT'):
    utils.add_hook(handle_chgclient, c)

def relayModes(irc, remoteirc, sender, channel, modes=None):
    remotechan = findRemoteChan(irc, remoteirc, channel)
    log.debug('(%s) Relay mode: remotechan for %s on %s is %s', irc.name, channel, irc.name, remotechan)
    if remotechan is None:
        return
    if modes is None:
        modes = remoteirc.channels[remotechan].modes
        log.debug('(%s) Relay mode: channel data for %s%s: %s', irc.name, remoteirc.name, remotechan, remoteirc.channels[remotechan])
    supported_modes = []
    log.debug('(%s) Relay mode: initial modelist for %s is %s', irc.name, channel, modes)
    for modepair in modes:
        try:
            prefix, modechar = modepair[0]
        except ValueError:
            modechar = modepair[0]
            prefix = '+'
        arg = modepair[1]
        # Iterate over every mode see whether the remote IRCd supports
        # this mode, and what its mode char for it is (if it is different).
        for name, m in irc.cmodes.items():
            supported_char = None
            if modechar == m:
                if modechar in irc.prefixmodes:
                    # This is a prefix mode (e.g. +o). We must coerse the argument
                    # so that the target exists on the remote relay network.
                    try:
                        arg = getLocalUser(irc, arg)[1]
                    except TypeError:
                        # getLocalUser returns None, raises None when trying to
                        # get [1] from it.
                        arg = getRemoteUser(irc, remoteirc, arg)
                supported_char = remoteirc.cmodes.get(name)
            if supported_char:
                supported_modes.append((prefix+supported_char, arg))
    log.debug('(%s) Relay mode: final modelist (sending to %s%s) is %s', irc.name, remoteirc.name, remotechan, supported_modes)
    # Don't send anything if there are no supported modes left after filtering.
    if supported_modes:
        # Check if the sender is a user; remember servers are allowed to set modes too.
        if sender in irc.users:
            u = getRemoteUser(irc, remoteirc, sender)
            remoteirc.proto.modeClient(remoteirc, u, channel, supported_modes)
        else:
            remoteirc.proto.modeServer(remoteirc, remoteirc.sid, channel, supported_modes)

def handle_mode(irc, numeric, command, args):
    target = args['target']
    if not utils.isChannel(target):
        ### TODO: handle user mode changes too
        return
    modes = args['modes']
    for name, remoteirc in utils.networkobjects.items():
        if irc.name == name:
            continue
        relayModes(irc, remoteirc, numeric, target, modes)
utils.add_hook(handle_mode, 'MODE')

def handle_topic(irc, numeric, command, args):
    channel = args['channel']
    topic = args['topic']
    # XXX: find a more elegant way to do this
    # Topics with content take precedence over empty topics.
    # This prevents us from overwriting topics on channels with
    # emptiness just because a leaf network hasn't received it yet.
    if topic:
        for name, remoteirc in utils.networkobjects.items():
            if irc.name == name:
                continue

            remotechan = findRemoteChan(irc, remoteirc, channel)
            # Don't send if the remote topic is the same as ours.
            if remotechan is None or topic == remoteirc.channels[remotechan].topic:
                continue
            # This might originate from a server too.
            remoteuser = getRemoteUser(irc, remoteirc, numeric)
            if remoteuser:
                remoteirc.proto.topicClient(remoteirc, remoteuser, remotechan, topic)
            else:
                remoteirc.proto.topicServer(remoteirc, remoteirc.sid, remotechan, topic)
utils.add_hook(handle_topic, 'TOPIC')

def handle_kill(irc, numeric, command, args):
    target = args['target']
    userdata = args['userdata']
    # We don't allow killing over the relay, so we must spawn the client.
    # all over again and rejoin it to its channels.
    realuser = getLocalUser(irc, target)
    del relayusers[realuser][irc.name]
    remoteirc = utils.networkobjects[realuser[0]]
    for channel in remoteirc.channels:
        remotechan = findRemoteChan(remoteirc, irc, channel)
        if remotechan:
            modes = getPrefixModes(remoteirc, irc, remotechan, realuser[1])
            log.debug('(%s) handle_kill: userpair: %s, %s', irc.name, modes, realuser)
            client = getRemoteUser(remoteirc, irc, realuser[1])
            irc.proto.sjoinServer(irc, irc.sid, remotechan, [(modes, client)])
            utils.msg(irc, numeric, "Your kill has to %s been blocked "
                                   "because PyLink does not allow killing"
                                   " users over the relay at this time." % \
                                   userdata.nick, notice=True)
utils.add_hook(handle_kill, 'KILL')

def relayJoins(irc, channel, users, ts, modes):
    queued_users = []
    for user in users.copy():
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
            remotechan = findRemoteChan(irc, remoteirc, channel)
            if remotechan is None:
                # If there is no link on our network for the user, don't
                # bother spawning it.
                continue
            u = getRemoteUser(irc, remoteirc, user)
            if u is None:
                continue
            ts = irc.channels[channel].ts
            # TODO: join users in batches with SJOIN, not one by one.
            prefixes = getPrefixModes(irc, remoteirc, channel, user)
            userpair = (prefixes, u)
            log.debug('(%s) relayJoin: joining %s to %s%s', irc.name, userpair, remoteirc.name, remotechan)
            remoteirc.proto.sjoinServer(remoteirc, remoteirc.sid, remotechan, [userpair], ts=ts)
            relayModes(irc, remoteirc, irc.sid, channel, modes)

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
        if not remoteirc.users[remoteuser].channels:
            remoteirc.proto.quitClient(remoteirc, remoteuser, 'Left all shared channels.')
            del relayusers[(irc.name, user)][remoteirc.name]

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
               for link in db[entry]['links'].copy():
                    if link[0] == remotenet:
                        removeChannel(utils.networkobjects[remotenet], link[1])
                        db[entry]['links'].remove(link)
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
