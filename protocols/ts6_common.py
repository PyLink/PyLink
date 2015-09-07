import sys
import os

curdir = os.path.dirname(__file__)
sys.path += [curdir, os.path.dirname(curdir)]
import utils
from log import log
from classes import *

class TS6BaseProtocol(Protocol):
    def _send(self, source, msg):
        """Sends a TS6-style raw command from a source numeric to the self.irc connection given."""
        self.irc.send(':%s %s' % (source, msg))

    def parseArgs(self, args):
        """Parses a string of RFC1459-style arguments split into a list, where ":" may
        be used for multi-word arguments that last until the end of a line.
        """
        real_args = []
        for idx, arg in enumerate(args):
            real_args.append(arg)
            # If the argument starts with ':' and ISN'T the first argument.
            # The first argument is used for denoting the source UID/SID.
            if arg.startswith(':') and idx != 0:
                # : is used for multi-word arguments that last until the end
                # of the message. We can use list splicing here to turn them all
                # into one argument.
                # Set the last arg to a joined version of the remaining args
                arg = args[idx:]
                arg = ' '.join(arg)[1:]
                # Cut the original argument list right before the multi-word arg,
                # and then append the multi-word arg.
                real_args = args[:idx]
                real_args.append(arg)
                break
        return real_args

    def parseTS6Args(self, args):
        """Similar to parseArgs(), but stripping leading colons from the first argument
        of a line (usually the sender field)."""
        args = self.parseArgs(args)
        args[0] = args[0].split(':', 1)[1]
        return args

    ### OUTGOING COMMANDS

    def _sendKick(self, numeric, channel, target, reason=None):
        """Internal function to send kicks from a PyLink client/server."""
        channel = utils.toLower(self.irc, channel)
        if not reason:
            reason = 'No reason given'
        self._send(numeric, 'KICK %s %s :%s' % (channel, target, reason))
        # We can pretend the target left by its own will; all we really care about
        # is that the target gets removed from the channel userlist, and calling
        # handle_part() does that just fine.
        self.handle_part(target, 'KICK', [channel])

    def kickClient(self, numeric, channel, target, reason=None):
        """Sends a kick from a PyLink client."""
        if not utils.isInternalClient(self.irc, numeric):
            raise LookupError('No such PyLink PseudoClient exists.')
        self._sendKick(numeric, channel, target, reason=reason)

    def kickServer(self, numeric, channel, target, reason=None):
        """Sends a kick from a PyLink server."""
        if not utils.isInternalServer(self.irc, numeric):
            raise LookupError('No such PyLink PseudoServer exists.')
        self._sendKick(numeric, channel, target, reason=reason)

    def nickClient(self, numeric, newnick):
        """Changes the nick of a PyLink client."""
        if not utils.isInternalClient(self.irc, numeric):
            raise LookupError('No such PyLink PseudoClient exists.')
        self._send(numeric, 'NICK %s %s' % (newnick, int(time.time())))
        self.irc.users[numeric].nick = newnick

    def removeClient(self, numeric):
        """Internal function to remove a client from our internal state."""
        for c, v in self.irc.channels.copy().items():
            v.removeuser(numeric)
            # Clear empty non-permanent channels.
            if not (self.irc.channels[c].users or ((self.irc.cmodes.get('permanent'), None) in self.irc.channels[c].modes)):
                del self.irc.channels[c]

        sid = numeric[:3]
        log.debug('Removing client %s from self.irc.users', numeric)
        del self.irc.users[numeric]
        log.debug('Removing client %s from self.irc.servers[%s]', numeric, sid)
        self.irc.servers[sid].users.discard(numeric)

    def partClient(self, client, channel, reason=None):
        """Sends a part from a PyLink client."""
        channel = utils.toLower(self.irc, channel)
        if not utils.isInternalClient(self.irc, client):
            log.error('(%s) Error trying to part client %r to %r (no such pseudoclient exists)', self.irc.name, client, channel)
            raise LookupError('No such PyLink PseudoClient exists.')
        msg = "PART %s" % channel
        if reason:
            msg += " :%s" % reason
        self._send(client, msg)
        self.handle_part(client, 'PART', [channel])

    def quitClient(self, numeric, reason):
        """Quits a PyLink client."""
        if utils.isInternalClient(self.irc, numeric):
            self._send(numeric, "QUIT :%s" % reason)
            self.removeClient(numeric)
        else:
            raise LookupError("No such PyLink PseudoClient exists.")

    def messageClient(self, numeric, target, text):
        """Sends a PRIVMSG from a PyLink client."""
        if not utils.isInternalClient(self.irc, numeric):
            raise LookupError('No such PyLink PseudoClient exists.')
        self._send(numeric, 'PRIVMSG %s :%s' % (target, text))

    def noticeClient(self, numeric, target, text):
        """Sends a NOTICE from a PyLink client."""
        if not utils.isInternalClient(self.irc, numeric):
            raise LookupError('No such PyLink PseudoClient exists.')
        self._send(numeric, 'NOTICE %s :%s' % (target, text))

    def topicClient(self, numeric, target, text):
        """Sends a TOPIC change from a PyLink client."""
        if not utils.isInternalClient(self.irc, numeric):
            raise LookupError('No such PyLink PseudoClient exists.')
        self._send(numeric, 'TOPIC %s :%s' % (target, text))
        self.irc.channels[target].topic = text
        self.irc.channels[target].topicset = True

    ### HANDLERS

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
        # Depending on whether the self.ircd sends explicit QUIT messages for
        # KILLed clients, the user may or may not have automatically been removed.
        # If not, we have to assume that KILL = QUIT and remove them ourselves.
        data = self.irc.users.get(killed)
        if data:
            self.removeClient(killed)
        return {'target': killed, 'text': args[1], 'userdata': data}

    def handle_kick(self, source, command, args):
        """Handles incoming KICKs."""
        # :70MAAAAAA KICK #endlessvoid 70MAAAAAA :some reason
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
        """Handles incoming QUITs."""
        # <- :1SRAAGB4T QUIT :Quit: quit message goes here
        self.removeClient(numeric)
        return {'text': args[0]}

    def handle_save(self, numeric, command, args):
        """Handles incoming SAVE messages, used to handle nick collisions."""
        # In this below example, the client Derp_ already exists,
        # and trying to change someone's nick to it will cause a nick
        # collision. On TS6 self.ircds, this will simply set the collided user's
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
        split_server = args[0]
        affected_users = []
        log.info('(%s) Netsplit on server %s', self.irc.name, split_server)
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
        del self.irc.servers[split_server]
        log.debug('(%s) Netsplit affected users: %s', self.irc.name, affected_users)
        return {'target': split_server, 'users': affected_users}

    def handle_mode(self, numeric, command, args):
        """Handles incoming user mode changes. For channel mode changes,
        TMODE (TS6/charybdis) and FMODE (Inspself.ircd) are used instead."""
        # In Inspself.ircd, MODE is used for setting user modes and
        # FMODE is used for channel modes:
        # <- :70MAAAAAA MODE 70MAAAAAA -i+xc
        target = args[0]
        modestrings = args[1:]
        changedmodes = utils.parseModes(self.irc, numeric, modestrings)
        utils.applyModes(self.irc, target, changedmodes)
        return {'target': target, 'modes': changedmodes}

    def handle_topic(self, numeric, command, args):
        """Handles incoming TOPIC changes from clients. For topic bursts,
        TB (TS6/charybdis) and FTOPIC (Inspself.ircd) are used instead."""
        # <- :70MAAAAAA TOPIC #test :test
        channel = utils.toLower(self.irc, args[0])
        topic = args[1]
        ts = int(time.time())
        self.irc.channels[channel].topic = topic
        self.irc.channels[channel].topicset = True
        return {'channel': channel, 'setter': numeric, 'ts': ts, 'topic': topic}

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
