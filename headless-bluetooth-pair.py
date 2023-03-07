#!/usr/bin/python

from gi.repository import GLib
import sys
import dbus
import dbus.service
import dbus.mainloop.glib
import os
from optparse import OptionParser

BUS_NAME = 'org.bluez'
AGENT_INTERFACE = 'org.bluez.Agent1'
AGENT_PATH = "/test/agent"
SERVICE_NAME = "org.bluez"
ADAPTER_INTERFACE = SERVICE_NAME + ".Adapter1"
DEVICE_INTERFACE = SERVICE_NAME + ".Device1"

def get_managed_objects():
        bus = dbus.SystemBus()
        manager = dbus.Interface(bus.get_object("org.bluez", "/"),
                                "org.freedesktop.DBus.ObjectManager")
        return manager.GetManagedObjects()

def find_adapter(pattern=None):
        return find_adapter_in_objects(get_managed_objects(), pattern)

def find_adapter_in_objects(objects, pattern=None):
        bus = dbus.SystemBus()
        for path, ifaces in objects.items():
                adapter = ifaces.get(ADAPTER_INTERFACE)
                if adapter is None:
                        continue
                if not pattern or pattern == adapter["Address"] or \
                                                        path.endswith(pattern):
                        obj = bus.get_object(SERVICE_NAME, path)
                        return dbus.Interface(obj, ADAPTER_INTERFACE)
        raise Exception("Bluetooth adapter not found")

def find_device(device_address, adapter_pattern=None):
        return find_device_in_objects(get_managed_objects(), device_address,
                                                                adapter_pattern)

def find_device_in_objects(objects, device_address, adapter_pattern=None):
        bus = dbus.SystemBus()
        path_prefix = ""
        if adapter_pattern:
                adapter = find_adapter_in_objects(objects, adapter_pattern)
                path_prefix = adapter.object_path
        for path, ifaces in objects.items():
                device = ifaces.get(DEVICE_INTERFACE)
                if device is None:
                        continue
                if (device["Address"] == device_address and
                                                path.startswith(path_prefix)):
                        obj = bus.get_object(SERVICE_NAME, path)
                        return dbus.Interface(obj, DEVICE_INTERFACE)

        raise Exception("Bluetooth device not found")


device_obj = None
device_path = None
mainloop = None
def set_trusted(path):
        props = dbus.Interface(bus.get_object("org.bluez", path),
                                        "org.freedesktop.DBus.Properties")
        props.Set("org.bluez.Device1", "Trusted", True)

def dev_connect(path):
        dev = dbus.Interface(bus.get_object("org.bluez", path),
                                                        "org.bluez.Device1")
        dev.Connect()

class Rejected(dbus.DBusException):
        _dbus_error_name = "org.bluez.Error.Rejected"

class Agent(dbus.service.Object):
        exit_on_release = True

        def __init__(self, bus, path, pin):
            super().__init__(bus, path)
            self.pin = pin

        def set_exit_on_release(self, exit_on_release):
                self.exit_on_release = exit_on_release

        @dbus.service.method(AGENT_INTERFACE,
                                        in_signature="", out_signature="")
        def Release(self):
                print("Release")
                if self.exit_on_release:
                        mainloop.quit()

        @dbus.service.method(AGENT_INTERFACE,
                                        in_signature="os", out_signature="")
        def AuthorizeService(self, device, uuid):
                return

        @dbus.service.method(AGENT_INTERFACE,
                                        in_signature="o", out_signature="s")
        def RequestPinCode(self, device):
                set_trusted(device)
                return self.pin

        @dbus.service.method(AGENT_INTERFACE,
                                        in_signature="o", out_signature="u")
        def RequestPasskey(self, device):
                set_trusted(device)
                return dbus.UInt32(self.pin)

        @dbus.service.method(AGENT_INTERFACE,
                                        in_signature="ouq", out_signature="")
        def DisplayPasskey(self, device, passkey, entered):
                print("DisplayPasskey (%s, %06u entered %u)" %
                                                (device, passkey, entered))

        @dbus.service.method(AGENT_INTERFACE,
                                        in_signature="os", out_signature="")
        def DisplayPinCode(self, device, pincode):
                print("DisplayPinCode (%s, %s)" % (device, pincode))

        @dbus.service.method(AGENT_INTERFACE,
                                        in_signature="ou", out_signature="")
        def RequestConfirmation(self, device, passkey):
                print("RequestConfirmation (%s, %06d)" % (device, passkey))
                confirm = ask("Confirm passkey (yes/no): ")
                if (confirm == "yes"):
                        set_trusted(device)
                        return
                raise Rejected("Passkey doesn't match")

        @dbus.service.method(AGENT_INTERFACE,
                                        in_signature="o", out_signature="")
        def RequestAuthorization(self, device):
                print("RequestAuthorization (%s)" % (device))
                auth = ask("Authorize? (yes/no): ")
                if (auth == "yes"):
                        return
                raise Rejected("Pairing rejected")

        @dbus.service.method(AGENT_INTERFACE,
                                        in_signature="", out_signature="")
        def Cancel(self):
                print("Cancel")

def pair_reply():
        print("Device paired")
        set_trusted(device_path)
        mainloop.quit()

def pair_error(error):
        err_name = error.get_dbus_name()
        if err_name == "org.freedesktop.DBus.Error.NoReply" and device_obj:
                print("Timed out. Cancelling pairing")
                device_obj.CancelPairing()
        else:
                print("Creating device failed: %s" % (error))
        mainloop.quit()

if __name__ == '__main__':
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)

        bus = dbus.SystemBus()

        capability = "NoInputNoOutput"

        parser = OptionParser()
        parser.add_option("-i", "--adapter", action="store",
                                        type="string",
                                        dest="adapter_pattern",
                                        default=None)
        parser.add_option("-b", "--btaddr", action="store",
                                        type="string",
                                        dest="bluetooth_address",
                                        default=os.environ.get('BT_ADDRESS') if os.environ.get('BT_ADDRESS') else None)
        parser.add_option("-p", "--pin", action="store",
                                        type="string",
                                        dest="pin",
                                        default=os.environ.get('BT_PIN') if os.environ.get('BT_PIN') else '1234')
        parser.add_option("-c", "--capability", action="store",
                                        type="string", dest="capability")
        parser.add_option("-t", "--timeout", action="store",
                                        type="int", dest="timeout",
                                        default=60000)
        (options, args) = parser.parse_args()
        if options.capability:
                capability  = options.capability

        if not options.bluetooth_address:
            print("No bluetooth address provided")
            exit(parser.print_usage())


        path = "/test/agent"
        agent = Agent(bus, path, options.pin)

        mainloop = GLib.MainLoop()

        obj = bus.get_object(BUS_NAME, "/org/bluez");
        manager = dbus.Interface(obj, "org.bluez.AgentManager1")
        manager.RegisterAgent(path, capability)

        device = find_device(options.bluetooth_address,
                                        options.adapter_pattern)
        device_path = device.object_path
        agent.set_exit_on_release(False)
        device.Pair(reply_handler=pair_reply, error_handler=pair_error,
                                                        timeout=60000)
        device_obj = device

        mainloop.run()

