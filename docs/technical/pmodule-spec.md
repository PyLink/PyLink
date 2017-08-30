# PyLink Protocol Module Specification

***Last updated for 2.0-dev (2017-0X-XX).***

Starting with PyLink 2.x, a protocol module is a file containing a class derived from `PyLinkNetworkCore` (e.g. `InspIRCdProtocol`), and a global, and a global `Class` attribute set equal to it (e.g. `Class = InspIRCdProtocol`). Classes may be implemented based off any of the classes in the following inheritance tree, with each of which having a different amount of abstraction.

![[Protocol module inheritence graph]](protocol-modules.png)

## Starting Steps

**Before you proceed, we highly recommend protocol module coders to get in touch with us** via our IRC channel (`#PyLink @ irc.overdrivenetworks.com`). Letting us know what you are working on can help coordinate coding efforts and better prepare for potential API breaks.

For writing new protocol modules, it is recommended to start from one of the following classes:

### `classes.IRCNetwork`

`IRCNetwork` is the base IRC class which includes the state checking utilities from `PyLinkNetworkCore`, the generic IRC utilities from `PyLinkNetworkCoreWithUtils`, along with abstraction for establishing IRC connections and pinging the uplink at a set interval.

To use `classes.IRCNetwork`, the following functions must be defined.

- `handle_events(self, data)`: given a line of text containing an IRC command, parse it and return a hook payload as specified in the [PyLink hooks reference](hooks-reference.md).
    - In all of the official PyLink modules so far, handling for specific commands is delegated into submethods via [`getattr()`](https://github.com/GLolol/PyLink/blob/3922d44173593e4bcceae1218bbc6f267caa9fc1/protocols/ircs2s_common.py#L409-L412), and unknown commands are ignored.
- `_ping_uplink(self)`: Sends a ping command to the uplink. No return value is expected / used.

This class offers the most flexibility because the protocol module can choose how it wants to handle any command. However, because most IRC server protocols use the same RFC 1459-style message format, rewriting the entire event handler is often not worth doing. Instead, it may be better to use `IRCS2SProtocol`, as documented below, which includes a `handle_events` method which handles most cases (TS5/6, P10, and TS-less protocols such as ngIRCd).

- An exception to this general statement is `clientbot`, whose event handler also checks for unknown message senders and enumerates them when such a message is received.

### `protocols.ircs2s_common.IRCCommonProtocol`

`IRCCommonProtocol` (based off `IRCNetwork`) includes more IRC-specific methods such as parsers for ISUPPORT, as well as helper methods to parse arguments and recursively handle SQUIT. It also defines a default `ping_uplink()` and incoming command handlers for commands that are the same across known protocols (AWAY, PONG, ERROR).

`IRCCommonProtocol` does *not*, however, define an `handle_events` method.

### `protocols.ircs2s_common.IRCS2SProtocol`
`IRCS2SProtocol` is the most complete base server class, including a generic `handle_events()` supporting most IRC S2S message styles (i.e. prefix-less messages, protocols with and without UIDs). It also defines some incoming and outgoing command functions that hardly vary between protocols: `invite()`, `kick()`, `message()`, `notice()`, `numeric()`, `part()`, `quit()`, `squit()`, and `topic()` as of PyLink 2.0. This list is subject to change in future releases.

### For non-IRC protocols: `classes.PyLinkNetworkCoreWithUtils`
Although this hasn't been put into practice, PyLink is designed to allow expansion into non-IRC protocols by providing a generic class that only includes state checking and utility functions.

Subclassing one of the `PyLinkNetworkCore*` classes means that a protocol module only needs to define one method of entry: `connect()`, and must do all message processing by itself. Configuration validation checks and autoconnect must also be reimplemented. IRC-style utility functions (i.e. `PyLinkNetworkCoreWithUtils` methods) *may* also be reimplemented.

(Unfortunately, this code work is complicated, so please get in touch with us if you're stuck or want tips!)

### Other

For protocols that are closely related to existing ones, it may be wise to subclass off of an existing protocol class. For example, the `hybrid` and `ratbox` modules are based off of `ts6`. However, these protocol modules *do not guarantee API stability*, so we recommend letting us know of your intentions beforehand.

### Outgoing command functions

Unless otherwise noted, the camel-case variant of command functions (e.g. "`spawnClient`) are also supported, but deprecated. However, protocol module coders do *not* need to implement these aliases themselves: attempts to missing camel case functions are automatically coersed into their snake case variants via the [`structures.CamelCaseToSnakeCase`](https://github.com/GLolol/PyLink/blob/3922d44173593e4bcceae1218bbc6f267caa9fc1/structures.py#L172-L197) wrapper.

- **`spawn_client`**`(self, nick, ident='null', host='null', realhost=None, modes=set(), server=None, ip='0.0.0.0', realname=None, ts=None, opertype=None, manipulatable=False)` - Spawns a client on the PyLink server. No nick collision / valid nickname checks are done by protocol modules, as it is up to plugins to make sure they don't introduce anything invalid.
    - `modes` is a list or set of `(mode char, mode arg)` tuples in the [PyLink mode format](#mode-formats).
    - `ident` and `host` should default to "null", while `realhost` should default to the same things as `host` if not defined.
    - `realname` should default to the real name specified in the PyLink config, if not given.
    - `ts` should default to the current time if not given.
    - `opertype` (the oper type name, if applicable) should default to the simple text of `IRC Operator`.
    - The `manipulatable` option toggles whether the client spawned should be considered protected. Currently, all this does is prevent commands from plugins like `bots` from modifying these clients, but future client protections (anti-kill flood, etc.) may also depend on this.
    - The `server` option optionally takes a SID of any PyLink server, and spawns the client on the one given. It should default to the root PyLink server if not specified.

- **`join`**`(self, client, channel)` - Joins the given client UID given to a channel.

- **`away`**`(self, source, text)` - Sends an AWAY message from a PyLink client. `text` can be an empty string to unset AWAY status.

- **`invite`**`(self, source, target, channel)` - Sends an INVITE from a PyLink client.

- **`kick`**`(self, source, channel, target, reason=None)` - Sends a kick from a PyLink client/server.

- **`kill`**`(self, source, target, reason)` - Sends a kill from a PyLink client/server.

- **`knock`**`(self, source, target, text)` - Sends a KNOCK from a PyLink client. This should raise `NotImplementedError` if not supported on the protocol.

- **`message`**`(self, source, target, text)` - Sends a PRIVMSG from a PyLink client.

- **`mode`**`(self, source, target, modes, ts=None)` - Sends modes from a PyLink client/server. `modes` takes a set of `([+/-]mode char, mode arg)` tuples.

- **`nick`**`(self, source, newnick)` - Changes the nick of a PyLink client.

- **`notice`**`(self, source, target, text)` - Sends a NOTICE from a PyLink client or server.

- **`numeric`**`(self, source, numeric, target, text)` - Sends a raw numeric `numeric` with `text` from the `source` server to `target`.

- **`part`**`(self, client, channel, reason=None)` - Sends a part from a PyLink client.

- **`quit`**`(self, source, reason)` - Quits a PyLink client.

- **`sjoin`**`(self, server, channel, users, ts=None, modes=set())` - Sends an SJOIN for a group of users to a channel. The sender should always be a Server ID (SID). TS is
optional, and defaults to the one we've stored in the channel state if not given. `users` is a list of `(prefix mode, UID)` pairs. Example uses:
    - `sjoin('100', '#test', [('', '100AAABBC'), ('qo', 100AAABBB'), ('h', '100AAADDD')])`
    - `sjoin(self.sid, '#test', [('o', self.pseudoclient.uid)])`

- **`spawn_server`**`(self, name, sid=None, uplink=None, desc=None)` - Spawns a server off another PyLink server. `desc` (server description) defaults to the one in the config. `uplink` defaults to the main PyLink server, and `sid` (the server ID) is automatically generated if not given. Sanity checks for server name and SID validity ARE done by the protocol module here.

- **`squit`**`(self, source, target, text='No reason given')` - SQUITs a PyLink server.

- **`topic`**`(self, source, target, text)` - Sends a topic change from a PyLink *client.

- **`topic_burst`**`(self, source, target, text)` - Sends a topic change from a PyLink server. This is usually used on burst.

- **`update_client`**`(self, source, field, text)` - Updates the ident, host, or realname of a PyLink client. `field` should be either "IDENT", "HOST", "GECOS", or
"REALNAME". If changing the field given on the IRCd isn't supported, `NotImplementedError` should be raised.

## Things to note

### Special variables

A protocol module should also set the following variables in their protocol class:

- `self.casemapping`: a string (`'rfc1459'` or `'ascii'`) to determine which case mapping the IRCd uses.
- `self.hook_map`: this is a `dict`, which maps non-standard command names sent by the IRCd to those used by [PyLink hooks](hooks-reference.md).
    - Examples exist in the [UnrealIRCd](https://github.com/GLolol/PyLink/blob/1.0-beta1/protocols/unreal.py#L24-L27) and [InspIRCd](https://github.com/GLolol/PyLink/blob/1.0-beta1/protocols/inspircd.py#L25-L28) modules.
- `self.conf_keys`: a set of strings determining which server configuration options a protocol module needs to function; see the [Configuration key validation](#configuration-key-validation) section below.

#### IRC object variables

A protocol module manipulates the following attributes in the IRC object it is attached to:

- `self.cmodes` / `self.umodes`: These are mappings of named IRC modes (e.g. `inviteonly` or `moderated`) to a string list of mode letters, that should be either set during link negotiation or hardcoded into the protocol module. There are also special keys: `*A`, `*B`, `*C`, and `*D`, which **must** be set properly with a list of mode characters for that type of mode.
    - Types of modes are defined as follows (from http://www.irc.org/tech_docs/005.html):
        - A = Mode that adds or removes a nick or address to a list. Always has a parameter.
        - B = Mode that changes a setting and always has a parameter.
        - C = Mode that changes a setting and only has a parameter when set.
        - D = Mode that changes a setting and never has a parameter.
    - If not defined, these will default to modes defined by RFC 1459: https://github.com/GLolol/PyLink/blob/1.0-beta1/classes.py#L127-L152
    - An example of mode mapping hardcoding can be found here: https://github.com/GLolol/PyLink/blob/1.0-beta1/protocols/ts6.py#L259-L311
    - You can find a list of supported (named) channel modes [here](channel-modes.csv), and a list of user modes [here](user-modes.csv).
- `self.prefixmodes`: This defines a mapping of prefix modes (+o, +v, etc.) to their respective mode prefix. This will default to `{'o': '@', 'v': '+'}` (the standard op and voice) if not defined.
    - Example: `self.prefixmodes = {'o': '@', 'h': '%', 'v': '+'}`

### Topics

When receiving or sending topics, there is a `topicset` attribute in the IRC channel (IrcChannel) object that should be set **True**. It simply denotes that a topic has been set in the channel at least once. Relay uses this so it doesn't overwrite topics with empty ones during burst, when a relay channel initialize before the uplink has sent the topic for it.

*Caveat:* Topic handling on the current PyLink protocol modules is not yet subject to TS rules (which vary by IRCds) and are currently blindly accepted. https://github.com/GLolol/PyLink/issues/277

### Mode formats

Modes are stored a special format in PyLink, different from raw mode strings in order to make them easier to parse. Mode strings can be turned into mode *lists*, which are used to represent mode changes in hooks, and when storing modes internally.

`irc.parseModes(target, modestring)` is used to convert mode strings to mode lists. `target` is the channel name/UID the mode is being set on, while `modestring` takes either a string or string split by spaces (really a list).

- `irc.parseModes('#chat', ['+tHIs', '*!*@is.sparta'])` would give:
    - `[('+t', None), ('+H', None), ('+I', '*!*@is.sparta'), ('+s', None)]`

`parseModes` will also automatically convert prefix mode targets from nicks to UIDs, and drop any duplicate (already set) or invalid (e.g. missing argument) modes.

- `irc.parseModes('#chat', ['+ol invalidnick'])`:
    - `[]`
- `irc.parseModes('#chat', ['+o GLolol'])`:
    - `[('+o', '001ZJZW01')]`

Then, a parsed mode list can be applied to channel name or UID using `irc.applyModes(target, parsed_modelist)`. **Note**: for protocols that accept or reject mode changes based on TS (i.e. practically every IRCd), you may want to use [`Protocol.updateTS(...)`](https://github.com/GLolol/PyLink/blob/1.0-beta1/classes.py#L1252-L1261) to handle TS changes more efficiently.

Internally, modes are stored in `IrcChannel` and `IrcUser` objects as sets, with the `+` prefixing each mode character omitted. This set is accessed via the `modes` attribute:

```
<+GLolol> PyLink-devel, eval irc.users[source].modes
<@PyLink-devel> {('i', None), ('x', None), ('w', None), ('o', None)}
<+GLolol> PyLink-devel, eval irc.channels['#chat'].modes
<@PyLink-devel> {('n', None), ('t', None)}
```

**Exception**: the owner, admin, op, halfop, and voice channel prefix modes are stored separately as a dict of sets in `IrcChannel.prefixmodes`:

```
<@GLolol> PyLink-devel, eval irc.channels['#chat'].prefixmodes
<+PyLink-devel> {'op': set(), 'halfop': set(), 'voice': {'38QAAAAAA'}, 'owner': set(), 'admin': set()}
```

When a certain mode (e.g. owner) isn't supported on a network, the key still exists in `prefixmodes` but is simply unused.

### Configuration key validation

Starting with PyLink 1.x, protocol modules can specify which config values within a server block they need in order to work. This is done by adjusting the `self.conf_keys` attribute, usually in the protocol module's `__init__()` method. The default set, defined in [`Classes.Protocol`](https://github.com/GLolol/PyLink/blob/1.0-beta1/classes.py#L1202-L1204), includes `{'ip', 'port', 'hostname', 'sid', 'sidrange', 'protocol', 'sendpass', 'recvpass'}`. Should any of these keys be missing from a server block, PyLink will bail with a configuration error.

As an example, one protocol module that tweaks this is [`Clientbot`](https://github.com/GLolol/PyLink/blob/1.0-beta1/protocols/clientbot.py#L17-L18), which removes all options except `ip`, `protocol`, and `port`.

## The final checklist

Protocol modules have some very important jobs. If any of these aren't done correctly, you will be left with a broken, desynced services server:

1) Handle incoming commands from the uplink.

2) Return [hook data](hooks-reference.md) for relevant commands, so that plugins can receive data from IRC.

3) Make sure channel/user states are kept correctly. Joins, quits, parts, kicks, mode changes, nick changes, etc. should all be handled accurately where relevant.

4) Implement a series of outgoing command functions (see below), used by plugins to send commands to IRC.

5) Set the threading.Event object `irc.connected` (via `irc.connected.set()`) when the protocol negotiation with the uplink is complete. This is important for plugins like Relay which must check that links are ready before spawning clients, and they will fail to work if this is not set.

6) Check that `recvpass` is correct when applicable, and raise `ProtocolError` with a relevant error message if not.

## Changes
* 2017-0X-XX (2.0-dev)
   - Rewritten specification for IRC-protocol class convergence, as well as command functions renamed to snake case.
* 2017-03-15 (1.2-dev)
   - Corrected the location of `self.cmodes/umodes/prefixmodes` attributes
   - Mention `self.conf_keys` as a special variable for completeness
* 2017-01-29 (1.2-dev)
   - NOTICE can now be sent from servers.
   - This section was added.
