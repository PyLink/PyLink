# PyLink Protocol Module Specification

In PyLink, each protocol module is a single file consisting of a protocol class, and a global `Class` attribute that is set equal to it (e.g. `Class = InspIRCdProtocol`). These classes should be based off of either [`classes.Protocol`](https://github.com/GLolol/PyLink/blob/e4fb64aebaf542122c70a8f3a49061386a00b0ca/classes.py#L532), a boilerplate class that only defines a few basic things, or [`ts6_common.TS6BaseProtocol`](https://github.com/GLolol/PyLink/blob/0.5.0-dev/protocols/ts6_common.py), which includes elements of the TS6 protocol that are shared by the InspIRCd, UnrealIRCd, and TS6 protocols. IRC objects load protocol modules by creating an instance of its main class, and sends it commands accordingly.

See also: [inspircd.html](inspircd.html) for auto-generated documentation the InspIRCd protocol module.

## Tasks

Protocol modules have some very important jobs. If any of these aren't done correctly, you will be left with a broken, desynced services server:

1) Handle incoming commands from the uplink IRCd.

2) Return [hook data](hooks-reference.md) for relevant commands, so that plugins can receive data from IRC.

3) Make sure channel/user states are kept correctly. Joins, quits, parts, kicks, mode changes, nick changes, etc. should all be handled accurately.

4) Respond to both pings *and* pongs - the `irc.lastping` attribute **must** be set to the current time whenever a `PONG` is received from the uplink, so PyLink's doesn't [lag out the uplink thinking that it isn't responding to our pings](https://github.com/GLolol/PyLink/blob/e4fb64aebaf542122c70a8f3a49061386a00b0ca/classes.py#L309-L311).

5) Implement a series of camelCase `commandServer/Client` functions - plugins use these for sending outgoing commands. See the `Outbound commands` section below for a list of which ones are needed.

6) Set the threading.Event object `irc.connected` (via `irc.connected.set()`) when the protocol negotiation with the uplink is complete. This is important for plugins like relay which must check that links are ready before spawning clients, and they will fail to work if this is not set.

## Core functions

The following functions *must* be implemented by any protocol module within its main class, since they are used by the IRC object internals.

- **`connect`**`(self)` - Initializes a connection to a server.

- **`handle_events`**`(self, line)` - Handles inbound data (lines of text) from the uplink IRC server. Normally, this will pass commands to other command handlers within the protocol module, while dropping commands that are unrecognized (wildcard handling). But, it's really up to you how to structure your modules. You will want to be able to parse command arguments properly into a list: many protocols send RFC1459-style commands that can be parsed using the [`Protocol.parseArgs()`](https://github.com/GLolol/PyLink/blob/e4fb64aebaf542122c70a8f3a49061386a00b0ca/classes.py#L539) function.

### Outgoing command functions

- **`spawnClient`**`(self, nick, ident='null', host='null', realhost=None, modes=set(), server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None, manipulatable=False)` - Spawns a client on the PyLink server. No nick collision / valid nickname checks are done by protocol modules, as it is up to plugins to make sure they don't introduce anything invalid.
    - `modes` is a set of `(mode char, mode arg)` tuples in the form of [`utils.parseModes()` output](using-utils.md#parseModes).
    - `ident` and `host` default to "null", while `realhost` defaults to the same things as `host` if not defined.
    - `realname` defaults to the real name specified in the PyLink config, if not given.
    - `ts` defaults to the current time if not given.
    - `opertype` (the oper type name, if applicable) defaults to the simple text of `IRC Operator`.
    - The `manipulatable` option toggles whether the client spawned should be considered protected. Currently, all this does is prevent commands from plugins like `bots` from modifying these clients, but future client protections (anti-kill flood, etc.) may also depend on this.
    - The `server` option optionally takes a SID of any PyLink server, and spawns the client on the one given. It will default to the root PyLink server.

- **`joinClient`**`(self, client, channel)` - Joins the given client UID given to a channel.

- **`awayClient`**`(self, source, text)` - Sends an AWAY message from a PyLink client. `text` can be an empty string to unset AWAY status.

- **`inviteClient`**`(self, source, target, channel)` - Sends an INVITE from a PyLink client.

- **`kickClient`**`(self, source, channel, target, reason=None)` - Sends a kick from a PyLink client.

- **`kickServer`**`(self, source, channel, target, reason=None)` - Sends a kick from a PyLink server.

- **`killClient`**`(self, source, target, reason)` - Sends a kill from a PyLink client.

- **`killServer`**`(self, source, target, reason)` - Sends a kill from a PyLink server.

- **`knockClient`**`(self, source, target, text)` - Sends a KNOCK from a PyLink client.

- **`messageClient`**`(self, source, target, text)` - Sends a PRIVMSG from a PyLink client.

- **`modeClient`**`(self, source, target, modes, ts=None)` - Sends modes from a PyLink client. `modes` takes a set of `([+/-]mode char, mode arg)` tuples.

- **`modeServer`**`(self, source, target, modes, ts=None)` - Sends modes from a PyLink server.

- **`nickClient`**`(self, source, newnick)` - Changes the nick of a PyLink client.

- **`noticeClient`**`(self, source, target, text)` - Sends a NOTICE from a PyLink client.

- **`numericServer`**`(self, source, numeric, target, text)` - Sends a raw numeric `numeric` with `text` from the `source` server to `target`.

- **`partClient`**`(self, client, channel, reason=None)` - Sends a part from a PyLink client.

- **`pingServer`**`(self, source=None, target=None)` - Sends a PING to a target server. Periodic PINGs are sent to our uplink automatically by the [`Irc()`
internals](https://github.com/GLolol/PyLink/blob/0.4.0-dev/classes.py#L267-L272); plugins shouldn't have to use this.

- **`quitClient`**`(self, source, reason)` - Quits a PyLink client.

- **`sjoinServer`**`(self, server, channel, users, ts=None)` - Sends an SJOIN for a group of users to a channel. The sender should always be a Server ID (SID). TS is
optional, and defaults to the one we've stored in the channel state if not given. `users` is a list of `(prefix mode, UID)` pairs. Example uses:
    - `sjoinServer('100', '#test', [('', '100AAABBC'), ('qo', 100AAABBB'), ('h', '100AAADDD')])`
    - `sjoinServer(self.irc.sid, '#test', [('o', self.irc.pseudoclient.uid)])`

- **`spawnServer`**`(self, name, sid=None, uplink=None, desc=None)` - Spawns a server off another PyLink server. `desc` (server description) defaults to the one in the config. `uplink` defaults to the main PyLink server, and `sid` (the server ID) is automatically generated if not given.

- **`squitServer`**`(self, source, target, text='No reason given')` - SQUITs a PyLink server.

- **`topicClient`**`(self, source, target, text)` - Sends a topic change from a PyLink client.

- **`topicServer`**`(self, source, target, text)` - Sends a topic change from a PyLink server. This is usually used on burst.

- **`updateClient`**`(self, source, field, text)` - Updates the ident, host, or realname of a PyLink client. `field` should be either "IDENT", "HOST", "GECOS", or
"REALNAME". If changing the field given on the IRCd isn't supported, `NotImplementedError` should be raised.

## Special variables

A protocol module should also set the following variables in their protocol class:

- `self.casemapping`: set this to `rfc1459` (default) or `ascii` to determine which case mapping the IRCd uses.
- `self.hook_map`: this is a `dict`, which maps non-standard command names sent by the IRCd to those that PyLink plugins use internally.
    - Examples exist in the [UnrealIRCd](https://github.com/GLolol/PyLink/blob/0.5-dev/protocols/unreal.py#L22) and [InspIRCd](https://github.com/GLolol/PyLink/blob/0.5-dev/protocols/inspircd.py#L24) modules.
