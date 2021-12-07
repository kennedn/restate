#!/usr/bin/env python3

from flask import Flask
from flask_restful import Api, Resource, reqparse
from werkzeug.exceptions import NotFound
from serial import Serial, SerialException
import subprocess as shell
import re
from ntfy import notify
import bluetooth
import requests
from uuid import uuid4
from time import time
import json
from hashlib import md5
from string import Template

# Local imports
import magic
from tvcom.serial_lookup import SerialLookup


app = Flask(__name__)
api = Api(app)
base_path = "/api/v1.0/"
serial_port = '/dev/ttyUSB0'
timeout = 5
#remotes = ["strip", "lamp", "bulb"]
wifi_bulbs = [["office", "192.168.1.140"],["hall_down", "192.168.1.141"],["hall_up", "192.168.1.142"],["attic", "192.168.1.143"],["bedroom", "192.168.1.144"],["livingroom", "192.168.1.145"], ["livingroom_lamp", "192.168.1.146"]]
hosts = [["pc", "2c:f0:5d:56:40:42"], ["shitcube", "e0:d5:5e:3c:2f:6c"]]
#bt_hosts = [
#    {
#        "name": "bt1",
#        "devices": ["bulb", "strip"],
#        "serial": "98:D3:32:30:CA:73"
#    },
#    {
#        "name": "bt2",
#        "devices": ["bulb", "strip"],
#        "serial": "98:D3:91:FD:EF:F6"
#    }
#]


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


class WiFiBulbBase(Resource):

    def __init__(self, bulbs):
        self.bulbs = bulbs

    def get(self):
        return {'endpoint': [b[0] for b in self.bulbs]}, 200


class WiFiBulb(Resource):
    def __init__(self, host, timeout):
        self.reqparse = reqparse.RequestParser()
        self.host = host
        self.timeout = timeout

        self.messageId = str(uuid4())  # arbitrary string
        #self.timestamp = str(int(time()))  # unix epoch
        self.timestamp = 0

        self.sign = md5(f'{self.messageId}{self.timestamp}'.encode()).hexdigest()  # sign is md5 of messageId+timestamp

        self.base_json = Template('{ "header": { "messageId": "${messageId}",  "method": "${method}", \
                                   "namespace": "${namespace}", "payloadVersion": 1, "sign": "${sign}",\
                                   "timestamp": ${timestamp} }, "payload": ${payload}}')
        self.payloads = {}
        self.payloads['toggle'] = ['Appliance.Control.ToggleX', Template('{"togglex":{"onoff": ${value}}}')]
        self.payloads['luminance'] = ['Appliance.Control.Light', Template('{"light":{"capacity":4, "luminance": ${value}}}')]
        self.payloads['temperature'] = ['Appliance.Control.Light', Template('{"light":{"capacity":2, "temperature": ${value}}}')]
        self.payloads['rgb'] = ['Appliance.Control.Light', Template('{"light":{"capacity":1, "rgb": ${value}}}')]
        self.payloads['status'] = ['Appliance.System.All', '{}']

    def get(self):
        return {"codes": list(self.payloads.keys())}, 200

    def put(self):
        self.reqparse.add_argument('code', required=True, help="variable required")
        self.reqparse.add_argument('value', help="variable required")
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
                    if value > 16777215 or value < 0:
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
                    print(e)
                    return {'message': 'Unexpected response'}, 500

                if request.status_code != 200:
                    return {'message': 'Unexpected response'}, 500

                req_json = request.json()['payload']['all']['digest']
                if args['code'] == 'status':
                    # Construct a stripped down json object describing the bulbs current state
                    ret_json = {
                        'onoff': req_json['togglex'][0]['onoff'],
                        'rgb': f"{req_json['light']['rgb']:x}",  # convert returned decimal to hexstring e.g ff00ff
                        'temperature': req_json['light']['temperature'],
                        'luminance': req_json['light']['luminance']
                        }
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
            print(e)
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

    def __init__(self, serial_port, serial_timeout, instance):
        self.instance = instance
        self.port = serial_port
        self.timeout = serial_timeout
        self.reqparse = reqparse.RequestParser()

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
            serial = Serial(self.port, timeout=self.timeout)

            self.reqparse.add_argument('code', required=True, help="variable required")
            args = self.reqparse.parse_args()
            # If 'code' var was not in request OR (if 'code' var is not in our list of valid codes AND is not a slider)
            # OR (is a slider and value is not a 1 to 3 digit integer), return error
            if 'code' not in args or (args['code'] not in self.instance.inverse_table and not self.instance.is_slider) \
                    or (self.instance.is_slider and not re.match("(^[\+-]?[0-9]{1,3}$)|(^status$)", args['code'])):
                return {'message': 'Invalid code'}, 400

            if self.instance.is_slider and re.match("^[\+-][0-9]{1,3}$", args['code']):
                raw_name = self.instance.name
                keycode = self.instance.get_keycode('status')

                serial.write("{0} 00 {1}\r".format(raw_name, keycode).encode())
                response = serial.read(10).decode()

                if len(response) != 10 or response[5:7] == "NG":
                    if len(response) == 0:
                        return {'message': "No response"}, 500
                    else:
                        return {'message': "Unexpected response"}, 500

                if args['code'][0] == '-':
                    args['code'] = self.instance.get_desc(response[7:9]) - int(args['code'][1::])
                elif args['code'][0] == '+':
                    args['code'] = self.instance.get_desc(response[7:9]) + int(args['code'][1::])


            raw_name = self.instance.name
            keycode = self.instance.get_keycode(args['code'])

            serial.write("{0} 00 {1}\r".format(raw_name, keycode).encode())
            response = serial.read(10).decode()

            if len(response) != 10 or response[5:7] == "NG":
                if len(response) == 0:
                    return {'message': "No response"}, 500
                else:
                    return {'message': "Unexpected response"}, 500

            if args['code'] == "status":
                return {'status': self.instance.get_desc(response[7:9])}, 200

            return {'message': 'Success'}, 200
        except SerialException:
            return {'message': "Unexpected response"}, 500
        finally:
            serial.close()


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

# Define api endpoints for LED IR Remote objects
#for r in remotes:
#    api.add_resource(LEDRemote, '{0}{1}'.format(base_path, r), endpoint=r,
#                     resource_class_kwargs={'device_name': r})
#
## Create a persistant bluetooth socket outside of class so that multiple calls
## to the same device do not require subsiquent reconnection
#active_btsocket = bluetooth.BluetoothSocket(bluetooth.RFCOMM)
## Define api endpoints for LED IR Remote objects
#for host in bt_hosts:
#    name = host.get('name')
#    serial = host.get('serial')
#    api.add_resource(BluetoothRemoteBase, '{0}{1}'.format(base_path, name), endpoint=name,
#                     resource_class_kwargs={'devices': host.get('devices')})
#    for device in host.get('devices'):
#        api.add_resource(BluetoothRemote, '{0}{1}/{2}'.format(base_path, name, device), endpoint=f'{name}_{device}',
#                         resource_class_kwargs={'lirc_device': device, 'serial': serial, 'timeout': timeout})
#
# Define base resource that will allow a GET for serial objects
api.add_resource(TvComBase, '{0}{1}'.format(base_path, "tvcom"), endpoint='tvcom')

# Define api endpoints for each serial object
for instance in SerialLookup.lookups:
    name = instance.long_name
    api.add_resource(TvCom, '{0}{1}{2}'.format(base_path, "tvcom/", name), endpoint=name,
                     resource_class_kwargs={'instance': instance,
                                            'serial_port': serial_port,
                                            'serial_timeout': timeout})
for h in hosts:
    api.add_resource(WakeHost, '{0}{1}'.format(base_path, h[0]), endpoint=h[0],
                     resource_class_kwargs={'host': h[0],
                                            'mac_address': h[1]})

api.add_resource(WiFiBulbBase, '{0}{1}'.format(base_path, "wifi_bulb"), endpoint='wifi_bulb',
                 resource_class_kwargs={'bulbs': wifi_bulbs})
for b in wifi_bulbs:
    api.add_resource(WiFiBulb, '{0}{1}{2}'.format(base_path, "wifi_bulb/", b[0]), endpoint=b[0],
                     resource_class_kwargs={'host': b[1], 'timeout': 1.5})

regex = re.compile(f'^{base_path}[^/]*?$')
rules = [i.rule for i in app.url_map.iter_rules()]
filtered_rules = [r.split('/')[-1] for r in rules if regex.match(r)]
api.add_resource(Root, '/api/v1.0', endpoint='',
                 resource_class_kwargs={'rules': filtered_rules})
api.add_resource(Root, '/api/v1.0/', endpoint='/',
                 resource_class_kwargs={'rules': filtered_rules})
if __name__ == '__main__':
    app.run(host='0.0.0.0', port='80', debug=True)
