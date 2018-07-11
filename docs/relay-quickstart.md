# PyLink Relay Quick Start Guide

PyLink Relay (aka "Relay") provides transparent server-side relaying between channels, letting networks share channels on demand without going through all the fuss of a hard link. Each network retains its own opers and services, with default behaviour being so that oper features (kill, overrides, etc.) are isolated to only work on channels they own. If you're familiar with Janus, you can think of PyLink Relay as being a rewrite of it from scratch (though PyLink can do much more via its other plugins!).

This guide goes over some of the basic commands in Relay, as well as all the must-know notes.

## How nick suffixing work

The default Relay configuration in will automatically tag users from other networks with a suffix such as `/net`. The purpose of this is to prevent confusing nick collisions if the same nick is used on multiple linked networks, and ensure that remote networks' nicks effectively use their own namespace.

How is this relevant to an operator? Firstly, it means that you **cannot ban users** using banmasks such as `*/net1!*@*`! The nick suffix is something PyLink adds artificially; on `net1`'s IRCd, which check the bans locally, the nick suffix doesn't exist and will therefore *not* match anyone.

## Services compatibility
While PyLink is generally able to run independently of individual networks's services, there are some gotchas. This list briefly details services features that have been known to cause problems with Relay. **Using any of these features in conjunction with Relay is *not* supported.**

- Anope, Atheme: **Clones prevention should be DISABLED** (or at a minimum, set to use G/KLINE instead of KILL)
    - Rationale: it is common for a person to want to connect to multiple networks in a Relay instance, because they are still independent entities. You can still use IRCd-side clones prevention, which sanely blocks connections instead of killing / banning everyone involved.
- Anope: **SQLINE nicks should NOT be used**
    - Rationale: Anope falls back to killing target clients matching a SQLINE, which will obviously cause conflicts with other services.
- *Any*: **Do NOT register a relayed channel on multiple networks**
    - Rationale: It is very easy for this to start kick or mode wars. (Bad akick mask? Secure ops enabled?)
- *Any*: **Do NOT jupe virtual Relay servers** (e.g. `net.relay`)
    - Rationale: This will just make PyLink split off - you should instead [delink any problem networks / channels](#dealing-with-disputes-and-emergencies).
- Multiple PyLink Relay instances:
    - **Do NOT connect a network twice to any PyLink instance**.
    - **Do NOT connect a network to 2+ separate PyLink instances if there is another network already acting as a hub for them**.
    - Not following these rules means that it's very easy for the Relay instances to go in a loop, whcih will hammer your CPU and seriously spam your channels.

## Relay commands
The concept of relay channels in PyLink is greatly inspired by Janus, though with a few differences in command syntax.

Then, to list all available channels:
- `/msg PyLink linked`

To create a channel:
- `/msg PyLink create #channelname`

To link to a channel already created on a different network:
- `/msg PyLink link othernet #channelname`

You can also link remote channels to take a different name on your network. (This is the third argument to the LINK command)
- `/msg PyLink link othernet #lobby #othernet-lobby`

To remove a relay channel that you've created:
- `/msg PyLink destroy #channelname`

To delink a channel linked to another network:
- `/msg PyLink delink #localchannelname`

Then, to list all available channels:
- `/msg PyLink linked`

### Claiming channels

Channel claims are a feature which prevents oper override (MODE, KICK, TOPIC, KILL, OJOIN, ...) from working on channels not owned by or whitelisting a network. By default, CLAIM is enabled for all new channels, though this can be configured in 2.0+ via the [`relay::enable_default_claim` option](https://github.com/jlu5/PyLink/blob/2.0-beta1/example-conf.yml#L771-L774). Unless the claimed network list of a channel is EMPTY, oper override will only be allowed from networks on that list.

To set a claim (note: for these commands, you must be on the network which created the channel in question!):
- `/msg PyLink claim #channel yournet,net2,net3` (the last parameter is a case-sensitive comma-separated list of networks)

To list claim networks on a channel:
- `/msg PyLink claim #channel`

To clear the claim list for a channel:
- `/msg PyLink claim #channel -`

### Access control for links (LINKACL)
LINKACL allows you to blacklist or whitelist networks from linking to your channel. The default configuration enables blacklist mode by default, though this can be configured via the [`relay::linkacl_use_whitelist` option](https://github.com/jlu5/PyLink/blob/2.0-beta1/example-conf.yml#L766-L769).

To change between blacklist and whitelist mode:
- `/msg PyLink linkacl whitelist #channel true/false`
- Note that when you switch between LINKACL modes, the LINKACL entries from the previous mode are stored and stashed away. This means that you will get an empty LINKACL list in the new LINKACL mode if you haven't used it already, and that you can reload the previous LINKACL mode's entries by switching back to it at any point.

To view the LINKACL networks for a channel:
- `/msg PyLink linkacl #channel list`

To add a network to the whitelist **OR** remove a network from the blacklist:
- `/msg PyLink linkacl #channel allow badnet`

To remove a network from the whitelist **OR** add a network to the blacklist:
- `/msg PyLink linkacl #channel deny goodnet`

### Adding channel descriptions
Starting with 2.0, you can annotate your channels with a description to use in LINKED:

To view the description for a channel:
- `/msg PyLink chandesc #channel`

To change the description for a channel:
- `/msg PyLink chandesc #channel your text goes here`

To remove the description for a channel:
- `/msg PyLink chandesc #channel -`

## Dealing with disputes and emergencies

The best thing to do in the event of a dispute is to delink the problem networks / channels. KILLs and network bans (K/G/ZLINE) will most often *not* behave the way you expect it to.

### Kill handling
Special kill handling was introduced in 2.0, while in previous versions they were always rejected:

1) If the sender was a server and not a client, reject the kill.
2) If the target and source networks are both in a(ny) [kill share pool](https://github.com/jlu5/PyLink/blob/2.0-beta1/example-conf.yml#L725-L735), relay the kill as-is.
3) Otherwise, check every channels the kill target is in:
    - If the killer has claim access in a channel, forward the KILL as a kick to that channel.
    - Otherwise, bounce the kill silently.

### Network bans (K/G/ZLINE)

Network bans are purposely not supported; see https://github.com/jlu5/PyLink/issues/521#issuecomment-352316396.

### Delinking channels

To delink another network from a channel your network owns:

- `/msg PyLink delink #yourchannel badnetwork`

To delink your network from a bad network's channel:

- `/msg PyLink delink #badchannel`

Basically, only one of the two above commands will work for one specific channel. Almost always, the network that owns a channel should be the one who has it registered via their services. You can see a list of channels by typing `/msg PyLink linked`.
