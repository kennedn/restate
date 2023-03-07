#!/bin/bash

# Enable dbus
service dbus start

# Enable bluetooth
sed -i 's/^\(BLUETOOTH_ENABLED=\)0/\11/' /etc/init.d/bluetooth
service bluetooth start

echo -n "Waiting for services to start..."
while pidof start-stop-daemon &> /dev/null; do sleep 0.1; done
echo "Done"

while ! bluetoothctl power on; do sleep 0.1; done
bluetoothctl agent on

# Wait for discovery of device
echo -n "Waiting on device discovery..."
bluetoothctl scan on &
scan_pid="$!"
while ! bluetoothctl devices | grep -q 00:14:03:05:0D:28; do sleep 0.1; done
kill "${scan_pid}"
echo "Done"

python3 simple-agent.py 00:14:03:05:0D:28

python3 restate.py
