# Reaching a lab machine from WSL through a full-tunnel VPN

A design note: working from home, the laptop reaches the office machine through the office VPN. This note explains
why the laptop's Linux environment, WSL (Windows Subsystem for Linux), lost almost every packet when the VPN was on,
and the two changes that made the AI agent work again and the lab machine reachable. It is the network under every
other note: the playbooks, the SSH tunnel to the cluster and the launchers (the scripts that start the lab's jobs) all
start in WSL.

**The one idea: the laptop is two computers in one, Windows and WSL, and the VPN is a Windows program that reliably
carries only the packets Windows itself sends. Every fix is a way of getting WSL's traffic either around the VPN or
handed to Windows to send.**

## The VPN: a virtual cable for Windows' traffic

The office VPN runs on Windows, set as a **full tunnel**: Windows' routing table sends all IPv4 traffic into the VPN's
virtual link, the cable. It carries IPv4 only; IPv6 still goes out over Wi-Fi. A browser and Windows'
own SSH are Windows programs, so their packets go into the cable and come out at the office: everything works for them.

## Why it failed for WSL

In WSL's default network mode, NAT, WSL sits on its own private network inside the laptop ("By default WSL uses a NAT
based architecture", [WSL networking](https://learn.microsoft.com/en-us/windows/wsl/networking)). Windows rewrites the
sender of each WSL packet to its own address and passes it on; the routing table sends it into the cable, and there
most of them are lost. Why Windows loses them cannot be seen from outside; the result can be measured.

The same tests from WSL, VPN off then on (2026-10-25). "Reached" means the server answered, whatever the status code:

| From WSL, NAT mode | VPN off | VPN on |
|---|---|---|
| HTTPS to the agent's API | **reached**: HTTP 404 in 0.17 s | **no answer**: `SSL_connect: SSL_ERROR_SYSCALL` after 15 s |
| A 600 KB upload (one agent request carries the whole conversation) | **reached**: all bytes sent, HTTP 401 in 0.68 s | **no answer**: 0 bytes sent, timed out at 40 s |
| Ping to a public address, the largest payload that passes | 1,252 bytes (a 1,280-byte packet, WSL's MTU) | none, even 1,200 |
| SSH to the lab machine | no answer (expected: it is on the office network) | **no answer either** |
| One real agent request | answered in 8 s | timed out after 92 s |

Not a packet-size problem: even 1,200-byte pings failed, under every size limit on the path. Name lookups still answered, because WSL asks Windows for them over
a separate channel, so programs did not fail at once; they waited for a timeout, and the agent seemed to hang instead
of showing an error.

## Fix 1: mirrored mode, half the problem

Mirrored mode (`networkingMode=mirrored` in `.wslconfig`, Windows' per-user WSL settings file) removes the NAT and gives WSL copies of Windows' network
cards: "the goal of 'mirroring' the network interfaces that you have on Windows into Linux", with "IPv6 support" and
"Improved networking compatibility for VPNs" among its benefits ([WSL networking](https://learn.microsoft.com/en-us/windows/wsl/networking)).
Now a packet's road depends on its kind:

```text
                         WSL's road (mirrored)                        result
 IPv6 (the agent's API)  copy of the Wi-Fi card ──► internet      ──► works: the VPN never touches it
 IPv4 (GitHub, the lab)  copy of the cable ──► most packets lost  ──► almost never an answer
```

The agent's API has an IPv6 address, so the agent worked again: HTTPS in 0.21 s, one real request answered in 26 s. GitHub has no IPv6 address, and
neither has the lab machine, so their packets still took the cable's copy. Counted with the VPN on, 20 TCP connections
to GitHub's port 443 each:

| Sent by | Connected | Slower than 0.5 s (a resent first packet) | Clean |
|---|---|---|---|
| WSL, through the cable's copy | 12 of 20 | 9 of those 12 | **3 of 20** |
| Windows, its own connection | 20 of 20 | 0 | **20 of 20** |

A connection needs a few packets to open; a TLS handshake, a `git push` or an SSH login needs many, in both
directions, so they mostly fail: HTTPS to GitHub from WSL worked in 1 of 3 tries, and SSH straight to the machine hung
until it was killed at 15 s.

## Fix 2: a relay through Windows, for the lab machine

The table says what works: Windows' own connections. So WSL's SSH is handed to Windows, which makes the connection
itself. A relay, unlike a router, ends the connection it receives and opens a second one of its own to the real
destination, copying the bytes between the two.

```text
 ssh (WSL) ══ connection 1 ══► relay (Windows) ══ connection 2 ══► VPN ══► the lab machine's SSH
             the shared         copies bytes        Windows' own packets,
             loopback           both ways           so the VPN carries them cleanly
```

Windows' port proxy (`netsh interface portproxy`) listens on the laptop's loopback, which WSL shares in mirrored mode,
and opens connection 2 itself. To the VPN it is Windows' own traffic. On 2026-10-25, SSH through the relay answered and
the machine's host key matched; Windows showed connection 2 owned by its own service process, from the VPN's address
to the machine. Everything the lab does on the machine (Ansible, the SSH tunnel to the
Kubernetes API, the launchers) rides on that SSH connection.

## What works now, and the one rule left

| Traffic from WSL, VPN on | Road | Result |
|---|---|---|
| The agent, and the sites checked that have an IPv6 address (package indexes, Docker Hub, a model hub) | The Wi-Fi card's copy, around the VPN | Works |
| SSH to the lab machine, and all that rides on it | The relay: Windows' own connection through the VPN | Works |
| A site with only an IPv4 address, such as GitHub | The cable's copy | Flaky to failing |

So `git push` waits until the VPN is off. The lab's rule is simpler still: from home with the VPN on, push and read
the web only after turning it off. At the office, where the machine is on the same network, no VPN is needed at all.

## In this lab

The laptop is the dev machine and the cluster's client ([D3](../design.md#decisions)). The two fixes are
[laptop setup, step 1](../runbooks/laptop-setup.md#1-wsl-mirrored-networking) and
[reaching the machine, step 4](../runbooks/reach-the-box.md#4-the-windows-relay-home-only); the push rule is in
[AGENTS.md](../../AGENTS.md#git).
