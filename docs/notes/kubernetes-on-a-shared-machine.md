# Kubernetes on a machine another team uses

A design note: how the lab runs a Kubernetes cluster on an Ubuntu machine with two GPUs that the AI team (the team
that builds the workload) uses every day for its own Docker workloads, without getting in its way. It builds on
[the handoff](ansible-and-argo-cd.md).

**The one idea: the machine is the AI team's first, so the cluster exists only while the lab works, reaches nothing
it does not need, and can be removed without a trace. Facts found in k3s's own documentation and scripts shaped the
first; an error found in the firewall shaped the second.**

## A cluster that exists only during a session

Between sessions nothing of the cluster runs: no k3s process, no pod, no cluster network, none of k3s's own
firewall chains. What stays is k3s installed but not enabled at boot, its data on the data disk, and the lab's own
firewall rules. Two playbooks switch the lab on and off (the [lab session runbook](../runbooks/lab-session.md)):

| Step | `lab-up` | `lab-down` |
|---|---|---|
| 1 | Check memory and disk against their floors, k3s's ports free, no Tailscale routes; show both GPUs' memory and load | Check the machine advertises no Tailscale routes |
| 2 | Start k3s | Stop the lab's on-demand runs, then k3s, then its cleanup script if anything of the lab is left |
| 3 | Wait for the node and, since phase 2a, the data path's pods; Argo CD catches up from Git | Check nothing of the lab is left (processes, containers, mounts, network spaces, network links, k3s's firewall rules) and record the AI team's containers, to compare with the session's start |
| Time, phase 1 only (2026-10-30) | 17 to 19 s; Argo CD's applications `Synced` 21 s after the start | 12 to 13 s |
| Time, with the data path (2026-11-01) | 3 min 16 s, until the five data path pods are ready | 25 s |

**Why the Tailscale check.** The AI team's machine is on their Tailscale network, and k3s's cleanup script resets the
routes a machine offers to it. So `lab-down` refuses to run while the machine advertises any, rather than cut the
other team's network.

The trade-off: a start of a few minutes in exchange for nothing running between sessions. Keeping k3s up with the
lab's pods scaled to zero would save the start, but keep the control plane's memory (917 MiB at rest) and its network
on the machine all the time.

**Two facts from k3s's documentation and scripts, found before they cost anything:**

| Found | Effect it would have had | So |
|---|---|---|
| Stopping k3s's service leaves its containers running; only `k3s-killall.sh` stops them, and it finds the pods only through `K3S_DATA_DIR`, not k3s's config | With the lab's data moved off a nearly full root disk, a plain call finds no pod, and the GPU memory stays held | Every call of the cleanup script sets `K3S_DATA_DIR` |
| The installer enables k3s at boot: "The K3s service will be configured to automatically restart after node reboots or if the process crashes or is killed" ([k3s quick start](https://docs.k3s.io/quick-start)) | A reboot by the AI team would bring the whole lab back, unannounced | k3s is installed but not enabled at boot |

## The firewall takes the first match

k3s listens on three ports beyond the machine itself: the API (6443), which the pods need; the kubelet (10250),
called only by the API on the machine; and Flannel's overlay (8472/udp), used only between nodes, and this cluster
has one. None is needed from the network. The lab adds its rules to the machine's firewall, which already holds the
AI team's.

**The found error** (2026-10-30). The lab's first rules were two allows, for its pods' and its Services' ranges, added
at the bottom of the list, and no denies; the machine's firewall denies incoming traffic by default. A check from a
laptop on the office VPN found port 6443 **open**: a rule already on the machine, higher in the list, matched it
first. A firewall like ufw stops at the first rule that matches, so the default never applied, and a deny added at the
bottom would never have run either.

```text
 before (20:14)                                    after (22:11)
 1..n  the machine's existing rules                1   allow the pods' range (10.42.0.0/16)
       ← 6443 matches one of them: let in          2   allow the Services' range (10.43.0.0/16)
 n+1   allow the pods' range                       3   deny 6443/tcp         ← 6443 matches here: dropped
 n+2   allow the Services' range                   4   deny 10250/tcp
       (no deny; the default is never reached)     5   deny 8472/udp
                                                   6.. the existing rules, unchanged and in the same order
```

**The fix:** the lab's rules go first. Its pods and Services may reach the machine, and k3s's ports are closed to
everyone else, over IPv4 and IPv6. The move ran as an Ansible playbook, previewed first; the check was repeated from
the same laptop: closed. The AI team's rules were left untouched and in their order
([how the move ran](ansible-and-argo-cd.md#why-ansible-below-the-line-and-not-a-shell-script)).

## The API through a tunnel, never an open port

The lab's admin credential for the Kubernetes API is, in effect, root on the machine: whoever can create a privileged
pod or mount the host's filesystem reaches the node, as Kubernetes' own
[RBAC good practices](https://kubernetes.io/docs/concepts/security/rbac-good-practices/) say. On a machine another
team depends on, that is reason enough to keep the API off the network entirely.

```text
 the tunnel (the lab's design)
   laptop ──ssh──► machine: proof 1, the SSH key; proof 2, the account it is registered to
          ──inside it──► 127.0.0.1:6443: proof 3, the kubeconfig's client certificate
   6443 is never knocked on from the network

 a bare port (what the found error allowed)
   any laptop on the office VPN ──► machine:6443: proves only the client certificate
```

| Risk | With a bare port | With the tunnel only |
|---|---|---|
| The kubeconfig leaks | The file alone is enough | Useless without the SSH key and the account |
| A bug in code that runs before authentication (TLS, request parsing) | Reachable by anyone who can connect | Reachable only from the machine itself |

This is defence in depth: no single control is trusted to stand alone, and a port nobody needs from the network is
not reachable from it.

## Leaving no trace

Every addition the lab makes to the machine (folders, k3s and its files, the firewall rules, keys) has its row in a
teardown inventory, with the step that removes it and the check that proves it, or the reason it is left until the
next reboot; a spec that adds anything adds its row in the same commit. A read-only scan, compared with a baseline
taken before the lab was installed, found what reading the code had missed, and runs again before the real teardown;
what it cannot see is written down, so the inventory never relies on it alone. Nothing the lab writes acts at boot,
so a reboot clears what the teardown leaves in the kernel. The teardown has been previewed by its acceptance check;
it runs for real when the lab ends.

## In this lab

The decisions are rows 8, 10 and 11 to 13 of the [platform spec](../specs/gpu-box-platform.md#decisions);
the inventory is its [teardown section](../specs/gpu-box-platform.md#teardown). The acceptance checks that prove it,
including the AI team's Docker unchanged and the firewall's three trips (a pod to the API, a pod out to GitHub, the
office VPN to k3s's ports), are in [bootstrap, step 8](../runbooks/gpu-box-bootstrap.md#8-acceptance).
