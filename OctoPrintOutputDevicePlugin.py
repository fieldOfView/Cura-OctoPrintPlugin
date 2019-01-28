# Copyright (c) 2019 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

from UM.OutputDevice.OutputDevicePlugin import OutputDevicePlugin
from . import OctoPrintOutputDevice

from .zeroconf import Zeroconf, ServiceBrowser, ServiceStateChange, ServiceInfo
from UM.Signal import Signal, signalemitter
from UM.Application import Application
from UM.Logger import Logger
from UM.Util import parseBool

from PyQt5.QtCore import QTimer

import time
import json
import re
import base64

from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
if TYPE_CHECKING:
    from cura.PrinterOutput.PrinterOutputModel import PrinterOutputModel

##      This plugin handles the connection detection & creation of output device objects for OctoPrint-connected printers.
#       Zero-Conf is used to detect printers, which are saved in a dict.
#       If we discover an instance that has the same key as the active machine instance a connection is made.
@signalemitter
class OctoPrintOutputDevicePlugin(OutputDevicePlugin):
    def __init__(self) -> None:
        super().__init__()
        self._zero_conf = None # type: Optional[Zeroconf]
        self._browser = None # type: Optional[ServiceBrowser]
        self._instances = {} # type: Dict[str, OctoPrintOutputDevice.OctoPrintOutputDevice]

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


    addInstanceSignal = Signal()
    removeInstanceSignal = Signal()
    instanceListChanged = Signal()

    ##  Start looking for devices on network.
    def start(self) -> None:
        self.startDiscovery()

    def startDiscovery(self) -> None:
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
            return

        try:
            self._zero_conf = Zeroconf()
        except Exception:
            self._zero_conf = None
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
            Logger.log("w", "Zeroconf discovery has died, restarting discovery of OctoPrint instances.")
            self.startDiscovery()
        else:
            self._keep_alive_timer.start()

    def addManualInstance(self, name: str, address: str, port: int, path: str, useHttps: bool = False, userName: str = "", password: str = "") -> None:
        self._manual_instances[name] = {"address": address, "port": port, "path": path, "useHttps": useHttps, "userName": userName, "password": password}
        self._preferences.setValue("octoprint/manual_instances", json.dumps(self._manual_instances))

        properties = { b"path": path.encode("utf-8"), b"useHttps": b"true" if useHttps else b"false", b'userName': userName.encode("utf-8"), b'password': password.encode("utf-8"), b"manual": b"true" }

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

    def reCheckConnections(self) -> None:
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        for key in self._instances:
            if key == global_container_stack.getMetaDataEntry("octoprint_id"):
                api_key = global_container_stack.getMetaDataEntry("octoprint_api_key", "")
                self._instances[key].setApiKey(self._deobfuscateString(api_key))
                self._instances[key].setShowCamera(parseBool(global_container_stack.getMetaDataEntry("octoprint_show_camera", "false")))
                self._instances[key].connectionStateChanged.connect(self._onInstanceConnectionStateChanged)
                self._instances[key].connect()
            else:
                if self._instances[key].isConnected():
                    self._instances[key].close()

    ##  Because the model needs to be created in the same thread as the QMLEngine, we use a signal.
    def addInstance(self, name: str, address: str, port: int, properties: Dict[bytes, bytes]) -> None:
        instance = OctoPrintOutputDevice.OctoPrintOutputDevice(name, address, port, properties)
        self._instances[instance.getId()] = instance
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if global_container_stack and instance.getId() == global_container_stack.getMetaDataEntry("octoprint_id"):
            api_key = global_container_stack.getMetaDataEntry("octoprint_api_key", "")
            instance.setApiKey(self._deobfuscateString(api_key))
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
    def _onServiceChanged(self, zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange):
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

            for record in zeroconf.cache.entries_with_name(info.server):
                info.update_record(zeroconf, time.time(), record)
                if info.address and info.address[:2] != b'\xa9\xfe': # don't accept 169.254.x.x address
                    break

            # Request more data if info is not complete
            if not info.address or not info.port:
                Logger.log("d", "Trying to get address of %s", name)
                info = zeroconf.get_service_info(service_type, key)

                if not info:
                    Logger.log("w", "Could not get information about %s" % name)
                    return

            if info.address and info.port:
                address = '.'.join(map(lambda n: str(n), info.address))
                self.addInstanceSignal.emit(name, address, info.port, info.properties)
            else:
                Logger.log("d", "Discovered instance named %s but received no address", name)

        elif state_change == ServiceStateChange.Removed:
            self.removeInstanceSignal.emit(str(name))
