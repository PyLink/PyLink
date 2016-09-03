# PyLink hooks reference

## Introduction

In PyLink, protocol modules communicate with plugins through a system of hooks. This has the benefit of being IRCd-independent, allowing most plugins to function regardless of the IRCd being used.
Each hook payload is formatted as a Python `list`, with three arguments: `numeric`, `command`, and `args`.

1) **numeric**: The sender of the hook payload (normally a UID or SID).

2) **command**: The command name (hook name) of the payload. These are *always* UPPERCASE, and those starting with "PYLINK_" indicate hooks sent out by PyLink IRC objects themselves; i.e. they don't require protocol modules to handle them.

3) **args**: The hook data (args), a Python `dict`, with different data keys and values depending on the command given.

*Note:* the `ts` key is **automatically added** (using the current time) to all hook data dicts that don't include it - such a key should only be provided if the command the uplink IRCd sends a TS value itself.

### Example syntax

The command `:42XAAAAAB PRIVMSG #dev :test` would result in the following raw hook data:

- `['42XAAAAAB', 'PRIVMSG', {'target': '#dev', 'text': 'test', 'ts': 1451174041}]`

On UnrealIRCd, because SETHOST is mapped to CHGHOST, `:GL SETHOST blah` would return the raw hook data of this (with the nick converted into UID automatically by the protocol module):

- `['001ZJZW01', 'CHGHOST', {'ts': 1451174512, 'target': '001ZJZW01', 'newhost': 'blah'}]`

Some hooks, like MODE, are more complex and can include the entire state of a channel! This will be further described later. `:GL MODE #chat +o PyLink-devel` is converted into (pretty-printed for readability):

```
['001ZJZW01',
 'MODE',
 {'modes': [('+o', '38QAAAAAA')],
  'oldchan': IrcChannel({'modes': set(),
                        'prefixmodes': {'admin': set(),
                                        'halfop': set(),
                                        'op': set(),
                                        'owner': set(),
                                        'voice': set()},
                        'topic': '',
                        'topicset': False,
                        'ts': 1451169448,
                        'users': {'38QAAAAAA', '001ZJZW01'}}),
  'target': '#chat',
  'ts': 1451174702}]
```

## Core hooks

These following hooks, sent with their correct data keys, are required for PyLink's basic functioning.

- **ENDBURST**: `{}`
    - The hook data here is empty.
    - This payload should be sent whenever a server finishes its burst, with the SID of the bursted server as the sender.
    - The service bot API and plugins like relay use this to make sure networks are properly connected. Should ENDBURST not be sent or emulated, they will likely fail to spawn users entirely.

- **PYLINK_DISCONNECT**: `{}`
    - This is sent to plugins by IRC object instances whenever their network has disconnected. The sender here is always **None**.

## IRC command hooks

The following hooks represent regular IRC commands sent between servers.

### Basic commands

- **JOIN**: `{'channel': '#channel', 'users': ['UID1', 'UID2', 'UID3'], 'modes': [('n', None), ('t', None), ('k', 'somesecretkey')], 'ts': 1234567890}`
    - This hook handles both SJOIN and JOIN commands, to make writing plugins slightly easier (they only need to listen to one hook).
    - `channel` sends the channel name, `users` sends a list of joining UIDs, and `ts` returns the TS (an `int`) that we have for the channel.
    - `modes` returns a list of parsed modes: `(mode character, mode argument)` tuples, where the mode argument is either `None` (for modes without arguments), or a string.
    - The sender of this hook payload is IRCd-dependent, and is determined by whether the command was originally a SJOIN or regular JOIN - SJOIN is only sent by servers, and JOIN is only sent by users.
    - For IRCds that support joining multiple channels in one command (`/join #channel1,#channel2`), consecutive JOIN hook payloads of this format will be sent (one per channel).
    - For SJOIN, the `channeldata` key may also be sent, with a copy of the `IrcChannel` object BEFORE any mode changes from this burst command were processed.

- **KICK**: `{'channel': '#channel', 'target': 'UID1', 'text': 'some reason'}`
    - `text` refers to the kick reason. The `target` and `channel` fields send the target's UID and the channel they were kicked from, and the sender of the hook payload is the kicker.

- **KILL**: `{'target': killed, 'text': args[1], 'userdata': data}`
    - `text` refers to the kill reason. `target` is the target's UID.
    - The `userdata` key may include an `IrcUser` instance, depending on the IRCd. On IRCds where QUITs are explicitly sent (InspIRCd), `userdata` will be `None`. Other IRCds do not explicitly send QUIT messages for KILLed clients, so the daemon must assume that they've quit, and deliver their last state to plugins that require this info.

- **MODE**: `{'target': '#channel', 'modes': [('+m', None), ('+i', None), ('+t', None), ('+l', '3'), ('-o', 'person')], 'channeldata': IrcChannel(...)}`
    - `target` is the target the mode is being set on: it may be either a channel (for channel modes) OR a UID (for user modes).
    - `modes` is a list of prefixed parsed modes: `(mode character, mode argument)` tuples, but with `+/-` prefixes to denote whether each mode is being set or unset.
    - For channels, the `channeldata` key is also sent, with a copy of the `IrcChannel` BEFORE this MODE hook was processed.
        - One use for this is to prevent oper-override hacks: checks for whether a sender is opped have to be done before the MODE is processed; otherwise, someone can simply op themselves and circumvent this detection.

- **NICK**: `{'newnick': 'Alakazam', 'oldnick': 'Abracadabra', 'ts': 1234567890}`

- **NOTICE**: `{'target': 'UID3', 'text': 'hi there!'}`
    - *Note:* `target` can not only be a channel or a UID, but also a channel with a prefix attached (e.g. `@#lounge`). These cases should not be overlooked!

- **PART**: `{'channels': ['#channel1', '#channel2'], 'text': 'some reason'}`
    - `text` can also be an empty string, as part messages are *optional* on IRC.
    - Unlike the JOIN hook, multiple channels can be specified in a list for PART. This means that a user PARTing one channel will cause a payload to be sent with `channels` as a one-length *list* with the channel name.

- **PRIVMSG**: `{'target': 'UID3', 'text': 'hi there!'}`
    - Ditto with NOTICE: `target` can be a channel or a UID, or a channel with a prefix attached (e.g. `@#lounge`).

- **QUIT**: `{'text': 'Quit: Bye everyone!'}`
    - `text` corresponds to the quit reason.

- **SQUIT**: `{'target': '800', 'users': ['UID1', 'UID2', 'UID6'], 'name': 'some.server', 'uplink': '24X', 'nicks': {'#channel1: ['tester1', 'tester2'], '#channel3': ['somebot']}, 'serverdata': IrcServer(...)`
    - `target` is the SID of the server being split, while `name` is the server's name.
    - `users` is a list of all UIDs affected by the netsplit. `nicks` maps channels to lists of nicks affected.
    - `serverdata` provides the `IrcServer` object of the server that was split.
    - `channeldata` provides the channel index of the network before the netsplit was processed, allowing plugins to track who was affected by a netsplit in a channel specific way.

- **TOPIC**: `{'channel': channel, 'setter': numeric, 'text': 'Welcome to #Lounge!, 'oldtopic': 'Welcome to#Lounge!'}`
    - `oldtopic` denotes the original topic, and `text` indicates the new one being set.
    - `setter` is the raw sender field given to us by the IRCd; it may be a `nick!user@host`, a UID, a SID, a server name, or a nick. This is not processed any further.

- **UID**: `{'uid': 'UID1', 'ts': 1234567891, 'nick': 'supercoder', 'realhost': 'localhost', 'host': 'admin.testnet.local', 'ident': ident, 'ip': '127.0.0.1'}`
    - This command is used to introduce users; the sender of the message should be the server bursting or announcing the connection.
    - `ts` refers to the user's signon time.

### Extra commands (where supported by the IRCd)

- **AWAY**: `{'text': text}`
    - `text` denotes the away reason. It is an empty string (`''`) when a user is unsetting their away status.

- **CHGHOST**: `{'target': 'UID2', 'newhost': 'some.silly.host'}`
    - SETHOST, CHGHOST, and any other events that cause host changes should return a CHGHOST hook payload. The point of this is to track changes in users' hostmasks.

- **CHGIDENT**: `{'target': 'UID2', 'newident': 'evilone'}`
    - SETIDENT and CHGIDENT commands, where available, both share this hook name.

- **CHGNAME**: `{'target': 'UID2', 'newgecos': "I ain't telling you!"}`
    - SETNAME and CHGNAME commands, where available, both share this hook name.

- **INVITE**: `{'target': 'UID3', 'channel': '#myroom'}`

- **KNOCK**: `{'text': 'let me in please!', 'channel': '#myroom'}`
    - This is not actually implemented by any protocol module as of writing.

- **SAVE**: `{'target': 'UID8', 'ts': 1234567892, 'oldnick': 'Abracadabra'}`
    - For protocols that use TS6-style nick saving. During nick collisions, instead of killing the losing client, servers that support SAVE will send such a command targeting the losing client, which forces that user's nick to their UID.

- **SVSNICK**: `{'target': 'UID1', 'newnick': 'abcd'}`
    - PyLink does not comply with SVSNICK requests, but instead forwards it to plugins that listen for it.
    - Relay, for example, treats SVSNICK as a cue to force tag nicks.

- **VERSION**: `{}`
    - This is used for protocols that send VERSION requests between servers when a client requests it (e.g. `/raw version pylink.local`).
    - `coreplugin` automatically handles this by responding with a 351 numeric, with the data being the output of `utils.fullVersion(irc)`.

- **WHOIS**: `{'target': 'UID1'}`
    - On protocols supporting it (everything except InspIRCd), the WHOIS command is sent between servers for remote WHOIS requests.
    - This requires servers to respond with a complete WHOIS reply (using all the different numerics), as done in `coreplugin`.

## Hooks that don't map to IRC commands
Some hooks do not map directly to IRC commands, but to events that protocol modules should handle.

- **CLIENT_SERVICES_LOGIN**: `{'text': 'supercoder'}`
    - This hook is sent whenever a user logs in to a services account, where `text` is the account name. The sender of the hook is the UID of the user logging in.

- **CLIENT_OPERED**: `{'text': 'IRC_Operator'}`
    - This hook is sent whenever an oper-up is successful: when a user with umode `+o` is bursted, when umode `+o` is set, etc.
    - The `text` field denotes the oper type (not the SWHOIS), which is used for WHOIS replies on different IRCds.

- **PYLINK_NEW_SERVICE**: `{'name': "servicename"}`
    - This hook is sent when a new service is introduced. It replaces the old `PYLINK_SPAWNMAIN` hook.
    - The sender here is always **None**.

- **PYLINK_CUSTOM_WHOIS**: `{'target': UID1, 'server': SID1}`
    - This hook is called by `coreplugin` during its WHOIS handling process, to allow plugins to provide custom WHOIS information. The `target` field represents the target UID, while the `server` field represents the SID that should be replying to the WHOIS request. The source of the payload is the user using `/whois`.
    - Plugins wishing to implement this should use the standard WHOIS numerics, using `irc.proto.numeric()` to reply to the source from the given server.
    - This hook replaces the pre-0.8 fashion of defining custom WHOIS handlers, which was non-standard and poorly documented.

## Commands handled WITHOUT hooks
At this time, commands that are handled by protocol modules without returning any hook data include PING, PONG, and various commands sent during the initial server linking phase.
