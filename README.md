# roomAPI
Flask-restful API implementatation that unites a varied bunch of automations.

Currently it allows control of the following:

|Endpoint|Description|
|---|---|
|alert|Forwards on notifications to the python ntfy module|
|tvcom|Allows control of an LCD Tv via a serial port connection, [see here](https://github.com/kennedn/TvCom) for the helper script.|
|bulb|Sends infrared codes to an IR LED bulb.|
|strip|Sends infrared codes to an IR LED strip.|
|pc|Sends magic packet (Wake-on-LAN) and pings to control power state of my computer, [see here](https://github.com/kennedn/Action-On-LAN) for how to turn computers off with magic packets.|
## How to run
python3 (preferably 3.7 for dict insertion order preservation) needs to be installed, along with the following modules:
- flask
- flask-restful
- pyserial
- icmplib
- ntfy

This can be achieve in debain linux variants by doing:

```bash
sudo apt install python3.7
```
```bash
python3.7 -m pip install flask flask-restful pyserial icmplib
```
Once the dependancies have been met the program can be run as follows:
```bash
chmod 755 room_api.py
./room_api.py
```

Python is cross platform and this should work on windows.

