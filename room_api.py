#!/usr/bin/python
from flask import Flask
from flask_restful import Api, Resource, reqparse
from tvcom.serial_lookup import *
import subprocess as shell
import re
from serial import Serial

app = Flask(__name__)
api = Api(app)
base_path = "/api/v1.0/"
serial_port = '/dev/ttyAMA0'
serial_timeout = 3

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

        return {"codes": decoded_list}, 200

    def put(self):
        # Ensure that a 'code' var has been passed in the request
        self.reqparse.add_argument('code', required=True, help="variable required")
        args = self.reqparse.parse_args()
        # Check that the passed code is in the list that our get method returns
        if args['code'] not in self.get()[0]['codes']:
            return "{} is not a valid code".format(args['code']), 400

        # Check return code of our irsend command to catch failure.
        if shell.call(["irsend", "send_once", self.device_name, args['code']]) != 0:
            return "{} code send failed".format(args['code']), 500

        return {}, 200


class TvComBase(Resource):

    def get(self):
        return {'endpoints': ['/{}'.format(i.long_name) for i in serial_lookup]}, 200


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
        return {"codes": code_list}, 200

    def put(self):
        try:
            serial = Serial(self.port, timeout=self.timeout)

            self.reqparse.add_argument('code', required=True, help="variable required")
            args = self.reqparse.parse_args()
            # If 'code' var was not in request OR (if 'code' var is not in our list of valid codes AND is not a slider)
            # OR (is a slider and value is not a 1 to 3 digit integer), return error
            if 'code' not in args or (args['code'] not in self.instance.inverse_table and not self.instance.is_slider) \
                    or (self.instance.is_slider and not re.match("(^[0-9]{1,3}$)", args['code'])):
                return "{} is not a valid code".format(args['code']), 400

            raw_name = self.instance.name
            keycode = self.instance.get_keycode(args['code'])

            serial.write("{0} 00 {1}\r".format(raw_name, keycode).encode())
            response = serial.read(10).decode()

            if len(response) != 10 or response[5:7] == "NG":
                return "Endpoint did not respond correctly to '{}'".format(args['code']), 500

            if args['code'] == "status":
                return {'status': self.instance.get_desc(response[7:9])}, 200

            return {}, 200
        finally:
            serial.close()


# Define api endpoints for LED IR Remote objects
for r in ("strip", "bulb"):
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port='80', debug=True)
