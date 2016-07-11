"""
ircs2s_common.py: Common base protocol class with functions shared by TS6 and P10-based protocols.
"""

from pylinkirc.classes import Protocol
from pylinkirc.log import log

class IRCS2SProtocol(Protocol):

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
        # <- ABAAE SQ nefarious.midnight.vpn 0 :test

        split_server = self._getSid(args[0])

        affected_users = []
        log.debug('(%s) Splitting server %s (reason: %s)', self.irc.name, split_server, args[-1])

        if split_server not in self.irc.servers:
            log.warning("(%s) Tried to split a server (%s) that didn't exist!", self.irc.name, split_server)
            return

        # Prevent RuntimeError: dictionary changed size during iteration
        old_servers = self.irc.servers.copy()
        # Cycle through our list of servers. If any server's uplink is the one that is being SQUIT,
        # remove them and all their users too.
        for sid, data in old_servers.items():
            if data.uplink == split_server:
                log.debug('Server %s also hosts server %s, removing those users too...', split_server, sid)
                # Recursively run SQUIT on any other hubs this server may have been connected to.
                args = self.handle_squit(sid, 'SQUIT', [sid, "0",
                                         "PyLink: Automatically splitting leaf servers of %s" % sid])
                affected_users += args['users']

        for user in self.irc.servers[split_server].users.copy():
            affected_users.append(user)
            log.debug('Removing client %s (%s)', user, self.irc.users[user].nick)
            self.removeClient(user)

        sname = self.irc.servers[split_server].name
        uplink = self.irc.servers[split_server].uplink
        del self.irc.servers[split_server]
        log.debug('(%s) Netsplit affected users: %s', self.irc.name, affected_users)

        return {'target': split_server, 'users': affected_users, 'name': sname,
                'uplink': uplink}

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
