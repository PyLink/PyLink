# PyLink Protocol Module Specification

***Last updated for 0.10-alpha1 (2016-08-24).***

In PyLink, each protocol module is a file consisting of a protocol class (e.g. `InspIRCdProtocol`), and a global `Class` attribute set equal to it (e.g. `Class = InspIRCdProtocol`). These classes are usually based off boilerplate classes such as `classes.Protocol`, `protocols.ircs2s_common.IRCS2SProtocol`, or other protocol module classes that share functionality with it. [[Protocol module inheritence graph]](protocol-modules.png)

IRC objects load protocol modules by creating an instance of this `Class` attribute, and then proceeding to call its commands.

## Tasks

Protocol modules have some very important jobs. If any of these aren't done correctly, you will be left with a broken, desynced services server:

1) Handle incoming commands from the uplink IRCd.

2) Return [hook data](hooks-reference.md) for relevant commands, so that plugins can receive data from IRC.

3) Make sure channel/user states are kept correctly. Joins, quits, parts, kicks, mode changes, nick changes, etc. should all be handled accurately.

4) Respond to both pings *and* pongs - the `irc.lastping` attribute **must** be set to the current time whenever a `PONG` is received from the uplink, so PyLink's doesn't [lag out the uplink thinking that it isn't responding to our pings](https://github.com/GLolol/PyLink/blob/e4fb64aebaf542122c70a8f3a49061386a00b0ca/classes.py#L309-L311).

5) Implement a series of outgoing command functions (see below), used by plugins to send commands to IRC.

6) Set the threading.Event object `irc.connected` (via `irc.connected.set()`) when the protocol negotiation with the uplink is complete. This is important for plugins like Relay which must check that links are ready before spawning clients, and they will fail to work if this is not set.

7) Check to see that RECVPASS is correct. Always.

## Core functions

The following functions *must* be implemented by any protocol module within its main class, since they are used by the IRC object internals.

- **`connect`**`(self)` - Initializes a connection to a server.

- **`handle_events`**`(self, line)` - Handles inbound data (lines of text) from the uplink IRC server. Normally, this will pass commands to other command handlers within the protocol module, while dropping commands that are unrecognized (wildcard handling). But, it's really up to you how to structure your modules. You will want to be able to parse command arguments properly into a list: many protocols send RFC1459-style commands that can be parsed using the [`Protocol.parseArgs()`](https://github.com/GLolol/PyLink/blob/e4fb64aebaf542122c70a8f3a49061386a00b0ca/classes.py#L539) function.

- **`ping`**`(self, source=None, target=None)` - Sends a PING to a target server. Periodic PINGs are sent to our uplink automatically by the [`Irc()`
internals](https://github.com/GLolol/PyLink/blob/0.4.0-dev/classes.py#L267-L272); plugins shouldn't have to use this.

### Outgoing command functions

- **`spawnClient`**`(self, nick, ident='null', host='null', realhost=None, modes=set(), server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None, manipulatable=False)` - Spawns a client on the PyLink server. No nick collision / valid nickname checks are done by protocol modules, as it is up to plugins to make sure they don't introduce anything invalid.
    - `modes` is a set of `(mode char, mode arg)` tuples in the form of [`utils.parseModes()` output](using-utils.md#parseModes).
    - `ident` and `host` default to "null", while `realhost` defaults to the same things as `host` if not defined.
    - `realname` defaults to the real name specified in the PyLink config, if not given.
    - `ts` defaults to the current time if not given.
    - `opertype` (the oper type name, if applicable) defaults to the simple text of `IRC Operator`.
    - The `manipulatable` option toggles whether the client spawned should be considered protected. Currently, all this does is prevent commands from plugins like `bots` from modifying these clients, but future client protections (anti-kill flood, etc.) may also depend on this.
    - The `server` option optionally takes a SID of any PyLink server, and spawns the client on the one given. It will default to the root PyLink server.

- **`join`**`(self, client, channel)` - Joins the given client UID given to a channel.

- **`away`**`(self, source, text)` - Sends an AWAY message from a PyLink client. `text` can be an empty string to unset AWAY status.

- **`invite`**`(self, source, target, channel)` - Sends an INVITE from a PyLink client.

- **`kick`**`(self, source, channel, target, reason=None)` - Sends a kick from a PyLink client/server.

- **`kill`**`(self, source, target, reason)` - Sends a kill from a PyLink client/server.

- **`knock`**`(self, source, target, text)` - Sends a KNOCK from a PyLink client.

- **`message`**`(self, source, target, text)` - Sends a PRIVMSG from a PyLink client.

- **`mode`**`(self, source, target, modes, ts=None)` - Sends modes from a PyLink client/server. `modes` takes a set of `([+/-]mode char, mode arg)` tuples.

- **`nick`**`(self, source, newnick)` - Changes the nick of a PyLink client.

- **`notice`**`(self, source, target, text)` - Sends a NOTICE from a PyLink client.

- **`numeric`**`(self, source, numeric, target, text)` - Sends a raw numeric `numeric` with `text` from the `source` server to `target`.

- **`part`**`(self, client, channel, reason=None)` - Sends a part from a PyLink client.

- **`quit`**`(self, source, reason)` - Quits a PyLink client.

- **`sjoin`**`(self, server, channel, users, ts=None, modes=set())` - Sends an SJOIN for a group of users to a channel. The sender should always be a Server ID (SID). TS is
optional, and defaults to the one we've stored in the channel state if not given. `users` is a list of `(prefix mode, UID)` pairs. Example uses:
    - `sjoin('100', '#test', [('', '100AAABBC'), ('qo', 100AAABBB'), ('h', '100AAADDD')])`
    - `sjoin(self.irc.sid, '#test', [('o', self.irc.pseudoclient.uid)])`

- **`spawnServer`**`(self, name, sid=None, uplink=None, desc=None)` - Spawns a server off another PyLink server. `desc` (server description) defaults to the one in the config. `uplink` defaults to the main PyLink server, and `sid` (the server ID) is automatically generated if not given. Sanity checks for server name and SID validity ARE done by the protocol module here.

- **`squit`**`(self, source, target, text='No reason given')` - SQUITs a PyLink server.

- **`topic`**`(self, source, target, text)` - Sends a topic change from a PyLink client.

- **`topicBurst`**`(self, source, target, text)` - Sends a topic change from a PyLink server. This is usually used on burst.

- **`updateClient`**`(self, source, field, text)` - Updates the ident, host, or realname of a PyLink client. `field` should be either "IDENT", "HOST", "GECOS", or
"REALNAME". If changing the field given on the IRCd isn't supported, `NotImplementedError` should be raised.

## Things to note

### Special variables

A protocol module should also set the following variables in their protocol class:

- `self.casemapping`: set this to `rfc1459` (default) or `ascii` to determine which case mapping the IRCd uses.
- `self.hook_map`: this is a `dict`, which maps non-standard command names sent by the IRCd to those that PyLink plugins use internally.
    - Examples exist in the [UnrealIRCd](https://github.com/GLolol/PyLink/blob/0.10-alpha1/protocols/unreal.py#L24-L27) and [InspIRCd](https://github.com/GLolol/PyLink/blob/0.10-alpha1/protocols/inspircd.py#L25-L28) modules.
- `self.cmodes` / `self.umodes`: These are mappings of named IRC modes (e.g. `inviteonly` or `moderated`) to a string list of mode letters, that should be either set during link negotiation or hardcoded into the protocol module. There are also special keys: `*A`, `*B`, `*C`, and `*D`, which **must** be set properly with a list of mode characters for that type of mode.
    - Types of modes are defined as follows (from http://www.irc.org/tech_docs/005.html):
        - A = Mode that adds or removes a nick or address to a list. Always has a parameter.
        - B = Mode that changes a setting and always has a parameter.
        - C = Mode that changes a setting and only has a parameter when set.
        - D = Mode that changes a setting and never has a parameter.
    - An example of mode mapping hardcoding can be found here: https://github.com/GLolol/PyLink/blob/0.10-alpha1/protocols/ts6.py#L259-L311
    - If not defined, these will default to modes defined by RFC 1459: https://github.com/GLolol/PyLink/blob/0.10-alpha1/classes.py#L123-L148
- `self.prefixmodes`: This defines a mapping of prefix modes (+o, +v, etc.) to their respective mode prefix. This will default to `{'o': '@', 'v': '+'}` (the standard op and voice) if not defined.
    - Example: `self.prefixmodes = {'o': '@', 'h': '%', 'v': '+'}`

### Topics

When receiving or sending topics, there is a `topicset` attribute in the IRC channel (IrcChannel) object that should be set **True**. It simply denotes that a topic has been set in the channel at least once. Relay uses this so it doesn't overwrite topics with empty ones during burst, when a relay channel initialize before the uplink has sent the topic for it.

*Caveat:* Topic handling is not yet subject to TS rules (which vary by IRCds) and are currently blindly accepted. https://github.com/GLolol/PyLink/issues/277

### Mode formats

Modes are stored a special format in PyLink, different from raw mode strings in order to make them easier to parse. Mode strings can be turned into mode *lists*, which are used to represent mode changes in hooks, and when storing modes internally.

`utils.parseModes(irc, target, split_modestring)` is used to convert mode strings to mode lists, where `irc` is the IRC object, `target` is the channel name or UID the mode is being set on, and `split_modestring` is the string of modes to parse, *split at each space* (meaning that it's really a list).

- `utils.parseModes(irc, '#chat', ['+tHIs', '*!*@is.sparta'])` would give:
    - `[('+t', None), ('+H', None), ('+I', '*!*@is.sparta'), ('+s', None)]`

Also, `parseModes` will automatically convert prefix mode targets from nicks to UIDs, and drop invalid modes settings.

- `utils.parseModes(irc, '#chat', ['+ol', 'invalidnick'])`:
    - `[]`
- `utils.parseModes(irc, '#chat', ['+o', 'GLolol'])`:
    - `[('+o', '001ZJZW01')]`

Then, a parsed mode list can be applied to channel name or UID using `utils.applyModes(irc, target, parsed_modelist)`.

Internally, modes are stored in channel and user objects as sets: `(userobj or chanobj).modes`:

```
<+GLolol> PyLink-devel, eval irc.users[source].modes
<@PyLink-devel> {('i', None), ('x', None), ('w', None), ('o', None)}
<+GLolol> PyLink-devel, eval irc.channels['#chat'].modes
<@PyLink-devel> {('n', None), ('t', None)}
```

*With the exception of channel prefix modes* (op, voice, etc.), which are stored as a dict of sets in `chanobj.prefixmodes`:

```
<@GLolol> PyLink-devel, eval irc.channels['#chat'].prefixmodes
<+PyLink-devel> {'op': set(), 'halfop': set(), 'voice': {'38QAAAAAA'}, 'owner': set(), 'admin': set()}
```

When a certain mode (e.g. owner) isn't supported on a network, the key still exists in `prefixmodes` but is simply unused.

You can find a list of supported (named) channel modes [here](channel-modes.csv), and a list of user modes [here](user-modes.csv).

### Configuration key validation

Starting with PyLink 0.10.x, protocol modules can specify which config values within a server block they need in order to work. This is done by adjusting the `self.conf_keys` attribute, usually in the protocol module's `__init__()` method. The default set, defined in [`Classes.Protocol`](https://github.com/GLolol/PyLink/blob/0.10-alpha1/classes.py#L1166-L1168), includes `{'ip', 'port', 'hostname', 'sid', 'sidrange', 'protocol', 'sendpass', 'recvpass'}`. Should any of these keys be missing from a server block, PyLink will bail with a configuration error.

One protocol module that tweaks this is [`Clientbot`](https://github.com/GLolol/PyLink/blob/0.10-alpha1/protocols/clientbot.py#L17-18), which removes all options except `ip`, `protocol`, and `port`.
