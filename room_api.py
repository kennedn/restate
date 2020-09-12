#!/usr/bin/env python3.7

from flask import Flask
from flask_restful import Api, Resource, reqparse
from werkzeug.exceptions import NotFound
from serial import Serial
import subprocess as shell
import re
from ntfy import notify

# Local imports
import magic
from tvcom.serial_lookup import serial_lookup


app = Flask(__name__)
api = Api(app)
base_path = "/api/v1.0/"
serial_port = '/dev/ttyAMA0'
serial_timeout = 3
remotes = ["strip", "bulb"]
hosts = [["pc", "e0:3f:49:9f:a3:c8"]]


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
            return "Endpoint did not respond correctly", 500
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
            return "{} is not a valid code".format(args['code']), 400

        state = getattr(magic, args['code'])(self.host, self.mac_address)

        if args['code'] == "status":
            return {'status': 'on' if state else 'off'}, 200
        elif not state:
            return "Endpoint did not respond correctly to '{}'".format(args['code']), 500

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
            return "{} is not a valid code".format(args['code']), 400

        # Check return code of our irsend command to catch failure.
        if shell.call(["irsend", "send_once", self.device_name, args['code']]) != 0:
            return "{} code send failed".format(args['code']), 500

        return {'message': 'Success'}, 200


class TvComBase(Resource):

    def get(self):
        return {'endpoint': ['/{}'.format(i.long_name) for i in serial_lookup]}, 200


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
                    or (self.instance.is_slider and not re.match("(^[0-9]{1,3}$)|(^status$)", args['code'])):
                return "{} is not a valid code".format(args['code']), 400

            raw_name = self.instance.name
            keycode = self.instance.get_keycode(args['code'])

            serial.write("{0} 00 {1}\r".format(raw_name, keycode).encode())
            response = serial.read(10).decode()

            if len(response) != 10 or response[5:7] == "NG":
                return "Endpoint did not respond correctly to '{}'".format(args['code']), 500

            if args['code'] == "status":
                return {'status': self.instance.get_desc(response[7:9])}, 200

            return {'message': 'Success'}, 200
        finally:
            serial.close()


@app.errorhandler(NotFound)
def handle_notfound(e):
    return {'message': e.name}, 404

# ntfy
api.add_resource(SendAlert, '{0}{1}'.format(base_path, "alert"), endpoint='alert')

# Define api endpoints for LED IR Remote objects
for r in remotes:
    api.add_resource(LEDRemote, '{0}{1}'.format(base_path, r), endpoint=r,
                     resource_class_kwargs={'device_name': 'led_{}'.format(r)})

# Define base resource that will allow a GET for serial objects
api.add_resource(TvComBase, '{0}{1}'.format(base_path, "tvcom"), endpoint='tvcom')

# Define api endpoints for each serial object
for instance in serial_lookup:
    name = instance.long_name
    api.add_resource(TvCom, '{0}{1}{2}'.format(base_path, "tvcom/", name), endpoint=name,
                     resource_class_kwargs={'instance': instance,
                                            'serial_port': serial_port,
                                            'serial_timeout': serial_timeout})
for h in hosts:
    api.add_resource(WakeHost, '{0}{1}'.format(base_path, h[0]), endpoint=h[0],
                     resource_class_kwargs={'host': h[0],
                                            'mac_address': h[1]})
if __name__ == '__main__':
    app.run(host='0.0.0.0', port='80', debug=True)
