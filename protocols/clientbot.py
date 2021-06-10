"""
clientbot.py: Clientbot (regular IRC bot) protocol module for PyLink.
"""

# Here be dragons. There are lots of hacks and stubs in this module to recreate the same sort of state
# that a regular server would have (e.g. spawning virtual users for things like Relay). Somehow it
# works on most networks though!

import base64
import string
import threading
import time

from pylinkirc import utils, world
from pylinkirc.classes import *
from pylinkirc.log import log
from pylinkirc.protocols.ircs2s_common import *

__all__ = ['ClientbotBaseProtocol', 'ClientbotWrapperProtocol']

FALLBACK_REALNAME = 'PyLink Relay Mirror Client'

# IRCv3 capabilities to request when available
IRCV3_CAPABILITIES = {'multi-prefix', 'sasl', 'away-notify', 'userhost-in-names', 'chghost', 'account-notify',
                      'account-tag', 'extended-join'}

class ClientbotBaseProtocol(PyLinkNetworkCoreWithUtils):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.protocol_caps |= {'visible-state-only', 'slash-in-nicks', 'slash-in-hosts', 'underscore-in-hosts',
                               'freeform-nicks'}

        # Remove conf key checks for those not needed for Clientbot.
        self.conf_keys -= {'recvpass', 'sendpass', 'sid', 'sidrange', 'hostname'}

    def _get_UID(self, nick, ident=None, host=None, spawn_new=False):
        """
        Fetches the UID for the given nick, creating one if it does not already exist and spawn_new is True.

        To prevent message spoofing, this will only return an external (non-PyLink) client or the PyLink bot itself.
        """
        #log.debug('(%s) _get_UID: searching for nick %s', self.name, nick, stack_info=True)
        idsource = self.nick_to_uid(nick, filterfunc=lambda uid: uid == self.pseudoclient.uid or not self.is_internal_client(uid))

        if idsource is None and spawn_new:
            # If this sender doesn't already exist, spawn a new client.
            idsource = self.spawn_client(nick, ident or 'unknown', host or 'unknown',
                                         server=self.uplink, realname=FALLBACK_REALNAME).uid
        return idsource or nick  # Return input if missing per upstream spec

    def away(self, source, text):
        """STUB: sets away messages for internal clients."""
        log.debug('(%s) away: target is %s, internal client? %s', self.name, source, self.is_internal_client(source))

        if self.users[source].away != text:
            if not self.is_internal_client(source):
                log.debug('(%s) away: sending AWAY hook from %s with text %r', self.name, source, text)
                self.call_hooks([source, 'AWAY', {'text': text}])

            self.users[source].away = text

    def join(self, client, channel):
        """STUB: sends a virtual join (CLIENTBOT_JOIN) from the client to channel."""
        self._channels[channel].users.add(client)
        self.users[client].channels.add(channel)

        if self.pseudoclient and client != self.pseudoclient:
            log.debug('(%s) join: faking JOIN of client %s/%s to %s', self.name, client,
                      self.get_friendly_name(client), channel)
            self.call_hooks([client, 'CLIENTBOT_JOIN', {'channel': channel}])

    def kick(self, source, channel, target, reason=''):
        """STUB: rejoins users on kick attempts, for server transports where kicking users from channels is not implemented."""
        if not self.is_internal_client(target):
            log.info("(%s) Rejoining user %s to %s since kicks are not supported here.", self.name, target, channel)
            self.join(target, channel)
            self.call_hooks([None, 'JOIN', {'channel': channel, 'users': [target], 'modes': []}])
        elif channel in self.channels:
            self.channels[channel].remove_user(target)
            self.users[target].channels.discard(channel)
            self.call_hooks([source, 'CLIENTBOT_KICK', {'channel': channel, 'target': target, 'text': reason}])
        else:
            log.warning('(%s) Possible desync? Tried to kick() on non-existent channel %s', self.name, channel)

    def message(self, source, target, text, notice=False):
        """STUB: Sends messages to the target."""
        if self.pseudoclient and self.pseudoclient.uid != source:
            self.call_hooks([source, 'CLIENTBOT_MESSAGE', {'target': target, 'is_notice': notice, 'text': text}])

    def nick(self, source, newnick):
        """STUB: sends a virtual nick change (CLIENTBOT_NICK)."""
        assert source, "No source given?"
        self.call_hooks([source, 'CLIENTBOT_NICK', {'newnick': newnick}])
        self.users[source].nick = newnick

    def notice(self, source, target, text):
        """Sends notices to the target."""
        # Wrap around message(), which does all the text formatting for us.
        self.message(source, target, text, notice=True)

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """STUB: bursts joins from a server."""
        # This stub only updates the state internally with the users given. modes and TS are currently ignored.
        puids = {u[-1] for u in users}
        for user in puids:
            self.users[user].channels.add(channel)

        self._channels[channel].users |= puids
        nicks = {self.get_friendly_name(u) for u in puids}
        self.call_hooks([server, 'CLIENTBOT_SJOIN', {'channel': channel, 'nicks': nicks}])

    # Note: clientbot clients are initialized with umode +i by default
    def spawn_client(self, nick, ident='unknown', host='unknown.host', realhost=None, modes={('i', None)},
            server=None, ip='0.0.0.0', realname='', ts=None, opertype=None,
            manipulatable=False):
        """
        STUB: Pretends to spawn a new client with a subset of the given options.
        """

        server = server or self.sid
        uid = self.uidgen.next_uid(prefix=nick)

        ts = ts or int(time.time())

        log.debug('(%s) spawn_client stub called, saving nick %s as PUID %s', self.name, nick, uid)
        u = self.users[uid] = User(self, nick, ts, uid, server, ident=ident, host=host, realname=realname,
                                   manipulatable=manipulatable, realhost=realhost, ip=ip)
        self.servers[server].users.add(uid)

        self.apply_modes(uid, modes)

        return u

    def spawn_server(self, name, sid=None, uplink=None, desc=None, internal=True):
        """
        STUB: Pretends to spawn a new server with a subset of the given options.
        """
        if internal:
            # Use a custom pseudo-SID format for internal servers to prevent any server name clashes
            sid = self.sidgen.next_sid(prefix=name)
        else:
            # For others servers, just use the server name as the SID.
            sid = name

        self.servers[sid] = Server(self, uplink, name, internal=internal)
        return sid

    def squit(self, source, target, text):
        """STUB: SQUITs a server."""
        # What this actually does is just handle the SQUIT internally: i.e.
        # Removing pseudoclients and pseudoservers.
        squit_data = self._squit(source, 'CLIENTBOT_VIRTUAL_SQUIT', [target, text])

        if squit_data and squit_data.get('nicks'):
            self.call_hooks([source, 'CLIENTBOT_SQUIT', squit_data])

    def part(self, source, channel, reason=''):
        """STUB: Parts a user from a channel."""
        if self.pseudoclient and source == self.pseudoclient.uid:
            raise NotImplementedError("Explicitly leaving channels is not supported here.")
        self._channels[channel].remove_user(source)
        self.users[source].channels.discard(channel)
        self.call_hooks([source, 'CLIENTBOT_PART', {'channel': channel, 'text': reason}])

    def quit(self, source, reason):
        """STUB: Quits a client."""
        userdata = self._remove_client(source)
        self.call_hooks([source, 'CLIENTBOT_QUIT', {'text': reason, 'userdata': userdata}])

    def _stub(self, *args):
        """Stub outgoing command function (does nothing)."""
        return
    # Note: invite() and mode() are implemented in ClientbotWrapperProtocol below
    invite = mode = topic = topic_burst = _stub  # XXX: incomplete

    def _stub_raise(self, *args):
        """Stub outgoing command function (raises an error)."""
        raise NotImplementedError("Not supported on Clientbot")
    kill = knock = numeric = _stub_raise

    def update_client(self, target, field, text):
        """Updates the known ident, host, or realname of a client."""
        # Note: unlike other protocol modules, this function is also called as a helper to
        # update data for external clients.
        # Following this, we only want to send hook payloads if the target is an external client.
        if target not in self.users:
            log.warning("(%s) Unknown target %s for update_client()", self.name, target)
            return

        u = self.users[target]

        if field == 'IDENT' and u.ident != text:
            u.ident = text
            if not self.is_internal_client(target):
                self.call_hooks([self.sid, 'CHGIDENT',
                                   {'target': target, 'newident': text}])
        elif field == 'HOST' and u.host != text:
            u.host = text
            if not self.is_internal_client(target):
                self.call_hooks([self.sid, 'CHGHOST',
                                   {'target': target, 'newhost': text}])
        elif field in ('REALNAME', 'GECOS') and u.realname != text:
            u.realname = text
            if not self.is_internal_client(target):
                self.call_hooks([self.sid, 'CHGNAME',
                                   {'target': target, 'newgecos': text}])
        else:
            return  # Nothing changed

class ClientbotWrapperProtocol(ClientbotBaseProtocol, IRCCommonProtocol):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.protocol_caps |= {'ssl-should-verify'}

        self.has_eob = False

        # This is just a fallback. Actual casemapping is fetched by handle_005()
        self.casemapping = 'ascii'

        self._caps = {}
        self.ircv3_caps = set()
        self.ircv3_caps_available = {}

        # Tracks the users sent in a list of /who replies, so that users can be bursted all at once
        # when ENDOFWHO is received.
        self.who_received = set()

        # This stores channel->Timer object mappings for users that we're waiting for a kick
        # acknowledgement for. The timer is set to send a NAMES request to the uplink to prevent
        # things like failed KICK attempts from desyncing plugins like relay.
        self.kick_queue = {}

        # Aliases: 463 (ERR_NOPERMFORHOST), 464 (ERR_PASSWDMISMATCH), and 465 (ERR_YOUREBANNEDCREEP)
        # are essentially all fatal errors for connections.
        self.handle_463 = self.handle_464 = self.handle_465 = self.handle_error

        self._use_builtin_005_handling = True
        self._nick_fails = 0

        self.hook_map = {'ACCOUNT': 'CLIENT_SERVICES_LOGIN'}

    def post_connect(self):
        """Initializes a connection to a server."""
        # (Re)initialize counter-based pseudo UID generators
        super().post_connect()
        self.uidgen = PUIDGenerator('PUID')
        self.sidgen = PUIDGenerator('ClientbotInternalSID')

        self.has_eob = False
        ts = self.start_ts
        f = lambda text: self.send(text, queue=False)

        # Enumerate our own server
        self.sid = self.sidgen.next_sid()

        # Clear states from last connect
        self.who_received.clear()
        self.kick_queue.clear()
        self._caps.clear()
        self.ircv3_caps.clear()
        self.ircv3_caps_available.clear()

        sendpass = self.serverdata.get("sendpass")
        if sendpass:
            f('PASS %s' % sendpass)

        f('CAP LS 302')

        # Start a timer to call CAP END if registration freezes (e.g. if AUTHENTICATE for SASL is
        # never replied to).
        def _do_cap_end_wrapper():
            log.info('(%s) Skipping SASL due to timeout; are the IRCd and services configured '
                     'properly?', self.name)
            self._do_cap_end()
        self._cap_timer = threading.Timer(self.serverdata.get('sasl_timeout') or 15, _do_cap_end_wrapper)
        self._cap_timer.start()

        # Log in to IRC and set our irc.pseudoclient object.
        sbot = world.services['pylink']
        self._nick_fails = 0

        nick = sbot.get_nick(self)
        ident = sbot.get_ident(self)
        realname = sbot.get_realname(self)

        f('NICK %s' % nick)
        f('USER %s 8 * :%s' % (ident, realname))
        self.pseudoclient = User(self, nick, int(time.time()),
                                 self.uidgen.next_uid(prefix='@ClientbotInternal'), self.sid,
                                 ident=ident, realname=realname, host=self.hostname())
        self.users[self.pseudoclient.uid] = self.pseudoclient


    def invite(self, client, target, channel):
        """Invites a user to a channel."""
        self.send('INVITE %s %s' % (self.get_friendly_name(target), channel))

    def join(self, client, channel):
        """STUB: Joins a user to a channel."""

        # Only joins for the main PyLink client are actually forwarded. Others are ignored.
        # Note: we do not automatically add our main client to the channel state, as we
        # rely on the /NAMES reply to sync it up properly.
        if self.pseudoclient and client == self.pseudoclient.uid:
            self.send('JOIN %s' % channel)
        else:
            # Pass on a virtual JOIN as a hook
            super().join(client, channel)

    def kick(self, source, channel, target, reason=''):
        """Sends channel kicks."""

        log.debug('(%s) kick: checking if target %s (nick: %s) is an internal client? %s',
                  self.name, target, self.get_friendly_name(target),
                  self.is_internal_client(target))
        if self.is_internal_client(target) and (self.pseudoclient and source != self.pseudoclient.uid):
            # Target was one of our virtual clients. Just remove them from the state.
            self.handle_part(target, 'KICK', [channel, reason])

            # Send a KICK hook for message formatting.
            self.call_hooks([source, 'CLIENTBOT_KICK', {'channel': channel, 'target': target, 'text': reason}])
            return

        self.send('KICK %s %s :<%s> %s' % (channel, self._expandPUID(target),
                  self.get_friendly_name(source), reason))

        # Don't update our state here: wait for the IRCd to send an acknowledgement instead.
        # There is essentially a 3 second wait to do this, as we send NAMES with a delay
        # to resync any users lost due to kicks being blocked, etc.
        if (channel not in self.kick_queue) or (not self.kick_queue[channel][1].is_alive()):
            # However, only do this if there isn't a NAMES request scheduled already.
            t = threading.Timer(3, lambda: self.send('NAMES %s' % channel))
            log.debug('(%s) kick: setting NAMES timer for %s on %s', self.name, target, channel)

            # Store the channel, target UID, and timer object in the internal kick queue.
            self.kick_queue[channel] = ({target}, t)
            t.start()
        else:
            log.debug('(%s) kick: adding %s to kick queue for channel %s', self.name, target, channel)
            self.kick_queue[channel][0].add(target)

    def message(self, source, target, text, notice=False):
        """Sends messages to the target."""
        command = 'NOTICE' if notice else 'PRIVMSG'

        if self.pseudoclient and self.pseudoclient.uid == source:
            self.send('%s %s :%s' % (command, self._expandPUID(target), text))
        else:
            # Pass the message on as a hook
            super().message(source, target, text, notice=notice)

    def mode(self, source, channel, modes, ts=None):
        """Sends channel MODE changes."""
        if self.is_channel(channel):
            extmodes = []
            # Re-parse all channel modes locally to eliminate anything invalid, such as unbanning
            # things that were never banned. This prevents the bot from getting caught in a loop
            # with IRCd MODE acknowledgements.
            # FIXME: More related safety checks should be added for this.
            log.debug('(%s) mode: re-parsing modes %s', self.name, modes)
            joined_modes = self.join_modes(modes)
            for modepair in self.parse_modes(channel, joined_modes):
                log.debug('(%s) mode: checking if %s a prefix mode: %s', self.name, modepair, self.prefixmodes)
                if modepair[0][-1] in self.prefixmodes:
                    if self.is_internal_client(modepair[1]):
                        # Ignore prefix modes for virtual internal clients.
                        log.debug('(%s) mode: skipping virtual client prefixmode change %s', self.name, modepair)
                        continue
                    else:
                        # For other clients, change the mode argument to nick instead of PUID.
                        nick = self.get_friendly_name(modepair[1])
                        log.debug('(%s) mode: coersing mode %s argument to %s', self.name, modepair, nick)
                        modepair = (modepair[0], nick)
                extmodes.append(modepair)

            log.debug('(%s) mode: filtered modes for %s: %s', self.name, channel, extmodes)
            if extmodes:
                bufsize = self.S2S_BUFSIZE - len(':%s MODE %s ' % (self.get_hostmask(self.pseudoclient.uid), channel))
                for msg in self.wrap_modes(extmodes, bufsize, max_modes_per_msg=int(self._caps.get('MODES') or 0)):
                    self.send('MODE %s %s' % (channel, msg))
                    # Don't update the state here: the IRCd sill respond with a MODE reply if successful.

    def nick(self, source, newnick):
        """STUB: Sends NICK changes."""
        if self.pseudoclient and source == self.pseudoclient.uid:
            self.send('NICK :%s' % newnick)
            # No state update here: the IRCd will respond with a NICK acknowledgement if the change succeeds.
        else:
            super().nick(source, newnick)

    def _ping_uplink(self):
        """
        Sends a PING to the uplink.
        """
        if self.uplink:
            self.send('PING %s' % self.get_friendly_name(self.uplink))

            # Poll WHO periodically to figure out any ident/host/away status changes.
            for channel in self.pseudoclient.channels:
                self._send_who(channel)

            # Join persistent channels if always_autorejoin is enabled and there are any we're not in
            if self.serverdata.get('always_autorejoin') and self.has_cap('can-manage-bot-channels'):
                for channel in world.services['pylink'].get_persistent_channels(self):
                    if channel not in self.pseudoclient.channels:
                        log.info('(%s) Attempting to rejoin %s', self.name, channel)
                        self.join(self.pseudoclient.uid, channel)

    def part(self, source, channel, reason=''):
        """STUB: Parts a user from a channel."""
        self._channels[channel].remove_user(source)
        self.users[source].channels.discard(channel)

        # Only parts for the main PyLink client are actually forwarded. Others are ignored.
        if self.pseudoclient and source == self.pseudoclient.uid:
            self._channels[channel]._clientbot_part_requested = True
            self.send('PART %s :%s' % (channel, reason))
        else:
            super().part(source, channel, reason=reason)

    def sjoin(self, server, channel, users, ts=None, modes=set()):
        """STUB: bursts joins from a server."""
        # This stub only updates the state internally with the users
        # given. modes and TS are currently ignored.
        puids = {u[-1] for u in users}
        for user in puids:
            if self.pseudoclient and self.pseudoclient.uid == user:
                # If the SJOIN affects our main client, forward it as a regular JOIN.
                self.join(user, channel)
            else:
                # Otherwise, track the state for our virtual clients.
                self.users[user].channels.add(channel)

        self._channels[channel].users |= puids
        nicks = {self.get_friendly_name(u) for u in puids}
        self.call_hooks([server, 'CLIENTBOT_SJOIN', {'channel': channel, 'nicks': nicks}])

    def _set_account_name(self, uid, account):
        """
        Updates the user's account metadata.
        """
        if account is None:  # Ignore when account=None
            return
        elif account in ('*', '0'):  # No account
            account = ''

        if account != self.users[uid].services_account:
            self.call_hooks([uid, 'CLIENT_SERVICES_LOGIN', {'text': account}])

    def handle_events(self, data):
        """Event handler for the RFC1459/2812 (clientbot) protocol."""
        data = data.split(" ")

        tags = self.parse_message_tags(data)
        if tags:
            # If we have tags, split off the first argument.
            data = data[1:]

        try:
            args = self.parse_prefixed_args(data)
            sender = args[0]
            command = args[1]
            args = args[2:]

        except IndexError:
            # Raw command without an explicit sender; assume it's being sent by our uplink.
            args = self.parse_args(data)
            idsource = sender = self.uplink
            command = args[0]
            args = args[1:]
        else:
            # PyLink as a services framework expects UIDs and SIDs for everything. Since we connect
            # as a bot here, there's no explicit user introduction, so we're going to generate
            # pseudo-uids and pseudo-sids as we see prefixes.
            if ('!' not in sender) and '.' in sender:
                # Sender is a server name. XXX: make this check more foolproof
                assert '@' not in sender, "Incoming server name %r clashes with a PUID!" % sender
                if sender not in self.servers:
                    self.spawn_server(sender, internal=False)
                idsource = sender
            else:
                # Sender is a either a nick or a nick!user@host prefix. Split it into its relevant parts.
                try:
                    nick, ident, host = utils.split_hostmask(sender)
                except ValueError:
                    ident = host = None  # Set ident and host as null for now.
                    nick = sender  # Treat the sender prefix we received as a nick.
                idsource = self._get_UID(nick, ident, host, spawn_new=True)

        if idsource in self.users:
            # Handle IRCv3.2 account-tag.
            self._set_account_name(idsource, tags.get('account'))

        try:
            func = getattr(self, 'handle_'+command.lower())
        except AttributeError:  # unhandled command
            pass
        else:
            parsed_args = func(idsource, command, args)
            if parsed_args is not None:
                parsed_args['tags'] = tags  # Add message tags to this dict.
                return [idsource, command, parsed_args]

    def _do_cap_end(self):
        """
        Abort SASL login by sending CAP END.
        """
        self.send('CAP END')
        log.debug("(%s) Stopping CAP END timer.", self.name)
        self._cap_timer.cancel()

    def _try_sasl_auth(self):
        """
        Starts an authentication attempt via SASL. This returns True if SASL
        is enabled and correctly configured, and False otherwise.
        """
        if 'sasl' not in self.ircv3_caps:
            log.info("(%s) Skipping SASL auth since the IRCd doesn't support it.", self.name)
            return

        sasl_mech = self.serverdata.get('sasl_mechanism')
        if sasl_mech:
            sasl_mech = sasl_mech.upper()
            sasl_user = self.serverdata.get('sasl_username')
            sasl_pass = self.serverdata.get('sasl_password')
            ssl_cert = self.serverdata.get('ssl_certfile')
            ssl_key = self.serverdata.get('ssl_keyfile')
            ssl = self.serverdata.get('ssl')

            if sasl_mech == 'PLAIN':
                if not (sasl_user and sasl_pass):
                    log.warning("(%s) Not attempting PLAIN authentication; sasl_username and/or "
                                "sasl_password aren't correctly set.", self.name)
                    return False
            elif sasl_mech == 'EXTERNAL':
                if not ssl:
                    log.warning("(%s) Not attempting EXTERNAL authentication; SASL external requires "
                                "SSL, but it isn't enabled.", self.name)
                    return False
                elif not (ssl_cert and ssl_key):
                    log.warning("(%s) Not attempting EXTERNAL authentication; ssl_certfile and/or "
                                "ssl_keyfile aren't correctly set.", self.name)
                    return False
            else:
                log.warning('(%s) Unsupported SASL mechanism %s; aborting SASL.', self.name, sasl_mech)
                return False
            self.send('AUTHENTICATE %s' % sasl_mech, queue=False)
            return True
        return False

    def _send_auth_chunk(self, data):
        """Send Base64 encoded SASL authentication chunks."""
        enc_data = base64.b64encode(data).decode()
        self.send('AUTHENTICATE %s' % enc_data, queue=False)

    def handle_authenticate(self, source, command, args):
        """
        Handles AUTHENTICATE, or SASL authentication requests from the server.
        """
        # Client: AUTHENTICATE PLAIN
        # Server: AUTHENTICATE +
        # Client: AUTHENTICATE ...
        if not args:
            return
        if args[0] == '+':
            sasl_mech = self.serverdata['sasl_mechanism'].upper()
            if sasl_mech == 'PLAIN':
                sasl_user = self.serverdata['sasl_username']
                sasl_pass = self.serverdata['sasl_password']
                authstring = '%s\0%s\0%s' % (sasl_user, sasl_user, sasl_pass)
                self._send_auth_chunk(authstring.encode('utf-8'))
            elif sasl_mech == 'EXTERNAL':
                self.send('AUTHENTICATE +')

    def handle_900(self, source, command, args):
        """
        Handles SASL RPL_LOGGEDIN numerics.
        """
        # <- :charybdis.midnight.vpn 900 ice ice!pylink@localhost ice :You are now logged in as ice
        # <- :server 900 <nick> <nick>!<ident>@<host> <account> :You are now logged in as <user>

        self.pseudoclient.services_account = args[2]
        log.info('(%s) SASL authentication successful: now logged in as %s', self.name, args[2])

        # Note: we don't send a hook here yet; is doing so for the bot this early in login
        # really necessary?

    def handle_904(self, source, command, args):
        """
        Handles SASL authentication status reports.
        """
        # <- :charybdis.midnight.vpn 903 ice :SASL authentication successful
        logfunc = log.debug if command == '903' else log.warning
        logfunc('(%s) %s', self.name, args[-1])
        if not self.has_eob:
            # End the pre-login CAP stuff regardless of whether SASL was successful.
            self._do_cap_end()
    handle_903 = handle_902 = handle_905 = handle_906 = handle_907 = handle_904

    def _request_ircv3_caps(self):
        # Filter the capabilities we want by the ones actually supported by the server.
        available_caps = {cap for cap in IRCV3_CAPABILITIES if cap in self.ircv3_caps_available}
        # And by the ones we don't already have.
        caps_wanted = available_caps - self.ircv3_caps

        log.debug('(%s) Requesting IRCv3 capabilities %s (available: %s)', self.name, caps_wanted, available_caps)
        if caps_wanted:
            self.send('CAP REQ :%s' % ' '.join(caps_wanted), queue=False)

    def handle_cap(self, source, command, args):
        """
        Handles IRCv3 capabilities transmission.
        """
        subcmd = args[1]

        if subcmd == 'LS':
            # Server: CAP * LS * :multi-prefix extended-join account-notify batch invite-notify tls
            # Server: CAP * LS * :cap-notify server-time example.org/dummy-cap=dummyvalue example.org/second-dummy-cap
            # Server: CAP * LS :userhost-in-names sasl=EXTERNAL,DH-AES,DH-BLOWFISH,ECDSA-NIST256P-CHALLENGE,PLAIN
            log.debug('(%s) Got new capabilities %s', self.name, args[-1])
            self.ircv3_caps_available.update(self.parse_isupport(args[-1], None))
            if args[2] != '*':
                self._request_ircv3_caps()

        elif subcmd == 'ACK':
            # Server: CAP * ACK :multi-prefix sasl
            newcaps = set(args[-1].split())
            log.debug('(%s) Received ACK for IRCv3 capabilities %s', self.name, newcaps)
            self.ircv3_caps |= newcaps

            # Only send CAP END immediately if SASL is disabled. Otherwise, wait for the 90x responses
            # to do so.
            if not self._try_sasl_auth():
                if not self.has_eob:
                    self._do_cap_end()
        elif subcmd == 'NAK':
            log.warning('(%s) Got NAK for IRCv3 capabilities %s, even though they were supposedly available',
                        self.name, args[-1])
            if not self.has_eob:
                self._do_cap_end()
        elif subcmd == 'NEW':
            # :irc.example.com CAP modernclient NEW :batch
            # :irc.example.com CAP tester NEW :away-notify extended-join
            # Note: CAP NEW allows capabilities with values (e.g. sasl=mech1,mech2), while CAP DEL
            # does not.
            log.debug('(%s) Got new capabilities %s', self.name, args[-1])
            newcaps = self.parse_isupport(args[-1], None)
            self.ircv3_caps_available.update(newcaps)
            self._request_ircv3_caps()

            # Attempt SASL auth routines when sasl is added/removed, if doing so is enabled.
            if 'sasl' in newcaps and self.serverdata.get('sasl_reauth'):
                log.debug('(%s) Attempting SASL reauth due to CAP NEW', self.name)
                self._try_sasl_auth()

        elif subcmd == 'DEL':
            # :irc.example.com CAP modernclient DEL :userhost-in-names multi-prefix away-notify
            log.debug('(%s) Removing capabilities %s', self.name, args[-1])
            for cap in args[-1].split():
                # Remove the capabilities from the list available, and return None (ignore) if any fail
                self.ircv3_caps_available.pop(cap, None)
                self.ircv3_caps.discard(cap)

    def handle_001(self, source, command, args):
        """
        Handles 001 / RPL_WELCOME.
        """
        # enumerate our uplink
        self.uplink = source

    def handle_376(self, source, command, args):
        """
        Handles end of MOTD numerics, used to start things like autoperform.
        """

        # Run autoperform commands.
        for line in self.serverdata.get("autoperform", []):
            # Expand substitutions like $nick, $ident, $host
            tmpl = string.Template(line)

            args = self.pseudoclient.get_fields()

            log.debug('(%s) handle_376: bot user fields are %s', self.name, args)
            line = tmpl.safe_substitute(**args)
            self.send(line)

        # Virtual endburst hook.
        self.connected.set()  # Note, this should always be set before the actual ENDBURST hook
        self.servers[source].has_eob = True

        return {'parse_as': 'ENDBURST'}

    handle_422 = handle_376

    def handle_353(self, source, command, args):
        """
        Handles 353 / RPL_NAMREPLY.
        """
        # <- :charybdis.midnight.vpn 353 ice = #test :ice @jlu5

        # Mark "@"-type channels as secret automatically, per RFC2812.
        channel = args[2]
        if args[1] == '@':
            self.apply_modes(channel, [('+s', None)])

        names = set()
        modes = set()
        prefix_to_mode = {v:k for k, v in self.prefixmodes.items()}
        prefixes = ''.join(self.prefixmodes.values())

        # N.B. only split on spaces because of color in hosts nonsense...
        # str.split() by default treats \x1f as whitespace
        for name in args[-1].strip().split(' '):
            nick = name.lstrip(prefixes)

            # Handle userhost-in-names where available.
            ident = host = None
            if 'userhost-in-names' in self.ircv3_caps:
                try:
                    nick, ident, host = utils.split_hostmask(nick)
                except ValueError:
                    log.exception('(%s) Failed to split hostmask %r from /names reply on %s; args=%s', self.name, nick, channel, args)
                    # If error, leave nick unsplit

            if not nick:
                continue

            # Get the PUID for the given nick. If one doesn't exist, spawn
            # a new virtual user.
            idsource = self._get_UID(nick, ident=ident, host=host, spawn_new=True)

            # Queue these virtual users to be joined if they're not already in the channel,
            # or we're waiting for a kick acknowledgment for them.
            if (idsource not in self._channels[channel].users) or (idsource in \
                    self.kick_queue.get(channel, ([],))[0]):
                names.add(idsource)
            self.users[idsource].channels.add(channel)
            if host:
                self.users[idsource]._clientbot_identhost_received = True

            # Process prefix modes
            for char in name:
                if char in self.prefixmodes.values():
                    modes.add(('+' + prefix_to_mode[char], idsource))
                else:
                    break

        # Statekeeping: make sure the channel's user list is updated!
        self._channels[channel].users |= names
        self.apply_modes(channel, modes)

        log.debug('(%s) handle_353: adding users %s to %s', self.name, names, channel)
        log.debug('(%s) handle_353: adding modes %s to %s', self.name, modes, channel)

        # Send JOIN hook payloads only for users that we know the ident@host of already.
        # This is mostly used to resync kicked Clientbot users that can't actually be kicked
        # after a delay.
        if names and hasattr(self.channels[channel], '_clientbot_initial_who_received'):
            log.debug('(%s) handle_353: sending JOIN hook because /WHO was already received for %s',
                      self.name, channel)
            return {'channel': channel, 'users': names, 'modes': self._channels[channel].modes,
                    'parse_as': "JOIN"}

    def _send_who(self, channel):
        """Sends /WHO to a channel, with WHOX args if that is supported."""
        # Note: %% = escaped %
        # %cuhsnfdr is the default; adding 'a' to it sends the account name.
        # 'd' is omitted because we don't really care about hop count.
        if 'WHOX' in self._caps:
            self.send('WHO %s %%cuhsnfar' % channel)
        else:
            self.send('WHO %s' % channel)

    def handle_352(self, source, command, args):
        """
        Handles 352 / RPL_WHOREPLY.
        """
        # parameter count:               0   1     2       3         4                      5   6  7(-1)
        # <- :charybdis.midnight.vpn 352 ice #test ~pylink 127.0.0.1 charybdis.midnight.vpn ice H+ :0 PyLink
        # <- :charybdis.midnight.vpn 352 ice #test ~jlu5 127.0.0.1 charybdis.midnight.vpn jlu5 H*@ :0 realname
        # with WHO %cuhsnfar (WHOX) - note, hopcount and realname are separate!
        #                                0   1     2   3         4                      5  6  7   8(-1)
        # <- :charybdis.midnight.vpn 354 ice #test ~jlu5 localhost charybdis.midnight.vpn jlu5 H*@ jlu5 :realname
        channel = args[1]
        ident = args[2]
        host = args[3]
        nick = args[5]
        status = args[6]

        # Hopcount and realname field are together in regular WHO. We only care about the latter.
        realname = args[-1]
        if command == '352':
            realname = realname.split(' ', 1)[-1]

        uid = self._get_UID(nick, spawn_new=False)

        if uid is None:
            log.debug("(%s) Ignoring extraneous /WHO info for %s", self.name, nick)
            return

        self.update_client(uid, 'IDENT', ident)
        self.update_client(uid, 'HOST', host)
        self.update_client(uid, 'GECOS', realname)
        self.users[uid]._clientbot_identhost_received = True

        # The status given uses the following letters: <H|G>[*][@|+]
        # H means here (not marked /away)
        # G means away is set (we'll have to fake a message because it's not given)
        # * means IRCop.
        # The rest are prefix modes. Multiple can be given by the IRCd if multiple are set
        log.debug('(%s) handle_352: status string on user %s: %s', self.name, nick, status)
        if status[0] == 'G':
            if not self.users[uid].away:
                # Only set away status if not previously set
                log.debug('(%s) handle_352: calling away() with argument', self.name)
                self.away(uid, 'Away')
        elif status[0] == 'H':
            if self.users[uid].away:
                log.debug('(%s) handle_352: calling away() without argument', self.name)
                self.away(uid, '')  # Unmark away status, but only if /away was previously set
        else:
            log.warning('(%s) handle_352: got wrong string %s for away status', self.name, status[0])

        if command == '354' and len(args) >= 9:  # WHOX account
            account = args[7]
            log.debug('(%s) handle_354: got account %r for %s', self.name, account, uid)

            self._set_account_name(uid, account)

        if self.serverdata.get('track_oper_statuses'):
            if '*' in status:  # Track IRCop status
                if not self.is_oper(uid):
                    # Don't send duplicate oper ups if the target is already oper.
                    self.apply_modes(uid, [('+o', None)])
                    self.call_hooks([uid, 'MODE', {'target': uid, 'modes': {('+o', None)}}])
                    self.call_hooks([uid, 'CLIENT_OPERED', {'text': 'IRC Operator'}])
            elif self.is_oper(uid) and not self.is_internal_client(uid):
                # Track deopers
                self.apply_modes(uid, [('-o', None)])
                self.call_hooks([uid, 'MODE', {'target': uid, 'modes': {('-o', None)}}])

        self.who_received.add(uid)
    handle_354 = handle_352  # 354 = RPL_WHOSPCRPL, used by WHOX

    def handle_315(self, source, command, args):
        """
        Handles 315 / RPL_ENDOFWHO.
        """
        # <- :charybdis.midnight.vpn 315 ice #test :End of /WHO list.
        # Join all the users in which the last batch of /who requests were received.
        users = self.who_received.copy()
        self.who_received.clear()

        channel = args[1]
        c = self._channels[channel]

        modes = set(c.modes)
        bursted_before = hasattr(c, '_clientbot_initial_who_received')

        queued_users = []
        for user in users.copy():
            # Fill in prefix modes of everyone when doing mock SJOIN.
            try:
                for mode in c.get_prefix_modes(user):
                    modechar = self.cmodes.get(mode)
                    log.debug('(%s) handle_315: adding mode %s +%s %s', self.name, mode, modechar, user)
                    if modechar:
                        modes.add((modechar, user))
            except KeyError as e:
                log.debug("(%s) Ignoring KeyError (%s) from WHO response; it's probably someone we "
                          "don't share any channels with", self.name, e)

            if bursted_before and user in c.users:
                log.debug("(%s) Skipping join of %s/%s to %r", self.name, user,
                          self.get_friendly_name(user), channel)
                continue
            queued_users.append(user)

        c._clientbot_initial_who_received = True
        if queued_users:
            return {'channel': channel, 'users': users, 'modes': modes,
                    'parse_as': "JOIN"}

    def handle_433(self, source, command, args):
        # <- :millennium.overdrivenetworks.com 433 * ice :Nickname is already in use.

        self._nick_fails += 1
        newnick = self.pseudoclient.nick = world.services['pylink'].get_nick(self, fails=self._nick_fails)
        log.debug('(%s) _nick_fails = %s, trying new nick %r', self.name, self._nick_fails, newnick)

        self.send('NICK %s' % newnick)
    handle_432 = handle_437 = handle_433

    def handle_account(self, source, command, args):
        """
        Handles IRCv3 account-notify messages.
        """
        # <- :nick!user@host ACCOUNT accountname
        # <- :nick!user@host ACCOUNT *

        self._set_account_name(source, args[0])

    def handle_join(self, source, command, args):
        """
        Handles incoming JOINs, as well as JOIN acknowledgements for us.
        """
        # Classic format:
        # <- :jlu5|!~jlu5@127.0.0.1 JOIN #whatever
        # With extended-join:
        # <- :jlu5|!~jlu5@127.0.0.1 JOIN #whatever accountname :realname
        channel = args[0]
        self._channels[channel].users.add(source)
        self.users[source].channels.add(channel)

        if len(args) >= 3:
            self._set_account_name(source, args[1])
            # Hmm, because _get_UID only looks at the sender prefix, it doesn't
            # have a way to process the realname info from JOIN yet...
            self.update_client(source, 'GECOS', args[2])

        # Only fetch modes, TS, and user hosts once we're actually in the channel.
        # The IRCd will send us a JOIN with our nick!user@host if our JOIN succeeded.
        if self.pseudoclient and source == self.pseudoclient.uid:
            self.send('MODE %s' % channel)
            self._send_who(channel)

            if self.serverdata.get('fetch_ban_lists', False):
                self.send('MODE %s +b' % channel)

                for m in ('banexception', 'invex'):
                    if m in self.cmodes:
                        self.send('MODE %s +%s' % (channel, self.cmodes[m]))
        else:
            self.call_hooks([source, 'CLIENTBOT_JOIN', {'channel': channel}])
            return {'channel': channel, 'users': [source], 'modes': self._channels[channel].modes}

    def handle_kick(self, source, command, args):
        """
        Handles incoming KICKs.
        """
        # <- :jlu5!~jlu5@127.0.0.1 KICK #whatever jlu5| :xd
        channel = args[0]
        target = self._get_UID(args[1], spawn_new=False)

        try:
            reason = args[2]
        except IndexError:
            reason = ''

        if channel in self.kick_queue:
            # Remove this client from the kick queue if present there.
            log.debug('(%s) kick: removing %s from kick queue for channel %s', self.name, target, channel)
            self.kick_queue[channel][0].discard(target)

            if not self.kick_queue[channel][0]:
                log.debug('(%s) kick: cancelling kick timer for channel %s (all kicks accounted for)', self.name, channel)
                # There aren't any kicks that failed to be acknowledged. We can remove the timer now
                self.kick_queue[channel][1].cancel()
                del self.kick_queue[channel]

        # Statekeeping: remove the target from the channel they were previously in.
        self._channels[channel].remove_user(target)
        try:
            self.users[target].channels.remove(channel)
        except KeyError:
            pass

        # Don't repeat hooks if we're the kicker, unless we're also the target.
        if self.is_internal_client(source) or self.is_internal_server(source):
            if self.pseudoclient and target != self.pseudoclient.uid:
                return
        return {'channel': channel, 'target': target, 'text': reason}

    def handle_mode(self, source, command, args):
        """Handles MODE changes."""
        # <- :jlu5!~jlu5@127.0.0.1 MODE #dev +v ice
        # <- :ice MODE ice :+Zi
        target = args[0]
        if self.is_channel(target):
            oldobj = self._channels[target].deepcopy()
        else:
            target = self._get_UID(target, spawn_new=False)
            oldobj = None
        modes = args[1:]
        changedmodes = self.parse_modes(target, modes)
        self.apply_modes(target, changedmodes)

        if self.is_internal_client(target):
            log.debug('(%s) Suppressing MODE change hook for internal client %s', self.name, target)
            return
        if changedmodes:
            # Prevent infinite loops: don't send MODE hooks if the sender is US.
            # Note: this is not the only check in Clientbot to prevent mode loops: if our nick
            # somehow gets desynced, this may not catch everything it's supposed to.
            if (self.pseudoclient and source != self.pseudoclient.uid) or not self.pseudoclient:
                return {'target': target, 'modes': changedmodes, 'channeldata': oldobj}

    def handle_324(self, source, command, args):
        """Handles MODE announcements via RPL_CHANNELMODEIS (i.e. the response to /mode #channel)"""
        # -> MODE #test
        # <- :midnight.vpn 324 jlu5 #test +nt
        # <- :midnight.vpn 329 jlu5 #test 1491773459
        channel = args[1]
        modes = args[2:]
        log.debug('(%s) Got RPL_CHANNELMODEIS (324) modes %s for %s', self.name, modes, channel)

        # Sometimes IRCds suppress arguments to +lk, so ignore missing args
        changedmodes = self.parse_modes(channel, modes, ignore_missing_args=True)

        self.apply_modes(channel, changedmodes)

    def handle_329(self, source, command, args):
        """Handles TS announcements via RPL_CREATIONTIME."""
        channel = args[1]
        ts = int(args[2])
        self._channels[channel].ts = ts

    def handle_chghost(self, source, command, args):
        """Handles the IRCv3 CHGHOST command."""
        # <- :nick!user@host CHGHOST ident new.host

        ident = self.users[source].ident
        host = self.users[source].host

        self.users[source].ident = newident = args[0]
        self.users[source].host = newhost = args[1]

        if ident != newident:
            self.call_hooks([source, 'CHGIDENT',
                             {'target': source, 'newident': newident}])

        if host != newhost:
            self.call_hooks([source, 'CHGHOST',
                             {'target': source, 'newhost': newhost}])

    def handle_nick(self, source, command, args):
        """Handles NICK changes."""
        # <- :jlu5|!~jlu5@127.0.0.1 NICK :jlu5_
        newnick = args[0]

        if not self.connected.is_set():
            # We haven't properly logged on yet, so any initial NICK should be treated as a forced
            # nick change for us. For example, this clause is used to handle forced nick changes
            # sent by ZNC, when the login nick and the actual IRC nick of the bouncer differ.
            self.pseudoclient.nick = newnick
            log.debug('(%s) Pre-auth FNC: Changing our nick to %s', self.name, args[0])
            return
        elif source == self.pseudoclient.uid:
            self._nick_fails = 0  # Our last nick change succeeded.

        oldnick = self.users[source].nick

        self.users[source].nick = newnick

        return {'newnick': newnick, 'oldnick': oldnick}

    def handle_part(self, source, command, args):
        """
        Handles incoming PARTs.
        """
        # <- :jlu5|!~jlu5@127.0.0.1 PART #whatever
        channels = args[0].split(',')
        try:
            reason = args[1]
        except IndexError:
            reason = ''

        for channel in channels:
            self._channels[channel].remove_user(source)
        self.users[source].channels -= set(channels)

        # Only send the PART hook for parts not initiated by us - this is for consistency with other
        # protocols
        notify_channels = []
        for channel in channels:
            is_part_requested = getattr(self._channels[channel], '_clientbot_part_requested', False)
            if is_part_requested:
                log.debug('(%s) clientbot.handle_part: not forwarding part hook for %s since we requested it', self.name, channel)
                self._channels[channel]._clientbot_part_requested = False
                continue
            else:
                notify_channels.append(channel)

        if notify_channels:
            log.debug('(%s) clientbot.handle_part: returning part hook for %s (original: %s)', self.name, notify_channels, channels)
            return {'channels': notify_channels, 'text': reason}

    def handle_ping(self, source, command, args):
        """
        Handles incoming PING requests.
        """
        self.send('PONG :%s' % args[0], queue=False)

    def handle_privmsg(self, source, command, args):
        """Handles incoming PRIVMSG/NOTICE."""
        # <- :sender PRIVMSG #dev :afasfsa
        # <- :sender NOTICE somenick :afasfsa
        target = args[0]

        if self.is_internal_client(source) or self.is_internal_server(source):
            log.warning('(%s) Received %s to %s being routed the wrong way!', self.name, command, target)
            return

        real_target = target.lstrip(''.join(self.prefixmodes.values()))
        if not self.is_channel(real_target):
            target = self._get_UID(target, spawn_new=False)

        if target:
            return {'target': target, 'text': args[1]}
    handle_notice = handle_privmsg

    def handle_quit(self, source, command, args):
        """Handles incoming QUITs."""
        if self.pseudoclient and source == self.pseudoclient.uid:
            # Someone faked a quit from us? We should abort.
            raise ProtocolError("Received QUIT from uplink (%s)" % args[0])
        elif source not in self.users:
            log.debug('(%s) Ignoring QUIT on non-existent user %s', self.name, source)
            return

        userdata = self.users[source]
        self.quit(source, args[0])
        return {'text': args[0], 'userdata': userdata}

    def handle_404(self, source, command, args):
        """
        Handles ERR_CANNOTSENDTOCHAN and other similar numerics.
        """
        # <- :some.server 404 james #test :Cannot send to channel
        if len(args) >= 2 and self.is_channel(args[1]):
            channel = args[1]
            f = log.warning

            if channel not in self.channels:
                return

            # Don't send the warning multiple times to prevent flood if the target
            # is a log chan.
            if hasattr(self.channels[channel], '_clientbot_cannot_send_warned'):
                f = log.debug
            f('(%s) Failed to send message to %s: %s', self.name, channel, args[-1])

            self.channels[channel]._clientbot_cannot_send_warned = True

    # 408: ERR_NOCOLORSONCHAN on Bahamut, ERR_NOCTRLSONCHAN on Hybrid
    handle_408 = handle_404
    # 492: ERR_NOCTCP on Hybrid
    handle_492 = handle_404

    def handle_367(self, source, command, args, banmode='b'):
        """
        Handles RPL_BANLIST, used to enumerate bans.
        """
        # <- :irc3.lose-the-game.nat 367 james #test *!*@1.2.3.4 james 1504560159
        channel = args[1]
        target = args[2]
        if channel not in self.channels:
            log.warning('(%s) got ban mode +%s %s on unknown channel %s?', self.name, banmode, target, channel)
        else:
            # Just apply the mode; we send out a mode hook only when the corresponding ban list has finished sending.
            self.apply_modes(channel, [('+%s' % banmode, target)])

    def handle_368(self, source, command, args, banmode='b'):
        """
        Handles RPL_ENDOFBANLIST, used to end off ban lists.
        """
        # <- :irc3.lose-the-game.nat 368 james #test :End of Channel Ban List
        channel = args[1]
        if channel not in self.channels:
            return

        modes = [('+%s' % banmode, m[1]) for m in self.channels[channel].modes if m[0] == banmode]

        # Send out the hook. We don't worry about repeats since these modes don't need to be
        # enumerated more than once per JOIN anyways.
        if modes:
            return {'target': channel, 'parse_as': 'MODE',
                    'modes': modes}

    def handle_346(self, *args):
        """
        Handles RPL_INVITELIST, used to enumerate invite exceptions.
        """
        return self.handle_367(*args, banmode=self.cmodes.get('invex', 'I'))

    def handle_347(self, *args):
        """
        Handles RPL_ENDOFINVITELIST, used to end off invite exception lists.
        """
        if 'invex' not in self.cmodes:
            log.warning('(%s) Got 347 / RPL_ENDOFINVITELIST even though invex is not a registered mode?', self.name)
        return self.handle_368(*args, banmode=self.cmodes.get('invex', 'I'))

    def handle_348(self, *args):
        """
        Handles RPL_EXCEPTLIST, used to enumerate ban exceptions.
        """
        return self.handle_367(*args, banmode=self.cmodes.get('banexception', 'e'))

    def handle_349(self, *args):
        """
        Handles RPL_ENDOFEXCEPTLIST, used to end off ban exception lists.
        """
        if 'banexception' not in self.cmodes:
            log.warning('(%s) Got 349 / RPL_ENDOFEXCEPTLIST even though banexception is not a registered mode?', self.name)
        return self.handle_368(*args, banmode=self.cmodes.get('banexception', 'e'))

    def handle_471(self, source, command, args):
        """
        Handles numerics commonly sent when a client fails to join a channel:

        * ERR_TOOMANYCHANNELS (405)
        * ERR_CHANNELISFULL (471)
        * ERR_INVITEONLYCHAN (473)
        * ERR_BANNEDFROMCHAN (474)
        * ERR_BADCHANNELKEY (475)
        * ERR_BADCHANMASK (476)
        * ERR_NEEDREGGEDNICK (477)
        * ERR_BADCHANNAME (479)
        * ERR_SECUREONLYCHAN / ERR_SSLONLYCHAN (489)
        * ERR_DELAYREJOIN (495)
        * ERR_OPERONLY (520)
        """

        if len(args) >= 3 and self.is_channel(args[1]):
            log.warning('(%s) Failed to join channel %s: %s', self.name, args[1], args[-1])

    handle_405 = handle_473 = handle_474 = handle_475 = handle_476 = handle_477 = \
        handle_479 = handle_489 = handle_495 = handle_520 = handle_471

Class = ClientbotWrapperProtocol
