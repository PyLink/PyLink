"""
ts6_common.py: Common base protocol class with functions shared by the UnrealIRCd, InspIRCd, and TS6 protocol modules.
"""

import sys
import os

# Import hacks to access utils and classes...
curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]

import utils
from log import log
from classes import *

class TS6BaseProtocol(Protocol):
    def _send(self, source, msg):
        """Sends a TS6-style raw command from a source numeric to the self.irc connection given."""
        self.irc.send(':%s %s' % (source, msg))

    def parseTS6Args(self, args):
        """Similar to parseArgs(), but stripping leading colons from the first argument
        of a line (usually the sender field)."""
        args = self.parseArgs(args)
        args[0] = args[0].split(':', 1)[1]
        return args

    def _getSid(self, sname):
        """Returns the SID of a server with the given name, if present."""
        name = sname.lower()
        for k, v in self.irc.servers.items():
            if v.name.lower() == name:
                return k
        else:
            return sname  # Fall back to given text instead of None

    def _getNick(self, target):
        """Converts a nick argument to its matching UID. This differs from irc.nickToUid()
        in that it returns the original text instead of None, if no matching nick is found."""
        target = self.irc.nickToUid(target) or target
        if target not in self.irc.users and not utils.isChannel(target):
            log.debug("(%s) Possible desync? Got command target %s, who "
                        "isn't in our user list!", self.irc.name, target)
        return target

    ### OUTGOING COMMANDS

    def numeric(self, source, numeric, target, text):
        """Sends raw numerics from a server to a remote client, used for WHOIS
        replies."""
        self._send(source, '%s %s %s' % (numeric, target, text))

    def kick(self, numeric, channel, target, reason=None):
        """Sends kicks from a PyLink client/server."""

        if (not self.irc.isInternalClient(numeric)) and \
                (not self.irc.isInternalServer(numeric)):
            raise LookupError('No such PyLink client/server exists.')

        channel = utils.toLower(self.irc, channel)
        if not reason:
            reason = 'No reason given'
        self._send(numeric, 'KICK %s %s :%s' % (channel, target, reason))

        # We can pretend the target left by its own will; all we really care about
        # is that the target gets removed from the channel userlist, and calling
        # handle_part() does that just fine.
        self.handle_part(target, 'KICK', [channel])

    def nick(self, numeric, newnick):
        """Changes the nick of a PyLink client."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')
        self._send(numeric, 'NICK %s %s' % (newnick, int(time.time())))
        self.irc.users[numeric].nick = newnick

    def part(self, client, channel, reason=None):
        """Sends a part from a PyLink client."""
        channel = utils.toLower(self.irc, channel)
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
        self._send(numeric, 'PRIVMSG %s :%s' % (target, text))

    def notice(self, numeric, target, text):
        """Sends a NOTICE from a PyLink client."""
        if not self.irc.isInternalClient(numeric):
            raise LookupError('No such PyLink client exists.')
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
            args = self.parseTS6Args(data)
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
                numeric = self._getNick(sender)

        # parseTS6Args() will raise IndexError if the TS6 sender prefix is missing.
        except IndexError:
            # Raw command without an explicit sender; assume it's being sent by our uplink.
            args = self.parseArgs(data)
            numeric = self.irc.uplink
            command = args[0]
            args = args[1:]

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
        # We use lowercase channels internally, but uppercase UIDs.
        if utils.isChannel(target):
            target = utils.toLower(self.irc, target)
        return {'target': target, 'text': args[1]}

    handle_notice = handle_privmsg

    def handle_kill(self, source, command, args):
        """Handles incoming KILLs."""
        killed = args[0]
        # Depending on whether the IRCd sends explicit QUIT messages for
        # killed clients, the user may or may not have automatically been
        # removed from our user list.
        # If not, we have to assume that KILL = QUIT and remove them
        # ourselves.
        data = self.irc.users.get(killed)
        if data:
            self.removeClient(killed)
        return {'target': killed, 'text': args[1], 'userdata': data}

    def handle_kick(self, source, command, args):
        """Handles incoming KICKs."""
        # :70MAAAAAA KICK #test 70MAAAAAA :some reason
        channel = utils.toLower(self.irc, args[0])
        kicked = args[1]
        self.handle_part(kicked, 'KICK', [channel, args[2]])
        return {'channel': channel, 'target': kicked, 'text': args[2]}

    def handle_error(self, numeric, command, args):
        """Handles ERROR messages - these mean that our uplink has disconnected us!"""
        self.irc.connected.clear()
        raise ProtocolError('Received an ERROR, disconnecting!')

    def handle_nick(self, numeric, command, args):
        """Handles incoming NICK changes."""
        # <- :70MAAAAAA NICK GL-devel 1434744242
        oldnick = self.irc.users[numeric].nick
        newnick = self.irc.users[numeric].nick = args[0]
        return {'newnick': newnick, 'oldnick': oldnick, 'ts': int(args[1])}

    def handle_quit(self, numeric, command, args):
        """Handles incoming QUIT commands."""
        # <- :1SRAAGB4T QUIT :Quit: quit message goes here
        self.removeClient(numeric)
        return {'text': args[0]}

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
        return {'target': user, 'ts': int(args[1]), 'oldnick': oldnick}

    def handle_squit(self, numeric, command, args):
        """Handles incoming SQUITs (netsplits)."""
        # :70M SQUIT 1ML :Server quit by GL!gl@0::1
        log.debug('handle_squit args: %s', args)
        split_server = args[0]
        affected_users = []
        log.debug('(%s) Splitting server %s (reason: %s)', self.irc.name, split_server, args[-1])
        if split_server not in self.irc.servers:
            log.warning("(%s) Tried to split a server (%s) that didn't exist!", self.irc.name, split_server)
            return
        # Prevent RuntimeError: dictionary changed size during iteration
        old_servers = self.irc.servers.copy()
        for sid, data in old_servers.items():
            if data.uplink == split_server:
                log.debug('Server %s also hosts server %s, removing those users too...', split_server, sid)
                args = self.handle_squit(sid, 'SQUIT', [sid, "PyLink: Automatically splitting leaf servers of %s" % sid])
                affected_users += args['users']
        for user in self.irc.servers[split_server].users.copy():
            affected_users.append(user)
            log.debug('Removing client %s (%s)', user, self.irc.users[user].nick)
            self.removeClient(user)
        sname = self.irc.servers[split_server].name
        del self.irc.servers[split_server]
        log.debug('(%s) Netsplit affected users: %s', self.irc.name, affected_users)
        return {'target': split_server, 'users': affected_users, 'name': sname}

    def handle_topic(self, numeric, command, args):
        """Handles incoming TOPIC changes from clients. For topic bursts,
        TB (TS6/charybdis) and FTOPIC (InspIRCd) are used instead."""
        # <- :70MAAAAAA TOPIC #test :test
        channel = utils.toLower(self.irc, args[0])
        topic = args[1]

        oldtopic = self.irc.channels[channel].topic
        self.irc.channels[channel].topic = topic
        self.irc.channels[channel].topicset = True

        return {'channel': channel, 'setter': numeric, 'text': topic,
                'oldtopic': oldtopic}

    def handle_part(self, source, command, args):
        """Handles incoming PART commands."""
        channels = utils.toLower(self.irc, args[0]).split(',')
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

    def handle_away(self, numeric, command, args):
        """Handles incoming AWAY messages."""
        # <- :6ELAAAAAB AWAY :Auto-away
        try:
            self.irc.users[numeric].away = text = args[0]
        except IndexError:  # User is unsetting away status
            self.irc.users[numeric].away = text = ''
        return {'text': text}

    def handle_version(self, numeric, command, args):
        """Handles requests for the PyLink server version."""
        return {}  # See coreplugin.py for how this hook is used
