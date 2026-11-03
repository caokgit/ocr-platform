#!/bin/bash
# Read-only report of the box's state, run as root by check.yml. Reads only; changes nothing.
# The first section is a summary; the others hold the details compared before and after the lab.
set -u
section() { printf '\n## %s\n' "$1"; }

mem_avail=$(free -m | awk '/^Mem:/ {print $7}')
swap_used=$(free -m | awk '/^Swap:/ {print $3}')
running=$(docker ps -q 2>/dev/null | wc -l)
healthy=$(docker ps --filter health=healthy -q 2>/dev/null | wc -l)
unhealthy=$(docker ps --filter health=unhealthy -q 2>/dev/null | wc -l)

section "summary"
echo "time: $(date '+%F %T %z')"
echo "load: $(cut -d' ' -f1-3 /proc/loadavg)"
echo "memory available: ${mem_avail} MiB; swap used: ${swap_used} MiB"
nvidia-smi --query-gpu=index,memory.used,memory.total,utilization.gpu --format=csv,noheader \
  | sed 's/^/gpu /'
echo "docker: ${running} running, ${healthy} healthy, ${unhealthy} unhealthy"
echo "k3s: unit $(systemctl is-active k3s 2>/dev/null; true), at boot $(systemctl is-enabled k3s 2>/dev/null; true), processes $(pgrep -c -f '^/usr/local/bin/k3s'; true)"
echo "ufw: $(ufw status | head -1)"
df -h --output=target,avail / /mnt/data | tail -n +2 | awk '{print "disk " $1 ": " $2 " free"}'

section "gpu processes (count, MiB, per GPU)"
nvidia-smi --query-compute-apps=gpu_uuid,used_memory --format=csv,noheader,nounits \
  | awk -F', ' 'NR==FNR {idx[$2]=$1; next} {n[idx[$1]]++; m[idx[$1]]+=$2} END {for (g in n) print "gpu " g ": " n[g] " processes, " m[g] " MiB"}' \
    <(nvidia-smi --query-gpu=index,uuid --format=csv,noheader) - | sort

section "docker containers (name, status)"
docker ps --format 'table {{.Names}}\t{{.Status}}' | tail -n +2 | sed -E 's/Up [^(]*/Up/' | sort

section "config files (sha256)"
sha256sum /etc/docker/daemon.json /etc/containerd/config.toml 2>&1

section "iptables: Docker's and Tailscale's chains"
iptables -S | grep -E '^-(P|N|A) (DOCKER|ts-)'
iptables -t nat -S | grep -E '^-(N|A) (DOCKER|ts-)' | sed 's/^/nat /'

section "ufw rules"
ufw status numbered | tail -n +4

section "tailscale advertised routes"
tailscale debug prefs 2>/dev/null | grep -o '"AdvertiseRoutes": [^]]*]\|"AdvertiseRoutes": null' || echo "tailscale: no prefs"

section "k3s footprint"
for p in /usr/local/bin/k3s /etc/rancher/k3s /mnt/data/k3s /mnt/data/k3s-kubelet /var/lib/kubelet /run/k3s /var/lib/cni; do
  [ -e "$p" ] && echo "present: $p" || echo "absent:  $p"
done
findmnt -n /var/lib/kubelet >/dev/null && echo "mounted: /var/lib/kubelet" || echo "not mounted: /var/lib/kubelet"
lsmod | grep -q '^br_netfilter' && echo "module br_netfilter: loaded" || echo "module br_netfilter: not loaded"
echo "k3s's own iptables rules (KUBE-, CNI-, FLANNEL): $( { iptables-save; ip6tables-save; } | grep -ciE 'KUBE-|CNI-|FLANNEL' || true)"
echo "pod network spaces: $(ls /run/netns 2>/dev/null | grep -c '^cni-' || true); lab links (cni0, flannel): $(ip -br link | grep -cE '^(cni0|flannel)' || true)"
ls /etc/sudoers.d | sed 's/^/sudoers.d: /'

section "kernel state k3s changes at start (until the next reboot)"
lsmod | awk 'NR>1 {print $1}' | grep -xE 'br_netfilter|vxlan|overlay|nf_conntrack|iptable_nat|iptable_filter|ip_set|xt_set|ip_vs' | sort | sed 's/^/module loaded: /'
for k in net.ipv4.conf.all.forwarding net.ipv4.conf.default.forwarding net.ipv6.conf.all.forwarding \
         net.bridge.bridge-nf-call-iptables net.netfilter.nf_conntrack_max \
         net.netfilter.nf_conntrack_tcp_timeout_established net.netfilter.nf_conntrack_tcp_timeout_close_wait; do
  echo "sysctl $k = $(sysctl -n $k 2>/dev/null || echo absent)"
done
ipset_bin=$(command -v ipset || ls /mnt/data/k3s/data/current/bin/ipset 2>/dev/null || true)
[ -n "$ipset_bin" ] && echo "ipsets KUBE-*: $($ipset_bin list -n 2>/dev/null | grep -c '^KUBE-' || true)" || echo "ipsets KUBE-*: no ipset tool"
echo "apparmor cri-containerd profile: $(grep -c 'cri-containerd' /sys/kernel/security/apparmor/profiles 2>/dev/null || echo 0)"

section "host folders the GPU Operator and k3s may write"
for d in /var/run/cdi /etc/cdi /run/nvidia /etc/kubernetes /etc/rancher /var/log/pods /var/log/containers; do
  [ -e "$d" ] && echo "$d: $(find "$d" -mindepth 1 -maxdepth 2 2>/dev/null | wc -l) entries: $(ls -1 "$d" 2>/dev/null | head -8 | tr '\n' ' ')" || echo "$d: absent"
done

section "what acts at boot (must not change)"
for d in /etc/modules-load.d /etc/modprobe.d /etc/sysctl.d; do
  echo "$d: $(find "$d" -type f -exec sha256sum {} + 2>/dev/null | sort | sha256sum | cut -c1-16)"
done
echo "/etc/sysctl.conf: $(sha256sum /etc/sysctl.conf 2>/dev/null | cut -c1-16)"
echo "enabled at boot, k3s or lab: $(ls /etc/systemd/system/*.wants 2>/dev/null | grep -ciE 'k3s|kubelet|ml-lab' || true)"
exit 0
