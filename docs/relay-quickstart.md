# PyLink Relay Quick Start

## What is Relay?

PyLink Relay is a plugin that provides transparent relays between channels on different networks. On participating networks, PyLink connects as a services server and mirrors messages as well as user lists from relayed channels, the latter by creating "puppet" service clients for all remote users in common channels. Relay offers an alternative to classic IRC linking, letting networks share channels on demand while retaining their services, policies, and distinct branding. By default, Relay also secures channels from remote oper overrides via a CLAIM feature, which restricts /kick, /mode, and /topic changes from un-opped users unless they are granted permissions via CLAIM.

Relay shares many ideas from its predecessor Janus, but is a complete rewrite in Python. This guide goes over some of the basic commands in Relay, as well as some must-know gotchas.

## Important notes (READ FIRST!)

### How nick suffixing work

By default, Relay will automatically tag users from other networks with a suffix such as `/net`. This prevents confusing nick collisions if the same nick is used on multiple linked networks, and ensure that nicks from remote networks are all isolated into their own namespaces.

How is this relevant to an operator? It means that you **cannot ban users** using banmasks such as `*/net1!*@*`! The nick suffix is something PyLink adds artificially; on `net1`'s IRCd, which check the bans locally, the nick suffix doesn't exist and will therefore *not* match anyone.

### Services compatibility

While PyLink is generally able to run independently of individual networks' services, there are some gotchas. This list briefly details services features that have been known to cause problems with Relay. **Using any of these features in conjunction with Relay is *not* supported.**

- Anope, Atheme: **Clones prevention should be DISABLED** (or at a minimum, set to use G/KLINE instead of KILL)
    - Rationale: it is common for a person to want to connect to multiple networks in a Relay instance, because they are still independent entities. You can still use IRCd-side clones prevention, which sanely blocks connections instead of killing / banning everyone involved.
- Anope: **SQLINE nicks should NOT be used**
    - Rationale: Anope falls back to killing target clients matching a SQLINE, which will obviously cause conflicts with other services.
- Atheme: **The ChanFix service should be disabled**
    - Rationale: ChanFix is incompatible with Relay CLAIM because it overrides ops on relay channels whenever they appear "opless". This basic op check is unable to consider the case of remote channel services not being set to join channels, and will instead cause join/message/part spam as CLAIM reverts the ChanFix service's mode changes.
- *Any*: **Do NOT register a relayed channel on multiple networks**
    - Rationale: It is very easy for this to start kick or mode wars. (Bad akick mask? Secure ops enabled?)
    - Clientbot is an exception to this, though you may want to add Clientbot networks to CLAIM so that PyLink doesn't try to reverse modes set by services on the Clientbot network.
- *Any*: **Do NOT jupe virtual Relay servers** (e.g. `net.relay`)
    - Rationale: This will just make PyLink split off - you should instead [delink any problem networks / channels](#dealing-with-disputes-and-emergencies).
- Multiple PyLink Relay instances:
    - **Do NOT connect a network twice to any PyLink instance**.
    - **Do NOT connect a network to 2+ separate PyLink instances if there is another network already acting as a hub for them**.
    - Not following these rules means that it's very easy for the Relay instances to go in a loop should an operator run the wrong command, which will hammer your CPU and relentlessly spam your channels.

Note: P10-specific services packages have not been particularly tested - your feedback is welcome.

## Relay commands

The basic steps for setting up a relay is to first CREATE the channel with PyLink on the network that owns it, and run LINK from each network that wants to link to it. In most cases, you want to run CREATE on the network where the channel is registered with services.

Importantly, this means that CREATE and LINK have to be run on different networks for any particular channel, and that you should only run CREATE once for each distinct channel! This setup is intended to allow individual network admins to pick and choose channels they want to participate in.

First, to list all available channels:
- `/msg PyLink linked`

To create a channel on Relay:
- `/msg PyLink create #channelname`
- Note: **you can only create channels on full IRCd links - this will NOT work with Clientbot.**
- A channel created on a particular network is considered to be _owned_ by that network; this affects how CLAIM works for instance (see the next section)

To link to a channel already created on a different network:
- `/msg PyLink link othernet #channelname`
- You should replace `othernet` with the *short name* for the network that owns the channel.
- Note: network names are case sensitive!

You can also link remote channels while using a different name for it on your network. (This is the third argument to the LINK command)
- `/msg PyLink link othernet #lobby #othernet-lobby`

To completely remove a relay channel (on the network that created it):
- `/msg PyLink destroy #channelname`

To delink a channel *linked to another network*:
- `/msg PyLink delink #localchannelname`

To delink one of *your* channels from another network:
- `/msg PyLink delink #yourchannelname <name-of-other-network>`

Then, to list all available channels:
- `/msg PyLink linked`

### Claiming channels

Channel claiming is a feature which prevents oper override (MODE, KICK, TOPIC, KILL, OJOIN, ...) by other networks' operators from affecting your channels. By default, CLAIM is enabled for all new channels, though this can be configured via the [`relay::enable_default_claim` option](https://github.com/jlu5/PyLink/blob/3.0.0/example-conf.yml#L828-L831). Unless the claimed network list of a channel is _empty__, oper override will only be allowed from networks on the CLAIM list (plus the network that owns the channel).

Note: these commands must be run from the network which owns the channel in question!

To set a claim:
- `/msg PyLink claim #channel yournet,net2,net3` (the last parameter is a case-sensitive comma-separated list of networks)

To list claim networks on a channel:
- `/msg PyLink claim #channel`

To clear the claim list for a channel:
- `/msg PyLink claim #channel -`

### Access control for links (LINKACL)

LINKACL allows you to allow or deny networks from linking to your channel. New channels are created using a blacklist by default, though this can be configured via the [`relay::linkacl_use_whitelist` option](https://github.com/jlu5/PyLink/blob/3.0.0/example-conf.yml#L823-L826).

To change between blacklist and whitelist mode:
- `/msg PyLink linkacl whitelist #channel true/false`
- Note that when you switch between LINKACL modes, the LINKACL entries from the previous mode are stored and stashed away. This means that you will get an empty LINKACL list in the new LINKACL mode if you haven't used it already, and that you can reload the previous LINKACL mode's entries by switching back to it at any point.

To view the LINKACL networks for a channel:
- `/msg PyLink linkacl #channel list`

To add a network to the whitelist **OR** remove a network from the blacklist:
- `/msg PyLink linkacl #channel allow goodnet`

To remove a network from the whitelist **OR** add a network to the blacklist:
- `/msg PyLink linkacl #channel deny badnet`

### Adding channel descriptions

Starting with PyLink 2.0, you can annotate your channels with a description to use in LINKED:

To view the description for a channel:
- `/msg PyLink chandesc #channel`

To change the description for a channel:
- `/msg PyLink chandesc #channel your text goes here`

To remove the description for a channel:
- `/msg PyLink chandesc #channel -`

## Dealing with disputes and emergencies

The best thing to do in the event of a dispute is to delink the problem networks / channels. In order for individual networks to maintain their autonomy, KILLs and network bans (K/G/ZLINE) will most often *not* behave the way you expect them to.

### Kill handling

Special kill handling was introduced in PyLink 2.0, while in previous versions they were always bounced:

1) If the sender was a server and not a client, reject the kill. (This prevents services messups from wreaking havoc across the relay)
2) If the target and source networks share a [kill share pool](https://github.com/jlu5/PyLink/blob/3.0.0/example-conf.yml#L782-L792), relay the kill as-is.
3) Otherwise, check every channel that the kill target is in:
    - If the sender is opped or has claim access in a channel, forward the KILL as a kick in that channel.
    - Otherwise, bounce the kill silently (i.e. rejoin the user immediately).

### Network bans (K/G/ZLINE)

Network bans are purposely not supported; see https://github.com/jlu5/PyLink/issues/521#issuecomment-352316396.

### Delinking channels

To delink another network from a channel your network owns:

- `/msg PyLink delink #yourchannel badnetwork`

To delink your network from a bad network's channel:

- `/msg PyLink delink #badchannel`

Basically, only one of the two above commands will work for one specific channel. Almost always, the network that owns a channel should be the one who has it registered via their services. You can see a list of channels by typing `/msg PyLink linked`.
