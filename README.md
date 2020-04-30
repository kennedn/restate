# roomAPI
Flask-restful API implementatation that unites disseminated automations.

E.g Lets me control my TV and LED light bulb/strip via a restful service.

## How to run
python3 (preferably 3.7 for dict insertion order preservation) needs to be installed, along with the following modules:
- flask
- flask-restful
- pyserial 

This can be achieve in debain linux variants by doing:

```bash
sudo apt install python3.7
```
```bash
python3.7 -m pip install flask flask-restful pyserial
```
Once the dependancies have been met the program can be run as follows:
```bash
chmod 755 room_api.py
./room_api.py
```

Python is cross platform and this should work on windows.

