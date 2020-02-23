# Copyright (c) 2020 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

from UM.OutputDevice.OutputDevicePlugin import OutputDevicePlugin
from .OctoPrintOutputDevice import OctoPrintOutputDevice

from UM.Signal import Signal, signalemitter
from UM.Application import Application
from UM.Logger import Logger
from UM.Util import parseBool

from PyQt5.QtCore import QTimer

import time
import json
import re
import base64
import os.path
import ipaddress

from typing import Any, Dict, List, Union, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    # for MYPY, fall back to the system-installed version
    from zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange, ServiceInfo, DNSAddress
else:
    try:
        # import the included version of python-zeroconf
        import sys
        import importlib.util

        # expand path so local copy of ifaddr can be imported by zeroconf
        sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "ifaddr"))

        zeroconf_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "python-zeroconf", "zeroconf", "__init__.py"
        )
        spec = importlib.util.spec_from_file_location("zeroconf", zeroconf_path)
        zeroconf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(zeroconf)

        del sys.path[-1] # restore original path

        Zeroconf = zeroconf.Zeroconf
        ServiceBrowser = zeroconf.ServiceBrowser
        ServiceStateChange = zeroconf.ServiceStateChange
        ServiceInfo = zeroconf.ServiceInfo
        DNSAddress = zeroconf.DNSAddress
        Logger.log("w", "Supplied version of Zeroconf module imported")
    except (FileNotFoundError, ImportError):
        # fall back to the system-installed version, or what comes with Cura
        Logger.log("w", "Falling back to default zeroconf module")
        from zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange, ServiceInfo

if TYPE_CHECKING:
    from cura.PrinterOutput.PrinterOutputModel import PrinterOutputModel

##  This plugin handles the connection detection & creation of output device objects for OctoPrint-connected printers.
#   Zero-Conf is used to detect printers, which are saved in a dict.
#   If we discover an instance that has the same key as the active machine instance a connection is made.
@signalemitter
class OctoPrintOutputDevicePlugin(OutputDevicePlugin):
    def __init__(self) -> None:
        super().__init__()
        self._zero_conf = None # type: Optional[Zeroconf]
        self._browser = None # type: Optional[ServiceBrowser]
        self._instances = {} # type: Dict[str, OctoPrintOutputDevice]

        # Because the model needs to be created in the same thread as the QMLEngine, we use a signal.
        self.addInstanceSignal.connect(self.addInstance)
        self.removeInstanceSignal.connect(self.removeInstance)
        Application.getInstance().globalContainerStackChanged.connect(self.reCheckConnections)

        # Load custom instances from preferences
        self._preferences = Application.getInstance().getPreferences()
        self._preferences.addPreference("octoprint/manual_instances", "{}")

        self._preferences.addPreference("octoprint/use_zeroconf", True)

        try:
            self._manual_instances = json.loads(self._preferences.getValue("octoprint/manual_instances"))
        except ValueError:
            self._manual_instances = {} # type: Dict[str, Any]
        if not isinstance(self._manual_instances, dict):
            self._manual_instances = {} # type: Dict[str, Any]

        self._name_regex = re.compile("OctoPrint instance (\".*\"\.|on )(.*)\.")

        self._keep_alive_timer = QTimer()
        self._keep_alive_timer.setInterval(2000)
        self._keep_alive_timer.setSingleShot(True)
        self._keep_alive_timer.timeout.connect(self._keepDiscoveryAlive)
        self._consecutive_zeroconf_restarts = 0


    addInstanceSignal = Signal()
    removeInstanceSignal = Signal()
    instanceListChanged = Signal()

    ##  Start looking for devices on network.
    def start(self) -> None:
        self.startDiscovery()

    def startDiscovery(self) -> None:
        # Clean up previous discovery components and results
        if self._zero_conf:
            self._zero_conf.close()
            self._zero_conf = None # type: Optional[Zeroconf]

        if self._browser:
            self._browser.cancel()
            self._browser = None # type: Optional[ServiceBrowser]
            self._printers = [] # type: List[PrinterOutputModel]

        instance_keys = list(self._instances.keys())
        for key in instance_keys:
            self.removeInstance(key)

        # Add manual instances from preference
        for name, properties in self._manual_instances.items():
            additional_properties = {
                b"path": properties["path"].encode("utf-8"),
                b"useHttps": b"true" if properties.get("useHttps", False) else b"false",
                b'userName': properties.get("userName", "").encode("utf-8"),
                b'password': properties.get("password", "").encode("utf-8"),
                b"manual": b"true"
            } # These additional properties use bytearrays to mimick the output of zeroconf
            self.addInstance(name, properties["address"], properties["port"], additional_properties)

        self.instanceListChanged.emit()

        # Don't start zeroconf discovery if it is disabled
        if not self._preferences.getValue("octoprint/use_zeroconf"):
            self._keep_alive_timer.stop()
            return

        try:
            self._zero_conf = Zeroconf()
        except Exception:
            self._zero_conf = None # type: Optional[Zeroconf]
            self._keep_alive_timer.stop()
            Logger.logException("e", "Failed to create Zeroconf instance. Auto-discovery will not work.")

        if self._zero_conf:
            self._browser = ServiceBrowser(self._zero_conf, u'_octoprint._tcp.local.', [self._onServiceChanged])
            if self._browser and self._browser.is_alive():
                self._keep_alive_timer.start()
            else:
                Logger.log("w", "Failed to create Zeroconf browser. Auto-discovery will not work.")
                self._keep_alive_timer.stop()

    def _keepDiscoveryAlive(self) -> None:
        if not self._browser or not self._browser.is_alive():
            if self._consecutive_zeroconf_restarts < 5:
                Logger.log("w", "Zeroconf discovery has died, restarting discovery of OctoPrint instances.")
                self._consecutive_zeroconf_restarts += 1
                self.startDiscovery()
            else:
                if self._zero_conf:
                    self._zero_conf.close()
                    self._zero_conf = None # type: Optional[Zeroconf]
                Logger.log("e", "Giving up restarting Zeroconf browser after 5 consecutive attempts. Auto-discovery will not work.")
        else:
            # ZeroConf has been alive and well for the past 2 seconds
            self._consecutive_zeroconf_restarts = 0
            self._keep_alive_timer.start()

    def addManualInstance(self, name: str, address: str, port: int, path: str, useHttps: bool = False, userName: str = "", password: str = "") -> None:
        self._manual_instances[name] = {
            "address": address,
            "port": port,
            "path": path,
            "useHttps": useHttps,
            "userName": userName,
            "password": password
        }
        self._preferences.setValue("octoprint/manual_instances", json.dumps(self._manual_instances))

        properties = {
            b"path": path.encode("utf-8"),
            b"useHttps": b"true" if useHttps else b"false",
            b'userName': userName.encode("utf-8"),
            b'password': password.encode("utf-8"),
            b"manual": b"true"
        }

        if name in self._instances:
            self.removeInstance(name)

        self.addInstance(name, address, port, properties)
        self.instanceListChanged.emit()

    def removeManualInstance(self, name: str) -> None:
        if name in self._instances:
            self.removeInstance(name)
            self.instanceListChanged.emit()

        if name in self._manual_instances:
            self._manual_instances.pop(name, None)
            self._preferences.setValue("octoprint/manual_instances", json.dumps(self._manual_instances))

    ##  Stop looking for devices on network.
    def stop(self) -> None:
        self._keep_alive_timer.stop()

        if self._browser:
            self._browser.cancel()
        self._browser = None # type: Optional[ServiceBrowser]

        if self._zero_conf:
            self._zero_conf.close()

    def getInstances(self) -> Dict[str, Any]:
        return self._instances

    def getInstanceById(self, instance_id: str) -> Optional[OctoPrintOutputDevice]:
        instance = self._instances.get(instance_id, None)
        if instance:
            return instance
        Logger.log("w", "No instance found with id %s", instance_id)
        return None

    def reCheckConnections(self) -> None:
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        for key in self._instances:
            if key == global_container_stack.getMetaDataEntry("octoprint_id"):
                api_key = global_container_stack.getMetaDataEntry("octoprint_api_key", "")
                self._instances[key].setApiKey(self._deobfuscateString(api_key))
                self._instances[key].setShowCamera(parseBool(
                    global_container_stack.getMetaDataEntry("octoprint_show_camera", "true"))
                )
                self._instances[key].connectionStateChanged.connect(self._onInstanceConnectionStateChanged)
                self._instances[key].connect()
            else:
                if self._instances[key].isConnected():
                    self._instances[key].close()

    ##  Because the model needs to be created in the same thread as the QMLEngine, we use a signal.
    def addInstance(self, name: str, address: str, port: int, properties: Dict[bytes, bytes]) -> None:
        instance = OctoPrintOutputDevice(name, address, port, properties)
        self._instances[instance.getId()] = instance
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if global_container_stack and instance.getId() == global_container_stack.getMetaDataEntry("octoprint_id"):
            api_key = global_container_stack.getMetaDataEntry("octoprint_api_key", "")
            instance.setApiKey(self._deobfuscateString(api_key))
            instance.setShowCamera(parseBool(global_container_stack.getMetaDataEntry("octoprint_show_camera", "true")))
            instance.connectionStateChanged.connect(self._onInstanceConnectionStateChanged)
            instance.connect()

    def removeInstance(self, name: str) -> None:
        instance = self._instances.pop(name, None)
        if instance:
            if instance.isConnected():
                instance.connectionStateChanged.disconnect(self._onInstanceConnectionStateChanged)
                instance.disconnect()

    ##  Utility handler to base64-decode a string (eg an obfuscated API key), if it has been encoded before
    def _deobfuscateString(self, source: str) -> str:
        try:
            return base64.b64decode(source.encode("ascii")).decode("ascii")
        except UnicodeDecodeError:
            return source

    ##  Handler for when the connection state of one of the detected instances changes
    def _onInstanceConnectionStateChanged(self, key: str) -> None:
        if key not in self._instances:
            return

        if self._instances[key].isConnected():
            self.getOutputDeviceManager().addOutputDevice(self._instances[key])
        else:
            self.getOutputDeviceManager().removeOutputDevice(key)

    ##  Handler for zeroConf detection
    def _onServiceChanged(self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change == ServiceStateChange.Added:
            key = name
            result = self._name_regex.match(name)
            if result:
                if result.group(1) == "on ":
                    name = result.group(2)
                else:
                    name = result.group(1) + result.group(2)

            Logger.log("d", "Bonjour service added: %s" % name)

            # First try getting info from zeroconf cache
            info = ServiceInfo(service_type, key)
            for record in zeroconf.cache.entries_with_name(key.lower()):
                info.update_record(zeroconf, time.time(), record)

            address = ""
            for record in zeroconf.cache.entries_with_name(info.server):
                info.update_record(zeroconf, time.time(), record)
                if not isinstance(record, DNSAddress):
                    return
                ip = None  # type: Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]
                try:
                    ip = ipaddress.IPv4Address(record.address) # IPv4
                except ipaddress.AddressValueError:
                    ip = ipaddress.IPv6Address(record.address) # IPv6
                except:
                    continue

                if ip and not ip.is_link_local: # don't accept 169.254.x.x address
                    address = str(ip) if ip.version == 4 else "[%s]" % str(ip)
                    break

            # Request more data if info is not complete
            if not address or not info.port:
                Logger.log("d", "Trying to get address of %s", name)
                requested_info = zeroconf.get_service_info(service_type, key)

                if not requested_info:
                    Logger.log("w", "Could not get information about %s" % name)
                    return

                info = requested_info

            if address and info.port:
                self.addInstanceSignal.emit(name, address, info.port, info.properties)
            else:
                Logger.log("d", "Discovered instance named %s but received no address", name)

        elif state_change == ServiceStateChange.Removed:
            self.removeInstanceSignal.emit(str(name))
