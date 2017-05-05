# Exttargets Guide

In PyLink, **extended targets** or **exttargets** *replace* regular hostmasks with conditional matching based on specific situations. PyLink exttargets are supported by most plugins in the place of `nick!user@host` masks (provided they use the `Irc.matchHost()` API with a user object).

Exttargets were introduced in PyLink 0.9 alongside [Automode](automode.md), with the goal of making user/ACL matching more versatile. As of PyLink 1.2-alpha2, the following exttargets are supported:

### The "$account" target (PyLink 0.9+)
Used to match users by their services account.

- `$account` -> Returns True (a match) if the target is registered.
- `$account:accountname` -> Returns True if the target's account name matches the one given, and the target is connected to the local network. Account names are case insensitive.
- `$account:accountname:netname` -> Returns True if both the target's account name and origin network name match the ones given. Account names are case insensitive, but network names ARE case sensitive.
- `$account:*:netname` -> Matches all logged in users on the given network. Globs are not supported here; only a literal `*`.

### The "$channel" target (PyLink 0.9+)
Used to match users in certain channels. Channel names are matched case insensitively.

- `$channel:#channel` -> Returns True if the target is in the given channel.
- `$channel:#channel:PREFIXMODE` -> Returns True if the target is in the given channel, and is opped. Any supported prefix mode (owner, admin, op, halfop, voice) can be used for the last part, but only one at a time.

### The "$ircop" target (PyLink 0.9+)
Used to match users by IRCop status.

- `$ircop` -> Returns True (a match) if the target is opered.
- `$ircop:*admin*` -> Returns True if the target's is opered and their oper type matches the glob given (case insensitive).

### Target inversion (PyLink 1.2+)
In PyLink 1.2 and above, all targets and hostmasks can be inverted by placing a `!` before the target:

- `!$account` -> Matches all users not registered with services.
- `!$ircop` -> Matches all non-opers.
- `!*!*@localhost` -> Matches all users not connecting from localhost.
- `!*!*@*:*` -> Matches all non-IPv6 users.

For users on PyLink version **before 1.2**, target inversion is *only* supported with exttargets (i.e. `!$account` will work, but not `!*!*@localhost`.

### The "$network" target (PyLink 1.2+)
Used to match users on specific networks.

- `$network:netname` -> Returns True if the target user originates from the given network (this supports and looks up the home network of Relay users).

### The "$and" target (PyLink 1.2+)
The `$and` target is slightly more complex, and involves chaining together multiple exttargets or hosts with a `+` between each. Note that parentheses are required around the list of targets to match.

- `$and:($ircop:*admin*+$network:ovd)` -> Matches all opers on the network ovd.
- `$and:($account+$pylinkirc)` -> Matches all users logged in to both services and PyLink.
- `$and:(*!*@localhost+$ircop)` -> Matches all opers with the host `localhost`.
- `$and:(*!*@*.mibbit.com+!$ircop+!$account)` -> Matches all (non-CGIIRC) Mibbit users that aren't opered or logged in to services.

### The "$server" target (PyLink 0.9+)
Used to match users on specific IRC servers.

- `$server:server.name` -> Returns True (a match) if the target is connected on the given server. Server names are matched case insensitively.
- `$server:*server.glob*` -> Returns True (a match) if the target is connected on a server matching the glob.
- `$server:1XY` -> Returns True if the target's is connected on the server with the given SID. Note: SIDs ARE case sensitive.

### The "$pylinkacc" target (PyLink 0.9+)
Used to match users logged in to *PyLink* (i.e. via the `identify` command).

- `$pylinkacc` -> Returns True if the target is logged in to PyLink.
- `$pylinkacc:accountname` -> Returns True if the target's PyLink login matches the one given (case insensitive).
