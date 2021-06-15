# PyLink Protocol Module Specification

***Last updated for 3.1-dev (2021-06-15).***

Starting with PyLink 2.x, a *protocol module* is any module containing a class derived from `PyLinkNetworkCore` (e.g. `InspIRCdProtocol`), along with a global `Class` attribute set equal to it (e.g. `Class = InspIRCdProtocol`). These modules do everything from managing connections to providing plugins with an API to send and receive data. New protocol modules may be implemented based off any of the classes in the following inheritance tree, with each containing a different amount of abstraction.

![[Protocol module inheritence graph]](protocol-modules.svg)

## Starting Steps

**Before you proceed, we highly recommend protocol module coders to get in touch with us** (e.g. via IRC at `#PyLink @ irc.overdrivenetworks.com`). Letting us know what you are working on can help coordinate coding efforts and better prepare for potential API breaks.

Note: The following notes in this section assume that you are working on some IRCd's server protocol, such that PyLink can spawn subservers and its own pseudoclients. If this is not the case, *virtual* clients and servers have to be spawned instead to emulate the correct state - the `clientbot` protocol module is a functional (though not very elegant) example of this.

When writing new protocol modules, it is recommended to subclass from one of the following classes:

### `classes.IRCNetwork`

`IRCNetwork` is the base IRC class which includes the state checking utilities from `PyLinkNetworkCore`, the generic IRC utilities from `PyLinkNetworkCoreWithUtils`, along with abstraction for establishing IRC connections and pinging the uplink at a set interval.

To use `classes.IRCNetwork`, the following functions must be defined:

- `handle_events(self, data)`: given a line of text containing an IRC command, parse it and return a hook payload as specified in the [PyLink hooks reference](hooks-reference.md).
    - In all of the official PyLink modules so far, handling for specific commands is delegated into submethods via [`getattr()`](https://github.com/jlu5/PyLink/blob/3922d44173593e4bcceae1218bbc6f267caa9fc1/protocols/ircs2s_common.py#L409-L412), and unknown commands are ignored.
- `post_connect(self)`: This method sends the server introduction commands to the uplink IRC server. This method replaces the `connect()` function defined by protocol modules prior to PyLink 2.x.
- `_ping_uplink(self)`: Sends a ping command to the uplink. No return value is expected / used.

This class offers the most flexibility because the protocol module can choose how it wants to handle any command. However, because most IRC server protocols use the same RFC 1459-style message format, rewriting the entire event handler is often not worth doing. Instead, it may be better to use `IRCS2SProtocol`, as documented below, which includes a `handle_events` method which handles most cases (TS5/6, P10, and TS-less protocols such as ngIRCd).

- An exception to this general statement is `clientbot`, whose event handler also checks for unknown message senders and enumerates them when such a message is received.

### `protocols.ircs2s_common.IRCCommonProtocol`

`IRCCommonProtocol` (based off `IRCNetwork`) includes more IRC-specific methods such as parsers for ISUPPORT, as well as helper methods to parse arguments and recursively handle SQUIT. It also defines a default `_ping_uplink()` and incoming command handlers for commands that are the same across known protocols (AWAY, PONG, ERROR).

`IRCCommonProtocol` does *not*, however, define an `handle_events` method.

### `protocols.ircs2s_common.IRCS2SProtocol`
`IRCS2SProtocol` is the most complete base server class, including a generic `handle_events()` supporting most IRC S2S message styles (i.e. prefix-less messages, protocols with and without UIDs). It also defines some incoming and outgoing command functions that hardly vary between protocols: `invite()`, `kick()`, `message()`, `notice()`, `numeric()`, `part()`, `quit()`, `squit()`, and `topic()` as of PyLink 2.0. This list is subject to change in future releases.

### `classes.PyLinkNetworkCoreWithUtils`

`PyLinkNetworkCoreWithUtils` contains various state checking and IRC-related utility functions. Originally this abstraction was intended to support non-IRC protocols (Discord, Telegram, Slack, ...), but I (jlu5) no longer support this as a development focus. The main reason being is that in order to keep track of IRC server state correctly, PyLink makes a lot of assumptions specific to IRC (e.g. explicit join/part, mode formats, etc.). Trying to reconcile this with other platforms is a large undertaking and ideally requires a different, more generic protocol specification. (In PyLink 2.x there was a [Discord module](https://github.com/PyLink/pylink-discord) that is no longer supported - see https://jlu5.com/blog/the-trouble-with-pylink for a more in depth explanation as to why.)

Subclassing one of the `PyLinkNetworkCore*` classes means that a protocol module only needs to define one method of entry: `connect()`, and must set up its own message handling stack. Protocol configuration validation checks and autoconnect must also be reimplemented. IRC-style utility functions (i.e. `PyLinkNetworkCoreWithUtils` methods) should also be reimplemented / overridden when applicable.

(Unfortunately, this work is complicated, so please get in touch with us if you're stuck or want tips!)

### Other

For protocols that are closely related to existing ones, it may be wise to subclass off of an existing protocol class. For example, the `hybrid` and `ratbox` modules are based off of `ts6`. However, these protocol modules *do not guarantee API stability*, so we recommend letting us know of your intentions beforehand.

## Outgoing command functions

The methods defined below are integral to any protocol module, as they are needed by plugins to communicate with the rest of the world.

Unless otherwise noted, the camel-case variants of command functions (e.g. "`spawnClient`) are supported but deprecated. Protocol modules do *not* need to implement these aliases themselves; attempts to missing camel case functions are automatically coersed into their snake case variants via the [`structures.CamelCaseToSnakeCase`](https://github.com/jlu5/PyLink/blob/3922d44173593e4bcceae1218bbc6f267caa9fc1/structures.py#L172-L197) wrapper.

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

- **`kick`**`(self, source, channel, target, reason=None)` - Sends a kick from a PyLink client/server. This should raise `NotImplementedError` if not supported by a protocol.

- **`kill`**`(self, source, target, reason)` - Sends a kill from a PyLink client/server. This should raise `NotImplementedError` if not supported by a protocol.

- **`knock`**`(self, source, target, text)` - Sends a KNOCK from a PyLink client. This should raise `NotImplementedError` if not supported by a protocol.

- **`message`**`(self, source, target, text)` - Sends a PRIVMSG from a PyLink client.

- **`mode`**`(self, source, target, modes, ts=None)` - Sends modes from a PyLink client/server. `modes` takes a set of `([+/-]mode char, mode arg)` tuples.

- **`nick`**`(self, source, newnick)` - Changes the nick of a PyLink client.

- **`oper_notice`**`(self, source, target)` - Sends a notice to all operators on the network.

- **`notice`**`(self, source, target, text)` - Sends a NOTICE from a PyLink client or server.

- **`numeric`**`(self, source, numeric, target, text)` - Sends a raw numeric `numeric` with `text` from the `source` server to `target`. This should raise `NotImplementedError` if not supported on a protocol.

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

- **`update_client`**`(self, source, field, text)` - Updates the ident, host, or realname of a PyLink client. `field` should be either "IDENT", "HOST", "GECOS", or "REALNAME". If changing the field given on the IRCd isn't supported, `NotImplementedError` should be raised.

## Special variables

A protocol module should also set the following variables in each instance:

- `self.casemapping`: a string (`'rfc1459'` or `'ascii'`) to determine which case mapping the IRCd uses.
- `self.hook_map`: this is a `dict`, which maps non-standard command names sent by the IRCd to those used by [PyLink hooks](hooks-reference.md).
    - Examples exist in the [UnrealIRCd](https://github.com/jlu5/PyLink/blob/1.0-beta1/protocols/unreal.py#L24-L27) and [InspIRCd](https://github.com/jlu5/PyLink/blob/1.0-beta1/protocols/inspircd.py#L25-L28) modules.
- `self.conf_keys`: a set of strings determining which server configuration options a protocol module needs to function; see the [Configuration key validation](#configuration-key-validation) section below.
- `self.cmodes` / `self.umodes`: These are mappings of named IRC modes (e.g. `inviteonly` or `moderated`) to a string list of mode letters, that should be either set during link negotiation or hardcoded into the protocol module. There are also special keys: `*A`, `*B`, `*C`, and `*D`, which **must** be set properly with a list of mode characters for that type of mode.
    - Types of modes are defined as follows (from http://www.irc.org/tech_docs/005.html):
        - A = Mode that adds or removes a nick or address to a list. Always has a parameter.
        - B = Mode that changes a setting and always has a parameter.
        - C = Mode that changes a setting and only has a parameter when set.
        - D = Mode that changes a setting and never has a parameter.
    - If not defined, these will default to modes defined by RFC 1459: https://github.com/jlu5/PyLink/blob/1.0-beta1/classes.py#L127-L152
    - An example of mode mapping hardcoding can be found here: https://github.com/jlu5/PyLink/blob/1.0-beta1/protocols/ts6.py#L259-L311
    - You can find a list of supported (named) channel modes [here](channel-modes.csv), and a list of user modes [here](user-modes.csv).
- `self.prefixmodes`: This defines a mapping of prefix modes (+o, +v, etc.) to their respective mode prefix. This will default to `{'o': '@', 'v': '+'}` (the standard op and voice) if not defined.
    - Example: `self.prefixmodes = {'o': '@', 'h': '%', 'v': '+'}`
- `self.connected`: this is a `threading.Event` object that plugins use to determine if the network has finished bursting. Protocol modules should set this to True via `self.connected.set()` when ready.

## PyLink Protocol capabilities
PyLink 1.2 introduced the concept of protocol-defined capabilities, so that plugins wishing to use IRCd-specific features don't have to hard code protocol modules by name. Protocol capabilities are defined in `self.protocol_caps` (a set of strings) and may be changed freely before `self.connected` is set. Individual capabilities are then checked by plugins via `irc.has_cap(capability_name)`.

As of writing, the following protocol capabilities (case-sensitive) are implemented:

### Supported protocol capabilities
- `can-host-relay` - whether servers using this protocol can host a relay channel (for sanity reasons, this should be off for anything that's not IRC S2S)
- `can-manage-bot-channels` - whether PyLink can manage which channels the bot itself is in. This is off for platforms such as Discord.
- `can-spawn-clients` - determines whether any spawned clients are real or virtual (mainly for `services_support`).
- `can-track-servers` - determines whether servers are accurately tracked (for `servermaps` and other statistics)
- `freeform-nicks` - if set, nicknames for PyLink's virtual clients are not subject to validity and nick collision checks. This implies the `slash-in-nicks` capability.
    - Note: PyLink already allows incoming nicks to be freeform, provided they are encoded correctly and don't cause parsing conflicts (i.e. containing reserved chars on IRC)
- `has-irc-modes` - whether IRC style modes are supported
- `has-statusmsg` - whether STATUSMSG messages (e.g. `@#channel`) are supported
- `has-ts` - determines whether channel and user timestamps are tracked (and not spoofed)
- `slash-in-hosts` - determines whether `/` is allowed in hostnames
- `slash-in-nicks` - determines whether `/` is allowed in nicks
- `ssl-should-verify` - determines whether TLS certificates should be checked for validity by default - this should be enabled for any protocol modules needing to verify a remote server (e.g. Clientbot or a non-IRC API endpoint), and disabled for most IRC S2S links (where self-signed certs are widespread)
- `underscore-in-hosts` - determines whether `_` is allowed in client hostnames (yes, support for this actually varies by IRCd)
- `virtual-server` - marks the server as virtual, i.e. controlled by protocol module under a different server. Virtual servers are ignored by `rehash` and `disconnect` in the `networks` plugin.
    - This is used by pylink-discord as of v0.2.0.
- `visible-state-only` - determines whether channels should be autocleared when the PyLink client leaves (for clientbot, etc.)
    - Note: enabling this in a protocol module lets `coremods/handlers` automatically clean up old channels for you!

New protocol capabilities are generally added when needed - see https://github.com/jlu5/PyLink/issues/620

### Abstraction defaults

For reference, the `IRCS2SProtocol` class defines the following by default:
- `can-host-relay`
- `can-spawn-clients`
- `can-track-servers`
- `has-ts`

Whereas `PyLinkNetworkCore` defines no capabilities (i.e. an empty set) by default.

## PyLink structures
In this section, `self` refers to the network object/protocol module instance itself (i.e. from its own perspective).

### Server, User, Channel classes
PyLink defines classes named `Server`, `User`, and `Channel` in the `classes` module, and stores dictionaries of these in the `servers`, `users`, and `channels` attributes of a protocol object respectively.

- `self.servers` is a dictionary mapping server IDs (SIDs) to `Server` objects. If a protocol module does not use SIDs, servers are stored by server name instead.

- `self.users` is a dictionary mapping user IDs (UIDs) to `User` objects. If a protocol module does not use UIDs, a pseudo UID (PUID) generator such as [`classes.PUIDGenerator`](https://github.com/jlu5/PyLink/blob/3922d44173593e4bcceae1218bbc6f267caa9fc1/classes.py#L1710-L1726) *must* be used instead.
    - The rationale behind this is because plugins tracking user lists are not designed to remove and re-add users when they change their nicks.
    - When sending text back to the protocol module, it may be helpful to use the [`_expandPUID()`](https://github.com/jlu5/PyLink/blob/4a363aee509c5a0488a38b9e60f93ec59a274c3c/classes.py#L1213-L1231) function in `PyLinkNetworkCoreWithUtils` to expand these pseudo-UIDs back to regular nicks.

- `self._channels` and `self.channels` are [IRC case-insensitive dictionaries](https://github.com/jlu5/PyLink/blob/4a363aee509c5a0488a38b9e60f93ec59a274c3c/structures.py#L114-L116) mapping channel names to Channel objects.
    - The key difference between these two dictionaries is that `_channels` is powered by `classes.ChannelState` and creates new channels *automatically* when they are accessed by index. This makes writing protocol modules easier, as they can assume that the channels they wish to modify always exist (no chance of `KeyError`!).
    - `self.channels`, on the other hand, does *not* implicitly create channels and is thus better suited for plugins.

The `Channel`, `User`, and `Server` classes are initiated as follows:

- `Channel(self, name)` - First arg is the protocol object, second is the channel name.
- `User(self, nick, ts, uid, server, ident='null', host='null', realname='PyLink dummy client', realhost='null', ip='0.0.0.0', manipulatable=False, opertype='IRC Operator')` - These arguments are essentially the same as `spawn_client()`'s.
- `Server(self, uplink, name, internal=False, desc="(None given)")`
    - The `uplink` (type `str`) option sets the SID of the uplink server, or *None* for both the main PyLink server and its uplink.
    - The `name` option sets the server name.
    - The `internal` boolean sets whether the server is an internal PyLink server.
    - The `desc` option sets the server description, when applicable.

#### Statekeeping specifics
- When a user is introduced, their UID must be added to both `self.users` and to the `users` set in the `Server` object hosting the user (`self.servers[SID].users`). The latter list is used internally to track SQUITs.
- When a user joins a channel, the channel name is added to the User object's `channels` set (`self.users[UID].channels`), as well as the Channel object's user list (`self.channels[CHANNELNAME].users`)
- When a user disconnects, the `_remove_client` helper method can be called on their UID to automatically remove them from the relevant Server object, as well as all channels they were in.
- When a user leaves a channel, the `Channel.remove_user()` method can be used to easily remove them from the channel state, and vice versa.

### Mode formats

Modes are stored not stored as strings, but lists of mode pairs in order to ease parsing. These lists of mode pairs are used both to represent mode changes in hooks and store modes internally.

`self.parse_modes(target, modestring)` is used to convert mode strings to mode lists. `target` is the channel name/UID the mode is being set on, while `modestring` takes either a string or string split by spaces (really a list).

- `self.parse_modes('#chat', ['+tHIs', '*!*@is.sparta'])` would give:
    - `[('+t', None), ('+H', None), ('+I', '*!*@is.sparta'), ('+s', None)]`

`parse_modes()` will also automatically convert prefix mode targets from nicks to UIDs, and drop any duplicate (already set) or invalid (e.g. missing argument) modes.

- `self.parse_modes('#chat', ['+ol invalidnick'])`:
    - `[]`
- `self.parse_modes('#chat', ['+o jlu5'])`:
    - `[('+o', '001ZJZW01')]`

Afterwords, a parsed mode list can be applied to channel name or UID using `self.apply_modes(target, parsed_modelist)`.

**Note**: for protocols that accept or reject mode changes based on TS (i.e. practically every IRCd), you will want to use [`updateTS(...)`](https://github.com/jlu5/PyLink/blob/master/classes.py#L1484-L1487) instead to only apply the modes if the source TS is lower.

Internally, modes are stored in `Channel` and `User` objects as sets, **with the `+` prefixing each mode character omitted**. These sets are accessed via the `modes` attribute:

```
<+jlu5> PyLink-devel, eval irc.users[source].modes
<@PyLink-devel> {('i', None), ('x', None), ('w', None), ('o', None)}
<+jlu5> PyLink-devel, eval irc.channels['#chat'].modes
<@PyLink-devel> {('n', None), ('t', None)}
```

**Exception**: the owner, admin, op, halfop, and voice channel prefix modes are stored separately as a dict of sets in `Channel.prefixmodes`:

```
<@jlu5> PyLink-devel, eval irc.channels['#chat'].prefixmodes
<+PyLink-devel> {'op': set(), 'halfop': set(), 'voice': {'38QAAAAAA'}, 'owner': set(), 'admin': set()}
```

When a certain mode (e.g. owner) isn't supported on a network, the key still exists in `prefixmodes` but is simply unused.

### Topics

When receiving or sending topics, there is a `topicset` attribute in the `Channel` object that should be set to **True**. This boolean denotes that a topic has been set in the channel at least once; Relay uses it to know not to overwrite topics with empty ones during startup, when topics have not been received from all networks yet.

*Caveat:* Topic handlers on the current protocol modules do not follow TS rules (which vary by IRCd), and blindly accept data. See issue https://github.com/jlu5/PyLink/issues/277

## Configuration key validation

Starting with PyLink 1.x, protocol modules can specify which config values within a server block they need in order to work. This is done by adjusting the `self.conf_keys` attribute, usually in the protocol module's `__init__()` method. The default set, defined in [`Classes.Protocol`](https://github.com/jlu5/PyLink/blob/1.0-beta1/classes.py#L1202-L1204), includes `{'ip', 'port', 'hostname', 'sid', 'sidrange', 'protocol', 'sendpass', 'recvpass'}`. Should any of these keys be missing from a server block, PyLink will bail with a configuration error.

As an example, one protocol module that tweaks this is [`Clientbot`](https://github.com/jlu5/PyLink/blob/1.0-beta1/protocols/clientbot.py#L17-L18), which removes all options except `ip`, `protocol`, and `port`.

## The final checklist

In short, protocol modules have some very important jobs. If any of these aren't done correctly, you will be left with a very broken, desynced services server:

1) Handle incoming commands from the uplink.

2) Return [hook data](hooks-reference.md) for relevant commands, so that plugins can receive data from the uplink.

3) Make sure channel/user states are kept correctly. Joins, quits, parts, kicks, mode changes, nick changes, etc. should all be handled accurately where relevant.

4) Implement the specified outgoing command functions, which are used by plugins to send commands to the uplink.

5) Set the `threading.Event` instance `self.connected` to True (via `self.connected.set()`) when the connection with the uplink is fully established. This is important for Relay and the services API, which will refuse to initialize if the connection is not marked ready.

6) Check that `recvpass` is correct when applicable, and raise `ProtocolError` with a relevant error message if not.

7) Declare the correct set of protocol module capabilities to prevent confusing PyLink's plugins.

## Changes to this document
* 2021-06-15 (3.1-dev)
   - Added `oper_notice()` function to send notices to opers (GLOBOPS / OPERWALL on most IRCds)
   - Update notes about non-IRC protocols and PyLinkNetworkCoreWithUtils
* 2019-11-02 (2.1-beta1)
   - Added protocol capability: `can-manage-bot-channels`
* 2019-10-10 (2.1-beta1)
   - Added protocol capability: `has-irc-modes`
* 2019-06-23 (2.1-alpha2)
   - Added new protocol capabilities: `virtual-server` and `freeform-nicks`
* 2018-07-11 (2.0.0)
   - Version bump for 2.0 stable release; no meaningful content changes.
* 2018-06-26 (2.0-beta1)
   - Added documentation for PyLink protocol capabilities
   - Wording tweaks, restructured headings
   - Consistently refer to protocol module attributes as `self.<whatever>` instead of `irc.<whatever>`
* 2018-05-09 (2.0-alpha3)
   - `kill` and `kick` implementations should raise `NotImplementedError` if not supported (anti-desync measure).
   - Future PyLink versions will further standardize which functions should be stubbed (no-op) when not available and which should raise an error.
* 2017-10-05 (2.0-alpha1)
   - Added notes on user statekeeping and the tracking/helper functions used.
   - Mention the `post_connect()` function that must be defined by protocols inheriting from IRCNetwork.
* 2017-08-30 (2.0-dev)
   - Rewritten specification for the IRC-protocol class convergence in PyLink 2.0.
   - Updated the spec for 2.0 method renames and class restructures.
   - Added a proper "Starting Steps" section detailing which new classes inherit from and when.
   - Explicitly document the Server, User, and Channel classes.
* 2017-03-15 (1.2-dev)
   - Corrected the location of `self.cmodes/umodes/prefixmodes` attributes
   - Mention `self.conf_keys` as a special variable for completeness
* 2017-01-29 (1.2-dev)
   - NOTICE can now be sent from servers.
   - This section was added.
