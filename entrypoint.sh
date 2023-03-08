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
bluetoothctl scan on &> /dev/null &
scan_pid="$!"
while ! bluetoothctl devices 2> /dev/null | grep -q "${BT_ADDRESS}"; do sleep 0.1; done
kill "${scan_pid}"
echo "Done"

python3 headless-bluetooth-pair.py

python3 restate.py
