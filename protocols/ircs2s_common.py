"""
ircs2s_common.py: Common base protocol class with functions shared by TS6 and P10-based protocols.
"""

import time

from pylinkirc.classes import Protocol
from pylinkirc.log import log
from pylinkirc import utils

class IRCS2SProtocol(Protocol):
    COMMAND_TOKENS = {}

    def __init__(self, irc):
        super().__init__(irc)
        self.protocol_caps = {'can-spawn-clients', 'has-ts', 'can-host-relay',
                              'can-track-servers'}

    def handle_events(self, data):
        """Event handler for RFC1459-like protocols.

        This passes most commands to the various handle_ABCD() functions
        elsewhere defined protocol modules, coersing various sender prefixes
        from nicks and server names to UIDs and SIDs respectively,
        whenever possible.

        Commands sent without an explicit sender prefix will have them set to
        the SID of the uplink server.
        """
        data = data.split(" ")
        args = self.parseArgs(data)

        sender = args[0]
        sender = sender.lstrip(':')

        # If the sender isn't in numeric format, try to convert it automatically.
        sender_sid = self._getSid(sender)
        sender_uid = self._getUid(sender)

        if sender_sid in self.irc.servers:
            # Sender is a server (converting from name to SID gave a valid result).
            sender = sender_sid
        elif sender_uid in self.irc.users:
            # Sender is a user (converting from name to UID gave a valid result).
            sender = sender_uid
        else:
            # No sender prefix; treat as coming from uplink IRCd.
            sender = self.irc.uplink
            args.insert(0, sender)

        raw_command = args[1].upper()
        args = args[2:]

        log.debug('(%s) Found message sender as %s', self.irc.name, sender)

        # For P10, convert the command token into a regular command, if present.
        command = self.COMMAND_TOKENS.get(raw_command, raw_command)
        if command != raw_command:
            log.debug('(%s) Translating token %s to command %s', self.irc.name, raw_command, command)

        if self.irc.isInternalClient(sender) or self.irc.isInternalServer(sender):
            log.warning("(%s) Received command %s being routed the wrong way!", self.irc.name, command)
            return

        if command == 'ENCAP':
            # Special case for TS6 encapsulated commands (ENCAP), in forms like this:
            # <- :00A ENCAP * SU 42XAAAAAC :GLolol
            command = args[1]
            args = args[2:]
            log.debug("(%s) Rewriting incoming ENCAP to command %s (args: %s)", self.irc.name, command, args)

        try:
            func = getattr(self, 'handle_'+command.lower())
        except AttributeError:  # Unhandled command
            pass
        else:
            parsed_args = func(sender, command, args)
            if parsed_args is not None:
                return [sender, command, parsed_args]

    def handle_privmsg(self, source, command, args):
        """Handles incoming PRIVMSG/NOTICE."""
        # TS6:
        # <- :70MAAAAAA PRIVMSG #dev :afasfsa
        # <- :70MAAAAAA NOTICE 0ALAAAAAA :afasfsa
        # P10:
        # <- ABAAA P AyAAA :privmsg text
        # <- ABAAA O AyAAA :notice text
        target = self._getUid(args[0])

        # Coerse =#channel from Charybdis op moderated +z to @#channel.
        if target.startswith('='):
            target = '@' + target[1:]

        # We use lowercase channels internally, but uppercase UIDs.
        # Strip the target of leading prefix modes (for targets like @#channel)
        # before checking whether it's actually a channel.
        split_channel = target.split('#', 1)
        if len(split_channel) >= 2 and utils.isChannel('#' + split_channel[1]):
            # Note: don't mess with the case of the channel prefix, or ~#channel
            # messages will break on RFC1459 casemapping networks (it becomes ^#channel
            # instead).
            target = '#'.join((split_channel[0], self.irc.toLower(split_channel[1])))
            log.debug('(%s) Normalizing channel target %s to %s', self.irc.name, args[0], target)

        return {'target': target, 'text': args[1]}

    handle_notice = handle_privmsg

    def check_nick_collision(self, nick):
        """
        Nick collision checker.
        """
        uid = self.irc.nickToUid(nick)
        # If there is a nick collision, we simply alert plugins. Relay will purposely try to
        # lose fights and tag nicks instead, while other plugins can choose how to handle this.
        if uid:
            log.info('(%s) Nick collision on %s/%s, forwarding this to plugins', self.irc.name,
                     uid, nick)
            self.irc.callHooks([self.irc.sid, 'SAVE', {'target': uid}])

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

        # TS6-style kills look something like this:
        # <- :GL KILL 38QAAAAAA :hidden-1C620195!GL (test)
        # What we actually want is to format a pretty kill message, in the form
        # "Killed (killername (reason))".

        try:
            # Get the nick or server name of the caller.
            killer = self.irc.getFriendlyName(source)
        except KeyError:
            # Killer was... neither? We must have aliens or something. Fallback
            # to the given "UID".
            killer = source

        # Get the reason, which is enclosed in brackets.
        reason = ' '.join(args[1].split(" ")[1:])

        killmsg = "Killed (%s %s)" % (killer, reason)

        return {'target': killed, 'text': killmsg, 'userdata': data}

    def handle_squit(self, numeric, command, args):
        """Handles incoming SQUITs."""
        return self._squit(numeric, command, args)

    def handle_away(self, numeric, command, args):
        """Handles incoming AWAY messages."""
        # TS6:
        # <- :6ELAAAAAB AWAY :Auto-away
        # P10:
        # <- ABAAA A :blah
        # <- ABAAA A
        try:
            self.irc.users[numeric].away = text = args[0]
        except IndexError:  # User is unsetting away status
            self.irc.users[numeric].away = text = ''
        return {'text': text}

    def handle_version(self, numeric, command, args):
        """Handles requests for the PyLink server version."""
        return {}  # See coremods/handlers.py for how this hook is used

    def handle_whois(self, numeric, command, args):
        """Handles incoming WHOIS commands.."""
        # TS6:
        # <- :42XAAAAAB WHOIS 5PYAAAAAA :pylink-devel
        # P10:
        # <- ABAAA W Ay :PyLink-devel

        # First argument is the server that should reply to the WHOIS request
        # or the server hosting the UID given. We can safely assume that any
        # WHOIS commands received are for us, since we don't host any real servers
        # to route it to.

        return {'target': self._getUid(args[-1])}

    def handle_quit(self, numeric, command, args):
        """Handles incoming QUIT commands."""
        # TS6:
        # <- :1SRAAGB4T QUIT :Quit: quit message goes here
        # P10:
        # <- ABAAB Q :Killed (GL_ (bangbang))
        self.removeClient(numeric)
        return {'text': args[0]}

    def handle_time(self, numeric, command, args):
        """Handles incoming /TIME requests."""
        return {'target': args[0]}

    def handle_pong(self, source, command, args):
        """Handles incoming PONG commands."""
        if source == self.irc.uplink:
            self.irc.lastping = time.time()
