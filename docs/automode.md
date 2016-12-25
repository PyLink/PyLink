# Automode & Exttargets Guide

The Automode plugin was introduced in PyLink 0.9 as a simple way of managing channel access control lists with Relay. That said, it is not designed to entirely replace traditional IRC services such as ChanServ.

## Starting steps

Upon loading the `automode` plugin, you should see an Automode service bot connect, using the name that you defined. This bot provides the commands used to manage access.

For a list of commands:
- `/msg ModeBot help`

Adding access lists to a channel:
- `/msg ModeBot setacc #channel [MASK] [MODE LIST]`
- The mask can be a simple `nick!user@host` hostmask or any of the extended targets (exttargets) mentioned below. MODE LIST is a string of any prefix modes that you want to set (no `+` before needed), such as `qo`, `h`, or `ov`.

Removing access from a channel:
- `/msg ModeBot delacc #channel [MASK]`

Listing access entries on a channel:
- `/msg ModeBot listacc #channel`

Applying all access entries on a channel (sync):
- `/msg ModeBot syncacc #channel`

Clearing all access entries on a channel:
- `/msg ModeBot clearacc #channel`

## Supported masks and extended targets

Extended targets or exttargets *replace* regular hostmasks with conditional matching based on the given situation. The following exttargets are supported:

- `$account` -> Returns True (a match) if the target is registered.
- `$account:accountname` -> Returns True if the target's account name matches the one given, and the target is connected to the local network. Account names are case insensitive.
- `$account:accountname:netname` -> Returns True if both the target's account name and origin network name match the ones given. Account names are case insensitive, but network names ARE case sensitive.
- `$account:*:netname` -> Matches all logged in users on the given network. Globs are not supported here; only a literal `*`.
- `$ircop` -> Returns True (a match) if the target is opered.
- `$ircop:*admin*` -> Returns True if the target's is opered and their oper type matches the glob given (case insensitive).
- `$server:server.name` -> Returns True (a match) if the target is connected on the given server. Server names are matched case insensitively.
- `$server:*server.glob*` -> Returns True (a match) if the target is connected on a server matching the glob.
- `$server:1XY` -> Returns True if the target's is connected on the server with the given SID. Note: SIDs ARE case sensitive.
- `$channel:#channel` -> Returns True if the target is in the given channel (case insensitive).
- `$channel:#channel:op` -> Returns True if the target is in the given channel, and is opped. Any supported prefix mode (owner, admin, op, halfop, voice) can be used for the last part, but only one at a time.
- `$pylinkacc` -> Returns True if the target is logged in to PyLink.
- `$pylinkacc:accountname` -> Returns True if the target's PyLink login matches the one given (case insensitive).

## Permissions

See the [Permissions Reference](permissions-reference.md#automode) for a list of permissions defined by Automode.

## Caveats

- Service bot joining and Relay don't always behave consistently: see https://github.com/GLolol/PyLink/issues/265
