#!/usr/bin/env python3

from flask import Flask
from flask_restful import Api, Resource, reqparse
from werkzeug.exceptions import NotFound
import subprocess as shell
import re
from ntfy import notify
import bluetooth
import requests
import httpx
import asyncio
from uuid import uuid4
import json
from hashlib import md5
from string import Template
from enum import Enum

# Local imports
import magic
from tvcom.serial_lookup import SerialLookup


class MerossDeviceType(Enum):
    BULB = 0
    SOCKET = 1


app = Flask(__name__)
api = Api(app)
bind_port = 8080
base_path = "/v1/"
serial_port = '/dev/ttyUSB0'
timeout = 5
meross_devices = {
    "office": {
        'hostname': "192.168.1.140",
        'device_type': MerossDeviceType.BULB
    },
    "hall_down": {
        "hostname": "192.168.1.141",
        "device_type": MerossDeviceType.BULB
    },
    "hall_up": {
        "hostname": "192.168.1.142",
        "device_type": MerossDeviceType.BULB
    },
    "attic": {
        "hostname": "192.168.1.148",
        "device_type": MerossDeviceType.BULB
    },
    "bedroom": {
        "hostname": "192.168.1.144",
        "device_type": MerossDeviceType.BULB
    },
    "livingroom": {
        "hostname": "192.168.1.145",
        "device_type": MerossDeviceType.BULB
    },
    "livingroom_lamp": {
        "hostname": "192.168.1.146",
        "device_type": MerossDeviceType.BULB
    },
    "kitchen": {
        "hostname": "192.168.1.147",
        "device_type": MerossDeviceType.BULB
    },
    "kitchen_2": {
        "hostname": "192.168.1.143",
        "device_type": MerossDeviceType.BULB
    },
    "plant": {
        "hostname": "192.168.1.150",
        "device_type": MerossDeviceType.SOCKET
    },
    "kitchen_socket": {
        "hostname": "192.168.1.151",
        "device_type": MerossDeviceType.SOCKET
    },
    "test_socket": {
        "hostname": "192.168.1.159",
        "device_type": MerossDeviceType.SOCKET
    }
}
magic_hosts = {
        "pc": "2c:f0:5d:56:40:43",
    "shitcube": "e0:d5:5e:3c:2f:6c"
}


class SendAlert(Resource):
    def __init__(self):
        self.reqparse = reqparse.RequestParser()
        self.reqparse.add_argument('message', required=True, help="variable required")
        self.reqparse.add_argument('title')
        self.reqparse.add_argument('priority')
        self.reqparse.add_argument('api_token')

    def put(self):
        args = self.reqparse.parse_args()
        # Assign a default value to title if nothing was recieved in request
        args['title'] = "flask" if args['title'] is None else args['title']
        # Filter out None's from the dict and pass the cleaned dict directly to ntfy as kwargs
        if notify(**dict(filter(lambda a: a[1] is not None, args.items()))) != 0:
            return {'message': 'Unexpected response'}, 500
        return {'message': 'Success'}, 200


async def meross_multi_put(hosts, json, timeout):
    async with httpx.AsyncClient() as client:
        tasks = (client.put(f'http://localhost:{bind_port}{base_path}meross/{host}', headers={'Content-Type': 'application/json'}, timeout=timeout, json=json) for host in hosts)
        return {req.url.path.split('/')[-1]: req.json() for req in await asyncio.gather(*tasks)}
            

class MerossDeviceBase(Resource):

    def __init__(self, devices, timeout):
        self.timeout = timeout
        self.devices = list(devices)
        self.reqparse = reqparse.RequestParser()

    def get(self):
        return {'endpoint': self.devices}, 200

    def put(self):
        self.reqparse.add_argument('hosts', required=True, help="variable required")
        self.reqparse.add_argument('code', required=True, help="variable required")
        self.reqparse.add_argument('value')
        args = self.reqparse.parse_args()
        json = {'code': args['code'], 'value': args['value']} if args['value'] else {'code': args['code']}

        hosts = args['hosts'].split(',')
        if not all(host in self.devices for host in hosts):
            return {'message': 'Invalid hosts'}, 400

        try:
            return asyncio.run(meross_multi_put(hosts, json, self.timeout)), 200
        except e:
            return e, 500
        


class MerossDevice(Resource):
    def __init__(self, host, device_type, timeout):
        self.reqparse = reqparse.RequestParser()
        self.host = host
        self.timeout = timeout
        self.device_type = device_type

        self.messageId = str(uuid4())  # arbitrary string
        self.timestamp = 0

        self.sign = md5(f'{self.messageId}{self.timestamp}'.encode()).hexdigest()  # sign is md5 of messageId+timestamp

        self.base_json = Template('{ "header": { "messageId": "${messageId}",  "method": "${method}", \
                                   "namespace": "${namespace}", "payloadVersion": 1, "sign": "${sign}",\
                                   "timestamp": ${timestamp} }, "payload": ${payload}}')

        self.payloads = {}
        if device_type is MerossDeviceType.BULB or device_type is MerossDeviceType.SOCKET:
            self.payloads['toggle'] = ['Appliance.Control.ToggleX', Template('{"togglex":{"onoff": ${value}}}')]
            self.payloads['status'] = ['Appliance.System.All', '{}']
        if device_type is MerossDeviceType.BULB:
            self.payloads['luminance'] = ['Appliance.Control.Light', Template('{"light":{"capacity":4, "luminance": ${value}}}')]
            self.payloads['temperature'] = ['Appliance.Control.Light', Template('{"light":{"capacity":2, "temperature": ${value}}}')]
            self.payloads['rgb'] = ['Appliance.Control.Light', Template('{"light":{"capacity":1, "rgb": ${value}}}')]

    def get(self):
        return {"codes": list(self.payloads.keys())}, 200

    def put(self):
        self.reqparse.add_argument('code', required=True, help="variable required")
        self.reqparse.add_argument('value')
        args = self.reqparse.parse_args()

        if args['code'] not in self.payloads:
            return {'message': 'Invalid code'}, 400

        value = None
        if self.payloads[args['code']][0] == 'Appliance.Control.Light':
            if args['value'] is None:  # must pass a value parameter when using Appliance.Control.Light namespace
                return {'message': {'value': "variable required"}}, 400

            if args['code'] == 'rgb':
                try:
                    value = int(args['value'], 16)  # convert hex color code to int - e.g ff00ff
                    if value > 0xffffff or value < 0x000000:
                        return {'message': 'value not a valid hex color (000000 -ffffff)'}
                except ValueError:
                    return {'message': 'value not a valid hex color (000000 -ffffff)'}
            else:
                try:
                    value = max(-1, min(int(args['value'], 10), 100))  # Clamp to range -1 -100
                except ValueError:
                    return {'message': 'value not a valid integer (1-100)'}
        else:
            if args['value'] is None or args['code'] == 'status':
                # Retrieve current state of bulb
                payload = self.payloads['status'][1]
                try:
                    request = requests.post(f'http://{self.host}/config', headers={'Content-Type': 'application/json'}, timeout=self.timeout,
                                            json=json.loads(self.base_json.substitute(messageId=self.messageId, method='GET',
                                                                                      namespace=self.payloads['status'][0], sign=self.sign,
                                                                                      timestamp=self.timestamp, payload=payload)))
                except requests.exceptions.RequestException as e:
                    return {'message': 'Unexpected response'}, 500

                if request.status_code != 200:
                    return {'message': 'Unexpected response'}, 500

                req_json = request.json()['payload']['all']['digest']
                if args['code'] == 'status':
                    # Construct a stripped down json object describing the bulbs current state
                    ret_json = {}
                    if self.device_type is MerossDeviceType.BULB or self.device_type is MerossDeviceType.SOCKET:
                        ret_json['onoff'] = req_json['togglex'][0]['onoff']
                    if self.device_type is MerossDeviceType.BULB:
                        ret_json['rgb'] = f"{req_json['light']['rgb']:x}"  # convert returned decimal to hexstring e.g ff00ff
                        ret_json['temperature'] = req_json['light']['temperature']
                        ret_json['luminance'] = req_json['light']['luminance']
                    return ret_json, 200
                else:
                    value = 1 - int(req_json['togglex'][0]['onoff'])  # store an inverted copy of the bulbs current onoff state

            elif args['value'] == '0' or args['value'] == '1':
                value = args['value']
            else:
                return {'message': 'value is not a valid integer (0-1)'}

        # Substitute parsed value into payload, and then substitute the payload and other required fields into base_json before
        # sending the constructed json on to the bulb
        payload = self.payloads[args['code']][1].substitute(value=value)
        try:
            request = requests.post(f'http://{self.host}/config', headers={'Content-Type': 'application/json'}, timeout=self.timeout,
                                    json=json.loads(self.base_json.substitute(messageId=self.messageId, method='SET',
                                                                              namespace=self.payloads[args['code']][0], sign=self.sign,
                                                                              timestamp=self.timestamp, payload=payload)))
        except requests.exceptions.RequestException as e:
            return {'message': 'Unexpected response'}, 500
        if request.status_code != 200:
            return {'message': 'Unexpected response'}, 500
        return {'message': 'Success'}, 200


class WakeHost(Resource):
    def __init__(self, host, mac_address):
        self.host = host
        self.mac_address = mac_address
        self.reqparse = reqparse.RequestParser()
        self.codes = ['power', 'status']
        # super().__init__()

    def get(self):
        return {"code": self.codes}, 200

    def put(self):
        self.reqparse.add_argument('code', required=True, help="variable required")
        args = self.reqparse.parse_args()
        if args['code'] not in self.codes:
            return {'message': 'Invalid code'}, 400

        state = getattr(magic, args['code'])(self.host, self.mac_address)

        if args['code'] == "status":
            return {'status': 'on' if state else 'off'}, 200
        elif not state:
            return {'message': "Unexpected response"}, 500

        return {'message': 'Success'}, 200


class LEDRemote(Resource):
    def __init__(self, device_name):
        self.device_name = device_name
        self.reqparse = reqparse.RequestParser()
        # super().__init__()

    def get(self):
        # Run irsend to get a raw list of keycodes for self.device_name
        raw_list = shell.check_output(["irsend", "list", self.device_name, ""])

        # Format keycodes; convert to lowercase string, split into a list and subset
        decoded_list = raw_list.decode("utf-8").lower().split()[1::2]

        return {"code": decoded_list}, 200

    def put(self):
        # Ensure that a 'code' var has been passed in the request
        self.reqparse.add_argument('code', required=True, help="variable required")
        args = self.reqparse.parse_args()
        # Check that the passed code is in the list that our get method returns
        if args['code'] not in self.get()[0]['code']:
            return {'message': 'Invalid code'}, 400

        # Check return code of our irsend command to catch failure.
        if shell.call(["irsend", "send_once", self.device_name, args['code']]) != 0:
            return {'message': 'Non zero return code'}, 500

        return {'message': 'Success'}, 200


class BluetoothRemoteBase(Resource):
    def __init__(self, devices):
        self.devices = devices

    def get(self):
        return {'endpoint': self.devices}, 200


class BluetoothRemote(Resource):
    def __init__(self, lirc_device, serial, timeout):
        self.serial = serial
        self.lirc_device = lirc_device
        self.timeout = timeout

        global active_btsocket  # persistant socket
        try:
            if active_btsocket.getpeername()[0] != self.serial:  # serial device changed
                self._init_socket()
        except:
            self._init_socket()
        self.socket = active_btsocket

        # Run irsend and split to get a rough cut list list of keycodes for configured device
        raw_list = shell.check_output(["irsend", "list", self.lirc_device, ""]).decode("utf-8").lower().split()
        # Format the list of codes into a dict of name/hex_value
        self.codes = dict([raw_list[i + 1], raw_list[i][-8:]]for i in range(0, len(raw_list), 2))

        self.reqparse = reqparse.RequestParser()

    # (Re)establish connection to a serial bluetooth module
    def _init_socket(self):
        global active_btsocket
        active_btsocket.close()
        active_btsocket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        active_btsocket.connect((self.serial, 1))
        active_btsocket.settimeout(self.timeout)

    def get(self):
        return {"code": list(self.codes.keys())}, 200

    def put(self):
        # Ensure that a 'code' var has been passed in the request
        self.reqparse.add_argument('code', required=True, help="variable required")
        args = self.reqparse.parse_args()
        # Check that the passed code is in the list that our get method returns
        if args['code'] not in self.codes:
            return {'message': 'Invalid code'}, 400

        try:
            # send 8 digit hex string to device
            self.socket.send(f"{self.codes.get(args['code'])}\r".encode())
            # Build a 4 byte response from return data, blocking on each byte
            response = b''
            while len(response) < 4:
                data = self.socket.recv(1)
                if not data:
                    break
                response += data

            if len(response) != 4 or response[:2] != b'OK':
                if len(response) == 0:
                    return {'message': "No response"}, 500
                else:
                    return {'message': "Unexpected response"}, 500
            return {'message': 'Success'}, 200
        except:
            return {'message': "Unexpected response"}, 500


class TvComBase(Resource):

    def get(self):
        return {'endpoint': ['{}'.format(i.long_name) for i in SerialLookup.lookups]}, 200


class TvCom(Resource):

    def __init__(self, bluetooth_address, timeout, instance):
        self.instance = instance
        self.bluetooth_address = bluetooth_address
        self.timeout = timeout
        self.reqparse = reqparse.RequestParser()
        
        global active_btsocket  # persistant socket
        try:
            
            if active_btsocket.getpeername()[0] != self.bluetooth_address:  # serial device changed
                self._init_socket()
        except:
            self._init_socket()
        self.socket = active_btsocket

    # (Re)establish connection to a serial bluetooth module
    def _init_socket(self):
        global active_btsocket
        active_btsocket.close()
        active_btsocket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
        active_btsocket.connect((self.bluetooth_address, 1))
        active_btsocket.settimeout(self.timeout)

    def serial_comm(self, key_code):
        self.socket.send(f"{self.instance.name} 00 {self.instance.get_keycode(key_code)}\r".encode())
        # Build a 10 byte response from return data, blocking on each byte
        response = ""
        while len(response) < 10:
            data = self.socket.recv(1)
            if not data:
                break
            response += data.decode()
        success = True if response[5:7] == "OK" else False
        payload = self.instance.get_desc(response[7:9])
        return success, payload 

    def get(self):
        # Extract list of values from dictionary
        code_list = [self.instance.lookup_table[k] for k in self.instance.lookup_table.keys()]
        # If we are a slider, append an item for each integer from 0 to 100
        if self.instance.is_slider:
            for i in range(101):
                code_list.append("{}".format(i))
        return {"code": code_list}, 200


    def put(self):
        try:

            self.reqparse.add_argument('code', required=True, help="variable required")
            args = self.reqparse.parse_args()
            # If 'code' var was not in request OR (if 'code' var is not in our list of valid codes AND is not a slider)
            # OR (is a slider and value is not a 1 to 3 digit integer), return error
            if 'code' not in args or (args['code'] not in self.instance.inverse_table and not self.instance.is_slider) \
                    or (self.instance.is_slider and not re.match("(^[\+-]?[0-9]{1,3}$)|(^status$)", args['code'])):
                return {'message': 'Invalid code'}, 400

            if self.instance.is_slider and re.match("^[\+-][0-9]{1,3}$", args['code']):
                success, payload = self.serial_comm('status')

                if not success:
                    return {'message': "Unexpected response"}, 500

                args['code'] = payload + int(args['code'])

            success, payload = self.serial_comm(args['code'])

            if not success:
                return {'message': "Unexpected response"}, 500

            if args['code'] == "status":
                return {'status': payload}, 200
            return {'message': 'Success'}, 200

        except bluetooth.BluetoothError:
            return {'message': "Unexpected response"}, 500

class Snowdon(Resource):

    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.reqparse = reqparse.RequestParser()
        self.codes = ["status", "power", "mute", "volume_up", "volume_down", "previous", "next", "play_pause", "input", "treble_up", "treble_down", "bass_up", "bass_down", "pair", "flat", "music", "dialog", "movie"]

    def get(self):
        return self.codes, 200

    def put(self):
        self.reqparse.add_argument('code', required=True, help="variable required")
        args = self.reqparse.parse_args()

        if 'code' not in args or args['code'] not in self.codes:
            return {'status': 'Invalid code'}, 400
        try:
            request = requests.put(f'http://{self.host}:{self.port}/?code={args["code"]}', timeout=self.timeout)
        except requests.exceptions.RequestException as e:
            return {'status': 'Unexpected response'}, 500

        if request.status_code != 200:
            return {'status': 'Unexpected response'}, 500

        return request.json(), 200

class Root(Resource):
    def __init__(self, rules):
        self.rules = rules

    def get(self):
        return {'endpoint': [r for r in self.rules]}, 200


@app.errorhandler(NotFound)
def handle_notfound(e):
    return {'message': e.name}, 404


# ntfy
api.add_resource(SendAlert, '{0}{1}'.format(base_path, "alert"), endpoint='alert')

# Define base resource that will allow a GET for serial objects
api.add_resource(TvComBase, '{0}{1}'.format(base_path, "tvcom"), endpoint='tvcom')

# Define api endpoints for each serial object
active_btsocket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
for instance in SerialLookup.lookups:
    name = instance.long_name
    api.add_resource(TvCom, '{0}{1}{2}'.format(base_path, "tvcom/", name), endpoint=name,
                     resource_class_kwargs={'instance': instance,
                                            'bluetooth_address': '00:14:03:05:0D:28',
                                            'timeout': timeout})
for name, mac_address in magic_hosts.items():
    api.add_resource(WakeHost, '{0}{1}'.format(base_path, name), endpoint=name,
                     resource_class_kwargs={'host': name,
                                            'mac_address': mac_address})

api.add_resource(MerossDeviceBase, '{0}{1}'.format(base_path, "meross"), endpoint='meross',
        resource_class_kwargs={'devices': meross_devices.keys(), 'timeout': timeout})
for name, settings in meross_devices.items():
    api.add_resource(MerossDevice, '{0}{1}{2}'.format(base_path, "meross/", name), endpoint=name,
                     resource_class_kwargs={'host': settings.get('hostname'),
                     'device_type': settings.get('device_type'), 'timeout': 1.5})

api.add_resource(Snowdon, '{0}{1}'.format(base_path, "snowdon"), endpoint='snowdon',
        resource_class_kwargs={'host': '192.168.1.160', 'port': 8080, 'timeout': 10})

regex = re.compile(f'^{base_path}[^/]*?$')
rules = [i.rule for i in app.url_map.iter_rules()]
filtered_rules = [r.split('/')[-1] for r in rules if regex.match(r)]
api.add_resource(Root, '/'.join(base_path.split('/')[:-1]) , endpoint='',
                 resource_class_kwargs={'rules': filtered_rules})
api.add_resource(Root, base_path, endpoint='/',
                 resource_class_kwargs={'rules': filtered_rules})
if __name__ == '__main__':
    from waitress import serve
    from paste.translogger import TransLogger
    serve(TransLogger(app, setup_console_handler=False), host='0.0.0.0', port=bind_port, threads=10)#, threads=1)
