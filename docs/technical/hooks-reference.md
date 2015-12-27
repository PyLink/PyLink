# PyLink hooks reference

## Introduction

In PyLink, protocol modules communicate with plugins through a system of hooks. This has the benefit of being IRCd-independent, allowing most plugins to function regardless of the IRCd being used.
Each hook payload is formatted as a Python `list`, with three arguments `(numeric, command, args)`:

1) **numeric**: The sender of the message (UID).

2) **command**: The command name (hook name) of the payload. These are *always* UPPERCASE, and those starting with "PYLINK_" indicate hooks sent out by IRC objects themselves, that don't require protocol modules to send.

3) **args**: The hook data (args), a Python `dict`, with different data keys depending on the command given.

Note that the `ts` key is *automatically added* (using the current time) to all hook data dicts that don't include it - such a key should only be provided if the command the uplink IRCd send has a TS value itself.

### Example syntax

The command `:42XAAAAAB PRIVMSG #endlessvoid :test` would result in the following raw hook data:

- `['42XAAAAAB', 'PRIVMSG', {'target': '#endlessvoid', 'text': 'test', 'ts': 1451174041}]`

On UnrealIRCd, because SETHOST is mapped to CHGHOST, `:GL SETHOST blah` would return the raw hook data of this (with the nick converted into UID by the UnrealIRCd protocol module):

- `['001ZJZW01', 'CHGHOST', {'ts': 1451174512, 'target': '001ZJZW01', 'newhost': 'blah'}]`

Some hooks, like MODE, are more complex and can include the entire state of a channel!  This will be further described later. `:GL MODE #chat +o PyLink-devel` is converted into (pretty-printed for readability):

- ```
['001ZJZW01',
 'MODE',
 {'modes': [('+o', '38QAAAAAA')],
  'oldchan': {'modes': set(),
              'prefixmodes': {'admins': set(),
                              'halfops': set(),
                              'ops': set(),
                              'owners': set(),
                              'voices': set()},
              'topic': '',
              'topicset': False,
              'ts': 1451169448,
              'users': {'38QAAAAAA', '001ZJZW01'}},
  'target': '#chat',
  'ts': 1451174702}]
```

## Core hooks

The following hooks are required for PyLink's basic functioning.

- **ENDBURST**: `{}` - Although the hook data is empty, this should be sent whenever a server finishes its burst. The sender should be the server that finishes bursting.
<br>
Plugins like Relay need this to know that the uplink has finished bursting all its users!

- **PYLINK_DISCONNECT**: `{}` - This is sent to plugins by the IRC objects when their network has disconnected. The sender (numeric) is **None** in this case.

- **PYLINK_SPAWNMAIN**: `{'olduser': olduserobj}` - This is sent whenever `Irc.spawnMain()` is called to (re)spawn the main PyLink client, for example to rejoin it from a KILL. It basically tells plugins that the UID of the main PyLink client has changed, while giving them the old data too.

## IRC command hooks

The following hooks represent regular IRC commands sent between servers.

<br><br><br>
(under construction)
