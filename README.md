# PyLink

PyLink is an extensible, plugin-based IRC Services framework written in Python. It aims to be 1) a replacement for the now-defunct Janus 2) a versatile framework and gateway to IRC.

## Usage

**PyLink is a work in progress and thus may be very unstable**! No warranty is provided if this completely wrecks your network and causes widespread rioting amongst your users!

That said, please report any bugs you find to the [issue tracker](https://github.com/GLolol/PyLink/issues). Pull requests are open if you'd like to contribute: note that **master** is bugfix only; new stuff goes to the **devel** branch.

You can also find support via our IRC channel: `#PyLink at irc.overdrive.pw` ([webchat](http://webchat.overdrive.pw/?channels=PyLink)). Ask your question and be patient.

### Dependencies

Dependencies currently include:

* Python 3.4+
* PyYAML (`pip install pyyaml` or `apt-get install python3-yaml`)
* *For the relay plugin only*: expiringdict (`pip install expiringdict`/`apt-get install python3-expiringdict`)

#### Supported IRCds

* InspIRCd 2.0.x - module `inspircd`
* charybdis (3.5.x / git master) - module `ts6`
* Elemental-IRCd (6.6.x / git master) - module `ts6`

### Setup

1) Rename `config.yml.example` to `config.yml` and configure your instance there. Note that the configuration format isn't finalized yet - this means that your configuration may break in an update!

2) Run `./pylink` from the command line.

3) Profit???
