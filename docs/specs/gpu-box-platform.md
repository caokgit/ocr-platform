# Spec: the GPU box platform (phase 1)

How the lab puts a single-node k3s cluster, the NVIDIA GPU Operator and Argo CD on the GPU box, the office machine the
AI team (the team that builds the OCR workload) runs its Docker workloads on, **beside those workloads, without
changing them**. The cluster runs only while the lab works, and is removed completely. It is the platform every
[outcome](../../README.md#outcomes) runs on, and implements [D3](../design.md#decisions), [D4](../design.md#decisions),
[D10](../design.md#decisions) and [D13](../design.md#decisions). The design notes behind it:
[Kubernetes on a machine another team uses](../notes/kubernetes-on-a-shared-machine.md),
[GPUs on the host's driver](../notes/gpus-on-the-hosts-driver.md), [Ansible and Argo CD](../notes/ansible-and-argo-cd.md),
[WSL and a full-tunnel VPN](../notes/wsl-and-a-full-tunnel-vpn.md). How to run it:
[bootstrap](../runbooks/gpu-box-bootstrap.md), [a lab session](../runbooks/lab-session.md),
[teardown](../runbooks/gpu-box-teardown.md). The [data path](data-path.md) builds on it.

**State: approved and built on 2026-10-30.** All eleven acceptance checks hold; four were run narrower than written
([as run](#acceptance)), and the teardown has run only as its preview, since the lab is still in use.

## Decisions

**The one rule behind every choice: the lab adds beside the AI team's setup and never edits it.** Docker,
its containerd, the NVIDIA driver and toolkit, the firewall's existing rules and the root disk stay as
they are; where k3s would touch something shared, the lab either moves its own part elsewhere or checks
the shared part before and after.

| # | Question | Decision | Why (machine fact, 2026-10-25) |
|---|---|---|---|
| 1 | Where k3s keeps its data | Everything bulky on `/mnt/data`: the k3s data directory (images, cluster state, volumes) at `/mnt/data/k3s`, and `/var/lib/kubelet` as a **bind mount** of `/mnt/data/k3s-kubelet` | `/` is 98% full (9 GB free) and shared; `/mnt/data` has 467 GB free. The kubelet path must stay `/var/lib/kubelet` because `k3s-killall.sh` unmounts pod volumes only under that path; a bind mount keeps the path and moves the bytes (read in the v1.36.5 installer) |
| 2 | Which container runtime | k3s's **own** containerd (its default), not Docker (`--docker`) | Docker's daemon, its containerd and `/etc/containerd/config.toml` stay untouched; k3s's containerd lives under its data directory and `/run/k3s` |
| 3 | Which container toolkit | The **host's** (1.20.1, already used by Docker); k3s detects it at start and registers the `nvidia` runtime and RuntimeClass | Installed and working for Docker. The Operator's toolkit pod rewrites a containerd config and restarts containerd; with the host toolkit there is nothing for it to do, and no risk of it editing Docker's config |
| 4 | GPU Operator | Installed by Argo CD with `driver.enabled=false` and `toolkit.enabled=false`; device plugin, GPU feature discovery, Node Feature Discovery, DCGM exporter and validator on | Host driver 610.43.02 ([D4](../design.md#decisions)); host toolkit (row 3) |
| 5 | GPU sharing | No GPU is reserved. A lab pod asks for `nvidia.com/gpu: 1` only after the pre-check's listing of the GPUs' processes and memory has been read; phase 1 runs one short CUDA test pod. Pinning the lab to one GPU, or time-slicing, is decided in the 2b spec (training) with real lab loads | Both GPUs were in use by the AI team (GPU 1 at 99%), a use Kubernetes cannot see ([why](../notes/gpus-on-the-hosts-driver.md#what-kubernetes-cannot-see)) |
| 6 | Packaged k3s parts | Traefik and ServiceLB **disabled**; CoreDNS, local-path storage (on `/mnt/data/k3s/storage`), metrics-server and the network policy controller kept | Traefik would take ports 80 and 443 on the machine through ServiceLB, which binds host ports, and on a shared machine a host port may already be in use. Nothing in the lab is exposed outside the cluster in phase 1 |
| 7 | Address ranges | k3s defaults: pods `10.42.x.x/16`, services `10.43.x.x/16` | The machine has no route in either, and Docker's bridges use other ranges |
| 8 | Firewall | ufw stays on with the AI team's rules, never edited. The lab's rules go **first**: allow from the pod range `10.42.0.0/16` and the Service range `10.43.0.0/16`, then deny k3s's ports (`k3s_ports` in [vars.yml](../../infra/ansible/vars.yml), listed from the machine with `ss`) to everyone else, for IPv4 and IPv6, all commented `ml-lab k3s`. The API is reached only through SSH (row 10) | ufw takes the first matching rule, and a rule already on the machine, higher in the list, let a laptop on the office VPN reach 6443 (found on 2026-10-30, [why](../notes/kubernetes-on-a-shared-machine.md#the-firewall-takes-the-first-match)); the same rule would admit k3s's other ports, so all three are denied. The tunnel arrives on `lo`, accepted before any user rule. k3s documents the two allows for ufw ("If you wish to keep ufw enabled, by default, the following rules are required", [requirements](https://docs.k3s.io/installation/requirements), 2026-10-25). Pod traffic passing **through** the machine is accepted by Flannel's `FLANNEL-FWD` chain (A4) |
| 9 | Kernel changes k3s makes | Accepted, with a check: at start k3s loads `br_netfilter` (not loaded before the lab) and sets `bridge-nf-call-iptables=1` and IPv4 forwarding (read in [`syssetup/setup.go`](https://github.com/k3s-io/k3s/blob/master/pkg/agent/syssetup/setup.go), 2026-10-25). With `br_netfilter`, traffic between containers on one Docker bridge passes iptables' FORWARD chain, whose policy is DROP; Docker's own rules already accept everything coming from each of its bridges (`DOCKER-FORWARD -i br-... -j ACCEPT`) and replies (`DOCKER-CT`) | The module stays loaded until a reboot; the acceptance checks compare the AI team's containers before and after |
| 10 | kubectl from the laptop | Through SSH: a tunnel from the laptop's `127.0.0.1:16443` to the machine's `127.0.0.1:6443` over `gpu-box-relay` (home) or `gpu-box` (office); the kubeconfig in `.scratch_kube/config` points at the tunnel | No open port, works through the [Windows relay](../notes/wsl-and-a-full-tunnel-vpn.md#fix-2-a-relay-through-windows-for-the-lab-machine); k3s's certificate covers `127.0.0.1` |
| 11 | When k3s runs | **Only during lab sessions** ([why](../notes/kubernetes-on-a-shared-machine.md#a-cluster-that-exists-only-during-a-session)): installed but not enabled at boot; `lab-up` starts it after pre-checks, `lab-down` stops it with `k3s-killall.sh` | Between sessions the machine is the AI team's alone; a reboot never starts the lab |
| 12 | `K3S_DATA_DIR` | Every call of `k3s-killall.sh` and `k3s-uninstall.sh` sets `K3S_DATA_DIR=/mnt/data/k3s` | Both scripts take the data directory only from that variable (default `/var/lib/rancher/k3s`), not from k3s's config: without it, killall finds none of the lab's pod processes and the GPU memory stays held |
| 13 | Tailscale | `lab-down` and `teardown` stop if the machine advertises Tailscale routes | `k3s-killall.sh` runs `tailscale set --advertise-routes=` when Tailscale is installed, which would clear them; none are advertised (`AdvertiseRoutes: None`) |
| 14 | How Argo CD is installed | Ansible drops a k3s **HelmChart** manifest for the `argo-cd` chart into k3s's auto-deploy folder; k3s's helm-controller installs it. Argo CD then manages everything else from the lab's repo, starting with the GPU Operator | No Helm on the machine or the laptop; "installing a Helm chart on your cluster can be automated by creating a single file on disk" ([K3s Helm](https://docs.k3s.io/add-ons/helm), read 2026-10-25 through a summarising tool) |
| 15 | Deploy keys | Phase 1 creates **one**: Argo CD's read-only key, generated **on the machine**, stored only as a cluster Secret. The machine's own key for git ([D10](../design.md#decisions)) is created when a phase first needs git on the machine | Least privilege: nothing on the machine pulls git in phase 1 ([the handoff](../notes/ansible-and-argo-cd.md#the-handoff)) |
| 16 | Versions | k3s **v1.36.5+k3s1** (stable channel; containerd 2.3.4), GPU Operator **v26.7.2**, Argo CD chart **10.11.1** (Argo CD v3.5.6), pinned in the code | Read 2026-10-25 from the k3s channel server, the NGC Helm index and the argo-helm index. The Operator needs containerd 2.0 or newer for CDI ([RKE2](https://docs.rke2.io/add-ons/gpu_operators), 2026-10-25) |

## Layout

```
 Laptop (WSL)                                   GPU box
 ┌─────────────────────────────┐               ┌───────────────────────────────────────────────────────────┐
 │ ansible-playbook infra/...  │──ssh (relay)─►│ AI team (untouched): Docker + its containerd, 22 running  │
 │ kubectl → 127.0.0.1:16443   │══tunnel══════►│ containers, host driver 610.43.02, toolkit 1.20.1, ufw    │
 │ .scratch_kube/config        │               │                                                           │
 └─────────────────────────────┘               │ Lab (only while it works):                                │
                                               │   k3s v1.36.5 (own containerd)  data: /mnt/data/k3s       │
 GitHub: the lab's private repo                │   /var/lib/kubelet ◄─bind─ /mnt/data/k3s-kubelet          │
   infra/argocd/ (apps, values)  ◄──read-only──│   Argo CD ──► GPU Operator (driver off, toolkit off)      │
                deploy key                     │   ufw: the lab's 5 rules first (row 8)                    │
                                               └───────────────────────────────────────────────────────────┘
```

The AI team's side as read on 2026-10-25; their container count changes through the day.

## Ansible playbooks

All under `infra/ansible/`, run from the laptop's repo root, always shown first with `--check --diff`
([D4](../design.md#decisions), [safety](../../AGENTS.md#safety-and-approvals)). The inventory reaches the
machine through `.scratch_ssh/config` (`gpu-box-relay` from home, `gpu-box` at the office). Ansible itself is
installed in the gitignored `.venv/`, pinned in the repo.

| Playbook | Does | Leaves |
|---|---|---|
| `bootstrap.yml` | Pre-checks; adopts `/etc/sudoers.d/<user>` (D13); creates `/mnt/data/k3s` and `/mnt/data/k3s-kubelet` and the bind-mount unit for `/var/lib/kubelet`; writes k3s's config (rows 1, 6, 7, 16); puts the lab's ufw rules first (row 8: two allows, then denies for k3s's ports, IPv4 and IPv6); installs k3s at the pinned version with the installer at a pinned checksum, **not enabled at boot**, and without the installer's `kubectl`, `crictl` and `ctr` links in `/usr/local/bin` (they would change those commands for every user of the machine); drops the Argo CD HelmChart and the root Application manifest into the auto-deploy folder | k3s installed and stopped |
| `lab-up.yml` | Pre-checks (below); mounts `/var/lib/kubelet`; starts k3s; waits for the node `Ready`; fetches the kubeconfig to `.scratch_kube/config` pointing at the tunnel | k3s running |
| `lab-down.yml` | Tailscale check (row 13); stops k3s; `K3S_DATA_DIR=/mnt/data/k3s k3s-killall.sh` (row 12); unmounts `/var/lib/kubelet`; checks no k3s process and no lab process on the GPUs | k3s stopped, data kept |
| `deploy-key.yml` | Generates Argo CD's key pair on the machine (root-only, outside any repo), prints the **public** half for me to add on GitHub as a read-only deploy key, and creates the Argo CD repo Secret from the private half inside the running cluster (never as a manifest file) | The key on the machine (root-only) and in the cluster only |
| `teardown.yml` | Everything in [teardown](#teardown) | The machine as before the lab |
| `check.yml` | Read-only: the [box check](#box-check-and-masked-output) | A check file on the laptop; nothing on the machine |
| `footprint.yml` | Read-only: what changed on the machine since the baseline, for the [teardown inventory](#teardown) | A scan file on the laptop; nothing on the machine |

Every playbook is idempotent: a second run reports no change.

**Pre-checks** (bootstrap and lab-up stop if one fails; the values are in the code):

| Check | Why |
|---|---|
| Free memory above a floor (6 GiB available in phase 1; 10 GiB since the [data path](data-path.md#box-budget)) | The AI team comes first; 13 GiB were available at the read of 2026-10-25, with 10 GiB of swap in use |
| `/` keeps at least 5 GB free, `/mnt/data` at least 50 GB | Row 1 |
| `nvidia-smi` answers; the GPU processes are listed in the run's output | Row 5 |
| Ports 6443, 10250 and 8472/udp free | k3s's ports |
| No Tailscale routes advertised | Row 13 |

## Box check and masked output

**One read-only playbook records the machine's state, so every "before vs after" is one `diff`.** `check.yml`
changes nothing and reads:

- free memory and swap, and the GPUs' processes and memory;
- Docker's running containers and their health;
- the sha256 of `/etc/docker/daemon.json` and `/etc/containerd/config.toml`;
- Docker's and Tailscale's iptables chains, and the ufw rules;
- k3s's state: unit, process, mounts and folders.

It writes the result, through `tools/mask.py` (below), to the gitignored `.scratch_box/checks/<time>.txt` on the
laptop. Its uses:

- **Baseline:** taken before `bootstrap`.
- **Every session:** run by `lab-up` and `lab-down`, so each session's start and end are compared.
- **Acceptance A5:** the AI team's Docker is unchanged.
- **Teardown:** the machine equals the baseline.

**Any output the agent shows or a runbook records passes through `tools/mask.py`.** It keeps internal
(private) addresses in full (the public export then masks their last two parts) and masks public IPv4 and global
IPv6 addresses (the VPN server's, the home connection's) and every name listed in the gitignored
`.scratch_box/mask-words` (the machine's hostname, which is also its Kubernetes node name). It is the single copy of
that rule ([safety](../../AGENTS.md#safety-and-approvals)). It grew from two incidents: tool output that printed an
address, and the hostname showing up as the Kubernetes node name.

## GPU stack

Driver and toolkit come from the host (rows 3, 4). k3s, at start, finds `nvidia-container-runtime` and
adds the `nvidia` runtime to its containerd and the `nvidia` RuntimeClass
([K3s advanced](https://docs.k3s.io/advanced), 2026-10-25). The GPU Operator, installed by Argo CD from
NVIDIA's Helm repository at the pinned version, adds the device plugin (which advertises
`nvidia.com/gpu: 2`), feature discovery, the DCGM exporter (for phase 3b) and the validator. GPU pods
use `runtimeClassName: nvidia`. Argo CD's components and the test pod carry their own memory limits, and the data
path's namespaces get default memory limits and a quota ([box budget](data-path.md#box-budget)), so no lab pod runs
unbounded next to the AI team.

## Argo CD

- Installed once by the k3s HelmChart (row 14), in namespace `argocd`, with the components the lab does
  not use turned off (Dex, notifications) and resource limits on the rest.
- Reads the lab's private repo (this public one is exported from it) over SSH with its own read-only deploy key
  (row 15, [the handoff](../notes/ansible-and-argo-cd.md#the-handoff)); GitHub's host key is trusted from the
  chart's default known hosts (`argocd-ssh-known-hosts-cm`), not pinned by the lab.
- One root Application (app of apps) points at `infra/argocd/apps/`; phase 1 holds one child, the GPU
  Operator (Helm chart from NVIDIA's repository, values from the repo). Automated sync with self-heal;
  prune on.
- The UI and API stay inside the cluster: reached with `kubectl port-forward` through the SSH tunnel.

Because Argo CD reads GitHub, a change to `infra/argocd/` reaches the machine only after a `git push`, which
from home needs the VPN off ([why](../notes/wsl-and-a-full-tunnel-vpn.md#what-works-now-and-the-one-rule-left)).

## Sharing the box

- **Before k3s is installed, I tell the AI team**: what will run (k3s, GPU Operator, Argo CD),
  when (lab sessions only, stopped in between), what changes on the machine (rows 1, 8, 9, 11), and the
  teardown.
- Lab sessions start with `lab-up` (pre-checks) and end with `lab-down`; between sessions no lab process
  runs on the machine.
- Nothing the lab installs listens on the office network: no open port, no NodePort, no LoadBalancer.

## Teardown

**After teardown the machine is as if the lab never existed.** Every item the lab adds is in one of the tables below,
each with the step that removes it and the check that proves it, or in "left until the next reboot" with the reason.
This section is the single list: `teardown.yml` implements it, the [teardown runbook](../runbooks/gpu-box-teardown.md)
runs it, acceptance A10 checks every row has a step. A later spec that adds anything to the machine adds its row here
in the same commit.

**What the scan covered** (read-only, 2026-10-30, with the lab up and after `lab-down`;
[footprint.yml](../../infra/ansible/footprint.yml), at the lowest CPU and disk priority, 14 s): k3s's
sockets; files changed since the 14:54 baseline under `/etc`, `/usr`, `/var`, `/opt`, `/srv`, `/root`,
`/home`, `/boot`, `/run`, `/tmp`, `/dev/shm` and the top of `/mnt/data`; the folders that act at boot;
kernel modules, settings, ipsets and AppArmor. A path counts as the lab's when its creation time falls in a
lab session and nothing else uses it (`/run/netns`, created at 10:44 before the lab, is not). Not covered:
anything the lab changed before the baseline (the sudoers rule and the login key of 2026-10-23, both in the
tables). `footprint.yml` runs again right before the real teardown; anything new becomes a row here.

**What the scan cannot see**, so the inventory never relies on it alone: files deleted or only re-permissioned
(it compares modification times), files that keep an old timestamp (unpacked from an archive), anything
outside the folders above (`/var/lib/docker`, `/var/lib/containerd`, `/mnt/data` below its top two levels,
the AI team's own disks), and changes made before the baseline. That is why every row also comes from
reading the playbooks and k3s's code, and why each change to the machine adds its row in the same commit
([AGENTS.md](../../AGENTS.md#living-docs-and-the-journal-never-mixed-owner-2026-10-25)).

### What the lab adds to the box

| What | Created by | Removed by (step) | Checked by |
|---|---|---|---|
| Running k3s, its containers, mounts, `cni0`, `flannel.1`, pod network spaces, `KUBE-`/`CNI-`/`FLANNEL` iptables and ip6tables rules | k3s at start | 1 (`lab-down`) | lab-down's counts, all 0 |
| `/usr/local/bin/k3s`, `k3s-killall.sh`, `k3s-uninstall.sh`, `k3s.service`, `k3s.service.env`, `/etc/rancher/k3s`, `/run/k3s`, `/run/flannel`, `/var/lib/cni`, `/var/lib/kubelet`, the data dir `/mnt/data/k3s` (images, cluster state, every cluster Secret, the CA) | The installer, k3s | 3 (`K3S_DATA_DIR=/mnt/data/k3s k3s-uninstall.sh`, read in the v1.36.5 installer) | Each absent |
| The data path's state ([2a spec](data-path.md#teardown-additions)): its volumes on local-path under `/mnt/data/k3s/storage` (Postgres, Kafka, SeaweedFS; Debezium's offsets and Spark's checkpoint and package cache when they come), the operators' CRDs and webhooks, the `lab-data` Secrets (role passwords, the S3 key, made by `infra/scripts/lab-credentials.py`) | Argo CD, the operators, the credentials step | 3, inside the data dir | `/mnt/data/k3s` absent |
| `/etc/rancher/node`, `/etc/rancher`, `/var/log/pods`, `/var/log/containers` (the pods' logs, on `/`) | k3s, the kubelet; **not** removed by k3s's scripts | 4 | Each absent |
| Host paths the GPU Operator and the kubelet write (scan, 2026-10-30): `/usr/libexec/kubernetes/kubelet-plugins/volume/exec` (the kubelet, created 15:02:58, empty folders), `/run/nri/nri.sock` (k3s's containerd, created at each start; nothing listens once k3s stops), `/var/run/cdi/k8s.device-plugin.nvidia.com-gpu.json` (the device plugin's; the host's `nvidia.yaml` beside it stays), `/run/nvidia/{driver,mps,validations}` (created 19:44, the Operator's first sync), `/etc/kubernetes/node-feature-discovery` (NFD; `/etc/kubernetes` itself created by it) | GPU Operator pods (host paths) | 4, only paths absent from the baseline | Each absent; `/var/run/cdi` equals the baseline |
| kube-router's ipsets `KUBE-*` | k3s's network policy controller; **not** removed by k3s's scripts | 2 | `ipset list -n` has no `KUBE-` set |
| `var-lib-kubelet.mount`, `k3s.service.d/`, `/mnt/data/k3s-kubelet` | `bootstrap.yml` | 5, then `daemon-reload` and `reset-failed` | `systemctl list-unit-files 'k3s*' 'var-lib-kubelet*'` empty |
| ufw rules commented `ml-lab k3s` (IPv4 and IPv6) | `bootstrap.yml` | 6 | ufw rules equal the baseline's |
| `/etc/ml-lab/` (Argo CD's key pair) | `deploy-key.yml` | 7 | Absent |
| `/root/.ansible`, `~/.ansible`, `/root/.kube` (the API discovery cache of `k3s kubectl` run as root) | Ansible, the playbooks' `k3s kubectl` calls (scan, 2026-10-30) | 7 and 11 | Absent |
| `/etc/sudoers.d/<user>` (D13) | Me, 2026-10-23; adopted by `bootstrap.yml` | 10 | `sudo -n true` fails |
| The laptop's key in `~/.ssh/authorized_keys`; `~/.ssh` itself (both created by `ssh-copy-id`, 2026-10-23 15:52:31, holding nothing else) | Me, 2026-10-23 | 11, last: the whole `~/.ssh` while it holds only the lab's key, else the key line only | `ssh -o BatchMode=yes gpu-box true` refused |
| Kernel modules k3s and Flannel load that were not loaded before: `br_netfilter`, `vxlan`, `udp_tunnel`, `ip6_udp_tunnel`, `ip_set`, `xt_set` (scan, 2026-10-30). `overlay`, `nf_conntrack`, `iptable_nat`, `iptable_filter` are shared with Docker and stay | k3s at start (`syssetup/setup.go`), Flannel | 8, if unused; else the next reboot | `lsmod` |
| containerd's AppArmor profile `cri-containerd.apparmor.d` (enforce; scan, 2026-10-30) | k3s's containerd | 8, if loaded; else the next reboot | AppArmor's loaded profiles |

### Credentials and access

Revoked at the server first: the GitHub deploy key is deleted right after step 1.

| Credential or access | Where | Removed by | Checked by |
|---|---|---|---|
| Argo CD's deploy key, public half | GitHub: repo Settings, Deploy keys | **Me**, after step 1; `teardown.yml` pauses until confirmed | The page lists none |
| The same key, private half | `/etc/ml-lab/` and the cluster Secret in `/mnt/data/k3s` | Steps 7 and 3 | Both absent |
| Argo CD's admin password, every cluster Secret, the cluster's CA | `/mnt/data/k3s` | Step 3 | Absent |
| The cluster's admin certificate, laptop copy | `.scratch_kube/config` | The runbook's laptop step | Absent |
| Passwordless sudo | `/etc/sudoers.d/<user>` | Step 10 | `sudo -n true` fails |
| The laptop's login | `~/.ssh/authorized_keys` on the machine; `.scratch_ssh/` on the laptop | Step 11; [reach the box, roll back](../runbooks/reach-the-box.md#roll-back) | BatchMode login refused; files absent |
| The account's `sudo` group membership | Granted by the AI team's admin for the lab (2026-10-23) | I ask the AI team, if the account has no other use | Their `id -nG` |

### Nothing survives a boot

**The lab writes nothing that acts at boot**, so any reboot of the machine, whenever the AI team has one,
clears its kernel leftovers by itself; the lab never asks for a reboot.

| Could act at boot | The lab's state | Checked by |
|---|---|---|
| systemd units | k3s `disabled` (row 11); the mount unit has no `[Install]` | `systemctl is-enabled k3s`; no lab link in `/etc/systemd/system/*.wants` |
| Modules at boot | Nothing in `/etc/modules-load.d` or `/etc/modprobe.d`; k3s runs `modprobe` at start only | Scan of 2026-10-30: nothing changed there since the baseline |
| Kernel settings at boot | Nothing in `/etc/sysctl.d` or `/etc/sysctl.conf`; k3s writes `/proc/sys` at start only | Scan of 2026-10-30: unchanged |
| AppArmor, udev, cron, `rc.local`, netplan, NetworkManager | Nothing written | Scan of 2026-10-30: no file changed since the baseline; in `/etc/systemd/system`, only the lab's own `k3s.service`, its `.env` and `.d`, and `var-lib-kubelet.mount` |

A reboot while the lab is installed is safe too: k3s does not start and `/var/lib/kubelet` is not mounted.

### Left until the box's next reboot

The kernel settings k3s sets at start (`syssetup/setup.go`, v1.36.5): IPv4 forwarding (`all`, `default`),
`bridge-nf-call-iptables` (gone with `br_netfilter`), `nf_conntrack_max` and the conntrack TCP timeouts,
and any module still in use. Their pre-lab values were never recorded, so teardown does not guess them;
the next reboot restores the machine's own. Their values with the lab up (scan, 2026-10-30): forwarding `1`,
`1`; `bridge-nf-call-iptables` `1`; `nf_conntrack_max` `917504`; established and close-wait timeouts `86400`
and `3600` s. `check.yml` records them from 2026-10-30, and the runbook lists their values at teardown.
Also left: the lab's lines in the machine's shared system logs (journald, `syslog`, `kern.log`, `auth.log`,
`ufw.log`), which belong to everyone on the machine.

### Steps

[teardown.yml](../../infra/ansible/teardown.yml), in order, each verified before the next:

1. `lab-down`; then pause until I confirm the GitHub deploy key is deleted (revoked at the server first).
2. Destroy kube-router's `KUBE-*` ipsets, with k3s's own `ipset` tool (the machine has none), so before step 3
   removes it.
3. `K3S_DATA_DIR=/mnt/data/k3s k3s-uninstall.sh`.
4. Remove what k3s leaves: `/etc/rancher`, `/var/log/pods`, `/var/log/containers`, the device plugin's CDI
   file, the GPU Operator's host folders (`/etc/kubernetes`, `/run/nvidia`), `/usr/libexec/kubernetes` and
   `/run/nri` (each whole only if nothing else is in it or uses it).
5. Remove `var-lib-kubelet.mount`, `k3s.service.d/`, `/mnt/data/k3s-kubelet`; `daemon-reload`.
6. Delete the lab's ufw rules (the two allows, the denies for IPv4 and IPv6).
7. Remove `/etc/ml-lab`, `/root/.ansible`, `/root/.kube`.
8. Unload the modules the lab loaded where nothing uses them; remove containerd's AppArmor profile; list
   what the kernel keeps until the next reboot.
9. `check.yml -e label=teardown`, compared with the baseline and with every table above.
10. Remove `/etc/sudoers.d/<user>`; check `sudo -n true` fails.
11. Remove `~/.ansible`, then the laptop's login, last: the whole `~/.ssh` while it holds only the lab's key
    (as `ssh-copy-id` created it), else only the key line; check from the laptop that the key login is
    refused.

## Acceptance

Phase 1 is done when all of these hold, recorded with real output in
[bootstrap, step 8](../runbooks/gpu-box-bootstrap.md#8-acceptance):

| # | Check | Expected |
|---|---|---|
| A1 | `kubectl get nodes` through the tunnel | One node, `Ready`, v1.36.5+k3s1 |
| A2 | The node's allocatable `nvidia.com/gpu` | `2` |
| A3 | CUDA test pod (NVIDIA's `nbody` sample, `runtimeClassName: nvidia`, one GPU) | Completes; its log shows a GeForce RTX 3060 and a benchmark result |
| A4 | Argo CD: the root app and the GPU Operator app | `Synced` and `Healthy`; GPU Operator pods `Running` or `Completed`. This also proves pod traffic passes the firewall both ways: to the API (ufw rule) and through the machine to GitHub (Flannel) |
| A5 | The AI team's Docker, before vs after bootstrap and after lab-down | Same running containers with the same health; `/etc/docker/daemon.json` and `/etc/containerd/config.toml` unchanged (sha256); Docker's iptables chains unchanged; their GPU processes still listed by `nvidia-smi` |
| A6 | Root disk | Free space on `/` drops by less than 1 GB across bootstrap, lab-up and the test pod |
| A7 | `lab-down` | No k3s process, no lab process on the GPUs, `/var/lib/kubelet` unmounted; `lab-up` again brings the node back `Ready` with Argo CD synced (start-up time measured) |
| A8 | Idle footprint | Memory used by k3s, Argo CD and the GPU Operator at rest, measured |
| A9 | Second run of each playbook | No change reported |
| A10 | `teardown.yml --check --diff` | Shows the removal of every row of [teardown](#teardown) and nothing of the AI team's; every row names a step or a reason (run for real only when the lab ends) |
| A11 | The firewall's three trips ([why the order matters](../notes/kubernetes-on-a-shared-machine.md#the-firewall-takes-the-first-match)), run for real | Trip 1, a pod to the API through ufw rule 1: the GPU Operator's pods find the node's GPUs (A2). Trip 2, a pod out through Flannel's lane: Argo CD fetched from GitHub (A4). Trip 3, outside to k3s's ports: from Windows over the VPN, `Test-NetConnection <box> -Port 6443` and `-Port 10250` report `False` and port 22 `True`, while `kubectl get nodes` through the SSH tunnel answers (A1) |

**As run** (2026-10-30), where a check ran narrower than worded here:

| Check | As worded | As run |
|---|---|---|
| A5 | Their GPU processes still listed by `nvidia-smi` | The baseline compared with the checks after bootstrap (14:56) and after lab-down (20:03): containers and their health, both sha256 and Docker's chains unchanged. The GPU lines were left out of both comparisons as moving values |
| A6 | Free space on `/` drops by less than 1 GB | Measured as the size of the lab's own paths on `/`, 76 MB, since free space also moves with the AI team's writes; the lab's data, 3.7 GB, is on `/mnt/data` |
| A9 | Each playbook | The four that change the machine (bootstrap, deploy-key, lab-up, lab-down) reported no change on a second run; `check.yml` and `footprint.yml` change nothing by design, and `teardown.yml` has run only as its preview (A10) |
| A10 | The removal of every row | The preview (22:27) reported steps 3 to 7, 10 and 11; steps 1, 2 and 8 (the deploy-key pause, the ipsets, the modules and the AppArmor profile) cannot run in check mode and were skipped. The data path's row was added after it |

## Not chosen

| Option | Why not |
|---|---|
| k3s with `--docker` (Docker as its runtime) | Lab pods would share the AI team's Docker daemon: their `docker ps` fills with lab containers, a Docker restart takes the lab down, and the reverse |
| The GPU Operator's toolkit (`toolkit.enabled=true`) | It rewrites a containerd config and restarts containerd; the host toolkit already works, and a wrong path would edit Docker's containerd config |
| `ufw disable` (k3s's first recommendation) | It is the AI team's firewall, not the lab's |
| Opening 6443 to the office network | The API would be reachable by anyone on the office network; the SSH tunnel needs no open port |
| kubelet `root-dir` moved, or a symlink | `k3s-killall.sh` then misses pod mounts (row 1) |
| Argo CD installed with Helm from the laptop | Needs Helm on the laptop and the API reachable for the install; the HelmChart file needs neither |
| k3s left running between sessions | Holds memory and k3s's network on a shared machine ([trade-off](../notes/kubernetes-on-a-shared-machine.md#a-cluster-that-exists-only-during-a-session)) |
