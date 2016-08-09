"""
ts6_common.py: Common base protocol class with functions shared by the UnrealIRCd, InspIRCd, and TS6 protocol modules.
"""

import string
import time

from pylinkirc import utils, structures
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ircs2s_common import *

class TS6SIDGenerator():
    """
    TS6 SID Generator. <query> is a 3 character string with any combination of
    uppercase letters, digits, and #'s. it must contain at least one #,
    which are used by the generator as a wildcard. On every next_sid() call,
    the first available wildcard character (from the right) will be
    incremented to generate the next SID.

    When there are no more available SIDs left (SIDs are not reused, only
    incremented), RuntimeError is raised.

    Example queries:
        "1#A" would give: 10A, 11A, 12A ... 19A, 1AA, 1BA ... 1ZA (36 total results)
        "#BQ" would give: 0BQ, 1BQ, 2BQ ... 9BQ (10 total results)
        "6##" would give: 600, 601, 602, ... 60Y, 60Z, 610, 611, ... 6ZZ (1296 total results)
    """

    def __init__(self, irc):
        self.irc = irc
        try:
            self.query = query = list(irc.serverdata["sidrange"])
        except KeyError:
            raise RuntimeError('(%s) "sidrange" is missing from your server configuration block!' % irc.name)

        self.iters = self.query.copy()
        self.output = self.query.copy()
        self.allowedchars = {}
        qlen = len(query)

        assert qlen == 3, 'Incorrect length for a SID (must be 3, got %s)' % qlen
        assert '#' in query, "Must be at least one wildcard (#) in query"

        for idx, char in enumerate(query):
            # Iterate over each character in the query string we got, along
            # with its index in the string.
            assert char in (string.digits+string.ascii_uppercase+"#"), \
                "Invalid character %r found." % char
            if char == '#':
                if idx == 0:  # The first char be only digits
                    self.allowedchars[idx] = string.digits
                else:
                    self.allowedchars[idx] = string.digits+string.ascii_uppercase
                self.iters[idx] = iter(self.allowedchars[idx])
                self.output[idx] = self.allowedchars[idx][0]
                next(self.iters[idx])


    def increment(self, pos=2):
        """
        Increments the SID generator to the next available SID.
        """
        if pos < 0:
            # Oh no, we've wrapped back to the start!
            raise RuntimeError('No more available SIDs!')
        it = self.iters[pos]
        try:
            self.output[pos] = next(it)
        except TypeError:  # This position is not an iterator, but a string.
            self.increment(pos-1)
        except StopIteration:
            self.output[pos] = self.allowedchars[pos][0]
            self.iters[pos] = iter(self.allowedchars[pos])
            next(self.iters[pos])
            self.increment(pos-1)

    def next_sid(self):
        """
        Returns the next unused TS6 SID for the server.
        """
        while ''.join(self.output) in self.irc.servers:
            # Increment until the SID we have doesn't already exist.
            self.increment()
        sid = ''.join(self.output)
        return sid

class TS6UIDGenerator(utils.IncrementalUIDGenerator):
     """Implements an incremental TS6 UID Generator."""

     def __init__(self, sid):
         # Define the options for IncrementalUIDGenerator, and then
         # initialize its functions.
         # TS6 UIDs are 6 characters in length (9 including the SID).
         # They go from ABCDEFGHIJKLMNOPQRSTUVWXYZ -> 0123456789 -> wrap around:
         # e.g. AAAAAA, AAAAAB ..., AAAAA8, AAAAA9, AAAABA, etc.
         self.allowedchars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456879'
         self.length = 6
         super().__init__(sid)

class TS6BaseProtocol(IRCS2SProtocol):

    def __init__(self, irc):
        super().__init__(irc)

        # Dictionary of UID generators (one for each server).
        self.uidgen = structures.KeyedDefaultdict(TS6UIDGenerator)

        # SID generator for TS6.
        self.sidgen = TS6SIDGenerator(irc)

    def _send(self, source, msg):
        """Sends a TS6-style raw command from a source numeric to the self.irc connection given."""
        self.irc.send(':%s %s' % (source, msg))

    def _expandPUID(self, uid):
        """
        Returns the outgoing nick for the given UID. In the base ts6_common implementation,
        this does nothing, but other modules subclassing this can override it.
        For example, this can be used to turn PUIDs (used to store legacy, UID-less users)
        to actual nicks in outgoing messages, so that a remote IRCd can understand it.
        """
        return uid

    ### OUTGOING COMMANDS

    def numeric(self, source, numeric, target, text):
        """Sends raw numerics from a server to a remote client, used for WHOIS
        replies."""
        # Mangle the target for IRCds that require it.
        target = self._expandPUID(target)

        self._send(source, '%s %s %s' % (numeric, target, text))

    def kick(self, numeric, channel, target, reason=None):
        """Sends kicks from a PyLink client/server."""

        if (not self.irc.isInternalClient(numeric)) and \
                (not self.irc.isInternalServer(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        channel = self.irc.toLower(channel)
        if not reason:
            reason = 'No reason given'

        # Mangle kick targets for IRCds that require it.
        target = self._expandPUID(target)

        self._send(numeric, 'KICK %s %s :%s' % (channel, target, reason))

        # We can pretend the target left by its own will; all we really care about
        # is that the target gets removed from the channel userlist, and calling
        # handle_part() does that just fine.
        self.handle_part(target, 'KICK', [channel])

    def kill(self, numeric, target, reason):
        """Sends a kill from a PyLink client/server."""

        if (not self.irc.isInternalClient(numeric)) and \
                (not self.irc.isInternalServer(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        # From TS6 docs:
        # KILL:
        # parameters: target user, path

        # The format of the path parameter is some sort of description of the source of
        # the kill followed by a space and a parenthesized reason. To avoid overflow,
        # it is recommended not to add anything to the path.

        assert target in self.irc.users, "Unknown target %r for kill()!" % target

        if numeric in self.irc.users:
            # Killer was an user. Follow examples of setting the path to be "killer.host!killer.nick".
            userobj = self.irc.users[numeric]
            killpath = '%s!%s' % (userobj.host, userobj.nick)
        elif numeric in self.irc.servers:
            # Sender was a server; killpath is just its name.
            killpath = self.irc.servers[numeric].name
        else:
            # Invalid sender?! This shouldn't happen, but make the killpath our server name anyways.
            log.warning('(%s) Invalid sender %s for kill(); using our server name instead.',
                        self.irc.name, numeric)
            killpath = self.irc.servers[self.irc.sid].name

        self._send(numeric, 'KILL %s :%s (%s)' % (target, killpath, reason))
        self.removeClient(target)

    def nick(self, numeric, newnick):
        """Changes the nick of a PyLink client."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')

        self._send(numeric, 'NICK %s %s' % (newnick, int(time.time())))

        self.irc.users[numeric].nick = newnick

        # Update the NICK TS.
        self.irc.users[numeric].ts = int(time.time())

    def part(self, client, channel, reason=None):
        """Sends a part from a PyLink client."""
        channel = self.irc.toLower(channel)
        if not self.irc.isInternalClient(client):
            log.error('(%s) Error trying to part %r from %r (no such client exists)', self.irc.name, client, channel)
            raise LookupError('No such PyLink client exists.')
        msg = "PART %s" % channel
        if reason:
            msg += " :%s" % reason
        self._send(client, msg)
        self.handle_part(client, 'PART', [channel])

    def quit(self, numeric, reason):
        """Quits a PyLink client."""
        if self.irc.isInternalClient(numeric):
            self._send(numeric, "QUIT :%s" % reason)
            self.removeClient(numeric)
        else:
            raise LookupError("No such PyLink client exists.")

    def message(self, numeric, target, text):
        """Sends a PRIVMSG from a PyLink client."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')

        # Mangle message targets for IRCds that require it.
        target = self._expandPUID(target)

        self._send(numeric, 'PRIVMSG %s :%s' % (target, text))

    def notice(self, numeric, target, text):
        """Sends a NOTICE from a PyLink client."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')

        # Mangle message targets for IRCds that require it.
        target = self._expandPUID(target)

        self._send(numeric, 'NOTICE %s :%s' % (target, text))

    def topic(self, numeric, target, text):
        """Sends a TOPIC change from a PyLink client."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')
        self._send(numeric, 'TOPIC %s :%s' % (target, text))
        self.irc.channels[target].topic = text
        self.irc.channels[target].topicset = True

    def spawnServer(self, name, sid=None, uplink=None, desc=None, endburst_delay=0):
        """
        Spawns a server off a PyLink server. desc (server description)
        defaults to the one in the config. uplink defaults to the main PyLink
        server, and sid (the server ID) is automatically generated if not
        given.

        Note: TS6 doesn't use a specific ENDBURST command, so the endburst_delay
        option will be ignored if given.
        """
        # -> :0AL SID test.server 1 0XY :some silly pseudoserver
        uplink = uplink or self.irc.sid
        name = name.lower()
        desc = desc or self.irc.serverdata.get('serverdesc') or self.irc.botdata['serverdesc']
        if sid is None:  # No sid given; generate one!
            sid = self.sidgen.next_sid()
        assert len(sid) == 3, "Incorrect SID length"
        if sid in self.irc.servers:
            raise ValueError('A server with SID %r already exists!' % sid)
        for server in self.irc.servers.values():
            if name == server.name:
                raise ValueError('A server named %r already exists!' % name)
        if not self.irc.isInternalServer(uplink):
            raise ValueError('Server %r is not a PyLink server!' % uplink)
        if not utils.isServerName(name):
            raise ValueError('Invalid server name %r' % name)
        self._send(uplink, 'SID %s 1 %s :%s' % (name, sid, desc))
        self.irc.servers[sid] = IrcServer(uplink, name, internal=True, desc=desc)
        return sid

    def squit(self, source, target, text='No reason given'):
        """SQUITs a PyLink server."""
        # -> SQUIT 9PZ :blah, blah
        log.debug('source=%s, target=%s', source, target)
        self._send(source, 'SQUIT %s :%s' % (target, text))
        self.handle_squit(source, 'SQUIT', [target, text])

    def away(self, source, text):
        """Sends an AWAY message from a PyLink client. <text> can be an empty string
        to unset AWAY status."""
        if text:
            self._send(source, 'AWAY :%s' % text)
        else:
            self._send(source, 'AWAY')
        self.irc.users[source].away = text

    ### HANDLERS

    def handle_events(self, data):
        """Event handler for TS6 protocols.

        This passes most commands to the various handle_ABCD() functions
        elsewhere defined protocol modules, coersing various sender prefixes
        from nicks and server names to UIDs and SIDs respectively,
        whenever possible.

        Commands sent without an explicit sender prefix will have them set to
        the SID of the uplink server.
        """
        data = data.split(" ")
        try:  # Message starts with a SID/UID prefix.
            args = self.parsePrefixedArgs(data)
            sender = args[0]
            command = args[1]
            args = args[2:]
            # If the sender isn't in UID format, try to convert it automatically.
            # Unreal's protocol, for example, isn't quite consistent with this yet!
            sender_server = self._getSid(sender)
            if sender_server in self.irc.servers:
                # Sender is a server when converted from name to SID.
                numeric = sender_server
            else:
                # Sender is a user.
                numeric = self._getUid(sender)

        # parsePrefixedArgs() will raise IndexError if the TS6 sender prefix is missing.
        except IndexError:
            # Raw command without an explicit sender; assume it's being sent by our uplink.
            args = self.parseArgs(data)
            numeric = self.irc.uplink
            command = args[0]
            args = args[1:]

        if command == 'ENCAP':
            # Special case for encapsulated commands (ENCAP), in forms like this:
            # <- :00A ENCAP * SU 42XAAAAAC :GLolol
            command = args[1]
            args = args[2:]
            log.debug("(%s) Rewriting incoming ENCAP to command %s (args: %s)", self.irc.name, command, args)

        try:
            func = getattr(self, 'handle_'+command.lower())
        except AttributeError:  # unhandled command
            pass
        else:
            parsed_args = func(numeric, command, args)
            if parsed_args is not None:
                return [numeric, command, parsed_args]

    def handle_privmsg(self, source, command, args):
        """Handles incoming PRIVMSG/NOTICE."""
        # <- :70MAAAAAA PRIVMSG #dev :afasfsa
        # <- :70MAAAAAA NOTICE 0ALAAAAAA :afasfsa
        target = args[0]

        # Coerse =#channel from Charybdis op moderated +z to @#channel.
        if target.startswith('='):
            target = '@' + target[1:]

        # We use lowercase channels internally, but uppercase UIDs.
        # Strip the target of leading prefix modes (for targets like @#channel)
        # before checking whether it's actually a channel.
        stripped_target = target.lstrip(''.join(self.irc.prefixmodes.values()))
        if utils.isChannel(stripped_target):
            target = self.irc.toLower(target)

        return {'target': target, 'text': args[1]}

    handle_notice = handle_privmsg

    def handle_kick(self, source, command, args):
        """Handles incoming KICKs."""
        # :70MAAAAAA KICK #test 70MAAAAAA :some reason
        channel = self.irc.toLower(args[0])
        kicked = self._getUid(args[1])
        self.handle_part(kicked, 'KICK', [channel, args[2]])
        return {'channel': channel, 'target': kicked, 'text': args[2]}

    def handle_nick(self, numeric, command, args):
        """Handles incoming NICK changes."""
        # <- :70MAAAAAA NICK GL-devel 1434744242
        oldnick = self.irc.users[numeric].nick
        newnick = self.irc.users[numeric].nick = args[0]

        # Update the nick TS.
        self.irc.users[numeric].ts = ts = int(args[1])

        return {'newnick': newnick, 'oldnick': oldnick, 'ts': ts}

    def handle_save(self, numeric, command, args):
        """Handles incoming SAVE messages, used to handle nick collisions."""
        # In this below example, the client Derp_ already exists,
        # and trying to change someone's nick to it will cause a nick
        # collision. On TS6 IRCds, this will simply set the collided user's
        # nick to its UID.

        # <- :70MAAAAAA PRIVMSG 0AL000001 :nickclient PyLink Derp_
        # -> :0AL000001 NICK Derp_ 1433728673
        # <- :70M SAVE 0AL000001 1433728673
        user = args[0]
        oldnick = self.irc.users[user].nick
        self.irc.users[user].nick = user

        # TS6 SAVE sets nick TS to 100. This is hardcoded in InspIRCd and
        # charybdis.
        self.irc.users[user].ts = 100

        return {'target': user, 'ts': 100, 'oldnick': oldnick}

    def handle_topic(self, numeric, command, args):
        """Handles incoming TOPIC changes from clients. For topic bursts,
        TB (TS6/charybdis) and FTOPIC (InspIRCd) are used instead."""
        # <- :70MAAAAAA TOPIC #test :test
        channel = self.irc.toLower(args[0])
        topic = args[1]

        oldtopic = self.irc.channels[channel].topic
        self.irc.channels[channel].topic = topic
        self.irc.channels[channel].topicset = True

        return {'channel': channel, 'setter': numeric, 'text': topic,
                'oldtopic': oldtopic}

    def handle_part(self, source, command, args):
        """Handles incoming PART commands."""
        channels = self.irc.toLower(args[0]).split(',')
        for channel in channels:
            # We should only get PART commands for channels that exist, right??
            self.irc.channels[channel].removeuser(source)
            try:
                self.irc.users[source].channels.discard(channel)
            except KeyError:
                log.debug("(%s) handle_part: KeyError trying to remove %r from %r's channel list?", self.irc.name, channel, source)
            try:
                reason = args[1]
            except IndexError:
                reason = ''
            # Clear empty non-permanent channels.
            if not (self.irc.channels[channel].users or ((self.irc.cmodes.get('permanent'), None) in self.irc.channels[channel].modes)):
                del self.irc.channels[channel]
        return {'channels': channels, 'text': reason}

    def handle_svsnick(self, source, command, args):
        """Handles SVSNICK (forced nickname change attempts)."""
        # InspIRCd:
        # <- :00A ENCAP 902 SVSNICK 902AAAAAB Guest53593 :1468299404
        # This is rewritten to SVSNICK with args ['902AAAAAB', 'Guest53593', '1468299404']

        # UnrealIRCd:
        # <- :services.midnight.vpn SVSNICK GL Guest87795 1468303726
        return {'target': self._getUid(args[0]), 'newnick': args[1]}
