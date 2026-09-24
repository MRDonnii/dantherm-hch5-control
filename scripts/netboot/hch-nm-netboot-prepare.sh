#!/bin/sh
set -eu
plugin_dir=/usr/lib/arm-linux-gnueabihf/NetworkManager/1.42.4
profile_dir=/etc/NetworkManager/system-connections
runtime_dir=/run/hch-nm-netboot
[ -d "$plugin_dir" ] || exit 0
[ -d "$profile_dir" ] || exit 0
mkdir -p "$runtime_dir/plugins" "$runtime_dir/connections"
chmod 700 "$runtime_dir/connections"
mount -t tmpfs -o size=8m,mode=755,exec tmpfs "$runtime_dir/plugins"
cp -a "$plugin_dir"/. "$runtime_dir/plugins"/
cp -a "$profile_dir"/. "$runtime_dir/connections"/
if [ -d /var/lib/dantherm-admin/nm-connections ]; then
    cp -a /var/lib/dantherm-admin/nm-connections/. "$runtime_dir/connections"/
fi
mount --bind "$runtime_dir/plugins" "$plugin_dir"
mount --bind "$runtime_dir/connections" "$profile_dir"
