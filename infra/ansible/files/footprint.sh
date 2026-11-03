#!/bin/bash
# Read-only: the lab's footprint on the box, for the teardown inventory (docs/specs/gpu-box-platform.md#teardown).
# Run as root by footprint.yml with SINCE (the baseline's time), at the lowest CPU and disk priority so the AI
# team's work comes first. Lists what changed since SINCE where anything can write, what acts at boot, and the
# kernel state k3s changes. Changes nothing.
set -u
SINCE=${SINCE:?}
section() { printf '\n## %s\n' "$1"; }
fold() {  # one line per lab or system area instead of every file
  sed -E 's#^(/var/log/(pods|containers)|/var/lib/(kubelet|cni)|/root/\.kube|/root/\.ansible|/home/[^/]+/\.ansible|/run/k3s|/run/nvidia|/run/flannel)/.*#\1/...#' \
  | sed -E 's#^(/var/lib/(apt|dpkg|snapd|systemd|fwupd|NetworkManager|update-notifier|tailscale|polkit-1|PackageKit|sss|ubuntu-advantage|logrotate|sysstat|private))(/.*)?$#\1 (the system)#' \
  | sed -E 's#^(/var/log/[^/]+)$#\1 (log)#; s#^/var/log/[^/]+/.*#/var/log/... (log)#; s#^(/home/[^/]+/(\.local|\.cache|\.config|snap|\.mozilla|\.vscode-server|\.cursor-server))(/.*)?$#\1/... (the user)#; s#^(/root/\.local)/.*#\1/... (the system)#' \
  | sed -E 's#^(/run/(user|systemd|udev|NetworkManager|dbus|lock|log|sudo|snapd|tailscale|containerd|docker))(/.*)?$#\1 (the system)#' \
  | sort -u
}

section "k3s's sockets outside 127.0.0.1"
ss -Hlntup | awk '{print $1, $5, $7}' | sed -E 's/,pid=[0-9]+,fd=[0-9]+//g' | grep -v '127.0.0.1:' | grep 'k3s' || echo "none (k3s stopped)"
ss -Hlnu | awk '{print "udp", $4, "(kernel)"}' | grep -E ':8472 ' || echo "no udp 8472"

section "changed since $SINCE on the root disk"
find /etc /usr /var /opt /srv /root /home /boot -xdev \
  \( -path /var/lib/docker -o -path /var/lib/containerd -o -path /var/log/journal -o -path /var/cache -o -path '/home/*/snap' \) -prune \
  -o -newermt "$SINCE" -print 2>/dev/null | fold

section "changed since $SINCE in memory filesystems (/run, /tmp, /dev/shm)"
# /tmp and /dev/shm hold other users' files, named after them: only the lab's names are listed, the rest counted
mem=$(for d in /run /tmp /dev/shm; do find "$d" -xdev -newermt "$SINCE" -print 2>/dev/null; done | grep -vE '^/run/(user|systemd|udev)/')
lab='k3s|kube|rancher|cni|flannel|nvidia|nri|ml-lab|ansible|argocd'
grep -E '^/run/' <<< "$mem" | fold
grep -E '^/(tmp|dev/shm)/' <<< "$mem" | grep -iE "$lab" | fold
echo "other users' files in /tmp and /dev/shm, not listed: $(grep -E '^/(tmp|dev/shm)/' <<< "$mem" | grep -viEc "$lab" || true)"

section "/mnt/data, top two levels, changed since $SINCE"
find /mnt/data -maxdepth 2 -newermt "$SINCE" -print 2>/dev/null | sort

section "what acts at boot, changed since $SINCE"
find /etc/modules-load.d /etc/modprobe.d /etc/sysctl.d /etc/sysctl.conf /etc/apparmor.d /etc/udev /etc/cron.d \
     /etc/crontab /etc/rc.local /etc/netplan /etc/NetworkManager/system-connections /etc/systemd/system \
     -newermt "$SINCE" 2>/dev/null | sort
echo "enabled at boot, k3s or lab: $(ls /etc/systemd/system/*.wants 2>/dev/null | grep -ciE 'k3s|kubelet|ml-lab' || true)"

section "kernel state k3s changes"
echo "modules: $(lsmod | awk 'NR>1 {print $1}' | grep -xE 'br_netfilter|vxlan|udp_tunnel|ip6_udp_tunnel|ip_set|xt_set|overlay|nf_conntrack|iptable_nat|iptable_filter' | sort | tr '\n' ' ')"
for k in net.ipv4.conf.all.forwarding net.ipv4.conf.default.forwarding net.bridge.bridge-nf-call-iptables \
         net.netfilter.nf_conntrack_max net.netfilter.nf_conntrack_tcp_timeout_established net.netfilter.nf_conntrack_tcp_timeout_close_wait; do
  echo "$k = $(sysctl -n $k 2>/dev/null || echo absent)"
done
ipset_bin=$(command -v ipset || ls /mnt/data/k3s/data/current/bin/ipset 2>/dev/null || true)
echo "ipsets KUBE-*: $([ -n "$ipset_bin" ] && $ipset_bin list -n 2>/dev/null | grep -c '^KUBE-' || echo 'no ipset tool')"
echo "apparmor cri-containerd profile: $(grep -c 'cri-containerd' /sys/kernel/security/apparmor/profiles 2>/dev/null || echo 0)"
exit 0
