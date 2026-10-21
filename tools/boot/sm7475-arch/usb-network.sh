#!/bin/busybox sh
# SPDX-License-Identifier: GPL-2.0-only
# ACM rescue shell plus CDC ECM, usable in both initramfs and the Arch rootfs.
set -eu

G=/sys/kernel/config/usb_gadget/g1
mkdir -p /sys/kernel/config
mountpoint -q /sys/kernel/config || mount -t configfs configfs /sys/kernel/config
mkdir -p "$G"
if [ -s "$G/UDC" ] && [ -n "$(cat "$G/UDC")" ]; then
    echo '' > "$G/UDC"
fi
echo 0x1d6b > "$G/idVendor"
echo 0x0104 > "$G/idProduct"
echo 0x0101 > "$G/bcdDevice"
echo 0x0200 > "$G/bcdUSB"
mkdir -p "$G/strings/0x409" "$G/configs/c.1/strings/0x409"
echo sm7475-arch > "$G/strings/0x409/serialnumber"
echo realme > "$G/strings/0x409/manufacturer"
echo 'GT Neo5 SE Arch' > "$G/strings/0x409/product"
echo 'ACM and ECM' > "$G/configs/c.1/strings/0x409/configuration"
mkdir -p "$G/functions/acm.0" "$G/functions/ecm.usb0"
echo 02:74:75:00:00:01 > "$G/functions/ecm.usb0/host_addr"
echo 02:74:75:00:00:02 > "$G/functions/ecm.usb0/dev_addr"
for function in acm.0 ecm.usb0; do
    [ -L "$G/configs/c.1/$function" ] ||
        ln -s "$G/functions/$function" "$G/configs/c.1/$function"
done
for device in a600000.usb 88e3000.phy; do
    control=/sys/bus/platform/devices/$device/power/control
    [ ! -e "$control" ] || echo on > "$control"
done
tries=0
while :; do
    udc=$(ls /sys/class/udc | head -n 1)
    [ -z "$udc" ] || break
    tries=$((tries + 1))
    [ "$tries" -lt 30 ] || exit 1
    sleep 1
done
echo "$udc" > "$G/UDC"
interface=$(cat "$G/functions/ecm.usb0/ifname")
ip link set "$interface" up
ip addr add 192.168.77.2/24 dev "$interface" 2>/dev/null || true
ip route add default via 192.168.77.1 dev "$interface" 2>/dev/null || true
echo "USB ACM + ECM ready: $interface 192.168.77.2/24"
