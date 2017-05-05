# Automode Tutorial

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
Automode supports any hostmask or extended target implemented in PyLink; see the [Exttargets Guide](exttargets.md) for more details.

## Permissions

See the [Permissions Reference](permissions-reference.md#automode) for a list of permissions defined by Automode.

## Caveats

- Service bot joining and Relay don't always behave consistently: see https://github.com/GLolol/PyLink/issues/265
