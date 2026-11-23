# Check before you pay

This repository holds the daily data and the plug-in of [Check before you pay](https://check.loopholetape.com/), a site that shows what happened to the entries that paid the registration fee of a Bittensor subnet. The site exists for one moment, which is the moment an operator, or the agent working for one, is about to pay that fee. The fee is gone once it is paid, and on most subnets most new entries are never paid enough to cover it, so the site counts from the chain's own records how many of the earlier entries were still earning after one and two weeks, how many got their fee back, what a new entry is paid a day today and how long today's fee takes to come back at that pay. Everything on it is measured, and nothing is predicted.

## How an agent reads it

An agent that is about to register on subnet N can fetch `https://check.loopholetape.com/c/N.md` and read the section "If you are about to pay the entry fee", and an agent that is still choosing where to enter can fetch [contests.md](https://check.loopholetape.com/contests.md), which has one row for each of the 64 subnets that are covered. The file [llms.txt](https://check.loopholetape.com/llms.txt) says what is where and what every word means. The record of a single wallet is at `https://check.loopholetape.com/wallet/COLDKEY.json`, where COLDKEY is the address that pays the fees and not the hotkey of one entry.

## The plug-in

The same three reads are offered as tools through the Model Context Protocol, at an address that needs no install, no key and no account. In Claude Code one line adds it:

```
claude mcp add --transport http check-before-you-pay https://check.loopholetape.com/mcp
```

Any other client that speaks streamable HTTP can be pointed at the same address. The tools are `check_contest`, which takes a subnet number, `list_contests`, which takes nothing, and `check_wallet`, which takes the address that pays a wallet's fees. An operator who would rather run the plug-in on their own machine can use [mcp_server.py](mcp_server.py) from this repository, which needs nothing beyond Python and the files that lie beside it here, and which is added like this:

```
claude mcp add check-before-you-pay -- python3 /path/to/mcp_server.py --base https://check.loopholetape.com/
```

## The data in this repository

The folder [data](data) is a copy of the site's files for agents, and it is refreshed once a day together with the site. It holds [llms.txt](data/llms.txt), [contests.md](data/contests.md) and [contests.json](data/contests.json) for all 64 subnets, and one `.md` and one `.json` file for each subnet under [data/c](data/c). This copy was read from the chain up to November 22, 2026 at 08:05 UTC. The wallet records are not copied here, because there are thousands of them, and the site serves them one at a time.

## What the numbers cannot see

The figures count the registration fee and nothing else, so a second fee that a subnet charges for every upload or task, and the cost of running an entry in machines, model calls and time, are not in them, and a result that looks even is a loss once those are paid. They also cannot say what a subnet asks of an entry or how its scoring works. Readings are four hours apart, so an entry shorter than that can be missed, and subnets about life science or about security are not covered.

## Who is behind it, and what is sold

The people who run the site enter Bittensor contests themselves and pay these fees like everyone else, and their own wallet's record is on the site, measured the same way as any other wallet's. Everything described above is free, and the one thing that is sold is a pack for a single contest, which holds an account of what that contest really pays for, read from its code with the file named for every statement about scoring, and a practice judge that an agent runs on its operator's own machine before the entry fee is paid. Today the pack for Pocket (subnet 26) costs $60 and is paid in TAO at the price of the moment, with 30 days of updates included, and [pay.md](https://check.loopholetape.com/pay.md) on the site says how it is bought, what a buyer should know first and whether we are entered in that contest ourselves. A pack also exists for rec4ll (subnet 31), and it is not for sale yet, for the reason given on that subnet's page.

## Contact and licence

Questions, corrections and complaints reach us at hello@agent.loopholetape.com. The code in this repository is under the MIT licence, which is in the file [LICENSE](LICENSE), and the data may be copied, used and republished freely as long as the source is named as check.loopholetape.com.
