# Opering with PyLink Relay

*This guide was written for the OVERdrive-IRC network, but may be applicable elsewhere.*

PyLink Relay behaves much like Janus, an extended service used to relay channels together. This guide goes over some of the basic oper commands in Relay, along with the best ways to handle channel emergencies.

## How nick suffixing work

When joining a relay channel, every user from another network will have a network tag attached to their name. The purpose of this is to prevent nick collisions from the same nick being used on multiple nets, and ensure that different networks' registered nicks remain separate.

How is this relevant? Firstly, it means that you **cannot ban users from entire networks** using banmasks such as `*/net1!*@*`! The nick suffix is something PyLink adds artificially; on `net1`'s IRCd, which is checking the bans locally, the nick suffix simply doesn't exist.

However, this *does* mean that you can effectively give access to remote users via services, by specifying masks such as `*/net1@someident@someperson.opers.somenet.org`. Just don't make masks too wide, or you risk getting channel takeovers.

## Relay commands
The concept of relay channels in PyLink is greatly inspired from the original Janus implementation, though with a few differences in command syntax.

To create a channel:
- `/msg PyLink create #channelname`

To link to a channel already created on a different network:
- `/msg PyLink link othernet #channelname`

You can also link remote channels to take a different name on your network. (This is the third argument to the LINK command)
- `/msg PyLink link othernet #lobby #othernet-lobby`

Also, to list the available channels:
- `/msg PyLink linked`

To remove a relay channel that you've created:
- `/msg PyLink destroy #channelname`

To delink a channel linked to another network:
- `/msg PyLink delink #channelname`

### Claiming channels

PyLink offers channel claims similarly to Janus, except that it is on by default when you create a channel on any network. Unless the claimed network list of a channel is EMPTY, oper override (MODE, KICK, TOPIC) will only be allowed from networks on that list.

To set a claim (note: for these commands, you must be on the network which created the channel in question!):
- `/msg PyLink claim #channel yournet,net2,net3` (the last parameter is a comma-separated list of networks, case-sensitive)

To list claims on a channel:
- `/msg PyLink claim #channel`

To remove claims from a channel
- `/msg PyLink claim #channel -`

### Access control for links (LINKACL)
LINKACL allows you to block certain networks from linking to your relay channels, based on a blacklist. By default, this blacklist is empty.

To list blocked networks for a channel:
- `/msg PyLink linkacl #channel list`

To add a network to the blacklist:
- `/msg PyLink linkacl #channel allow badnet`

To remove a network from the blacklist:
- `/msg PyLink linkacl #channel deny goodnet`

Whitelists with LINKACL are not supported at this time.

## Dealing with channel emergencies

PyLink is not designed with the ability to forward KILLs, G:Lines, or any network bans. **The best thing to do in the case of emergencies is to delink the problem networks / channels!** Kills are actively blocked by the PyLink daemon (user is just respawned), while X:Lines are simply ignored, as there isn't any code to handle them yet.

To delink another network from a channel your network owns:

- `/msg PyLink delink #yourchannel badnetwork`

To delink your network from a bad network's channel:

- `/msg PyLink delink #badchannel`

Basically, only one of the two above commands will work for one specific channel. Almost always, the network that owns a channel should be the one who has it registered via their services. You can see a list of channels by typing `/msg PyLink linked`.

## When a network starts causing disconnect spam

Juping an individual `net.relay` server will likely cause PyLink Relay to break or disconnect completely. When a network starts acting up and disconnecting frequently (and causing netsplit/quit floods), you should disable autoconnect for this network:

- `/msg PyLink autoconnect badnetwork -1` (setting autoconnect to 0 or below will cause it to be disabled)

