# Copyright (c) 2022 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

from UM.OutputDevice.OutputDevicePlugin import OutputDevicePlugin
from .OctoPrintOutputDevice import OctoPrintOutputDevice

from UM.Signal import Signal, signalemitter
from UM.Application import Application
from UM.Logger import Logger
from UM.Util import parseBool
from UM.Settings.ContainerStack import ContainerStack

try:
    from cura.ApplicationMetadata import CuraSDKVersion
except ImportError: # Cura <= 3.6
    CuraSDKVersion = "6.0.0"
if CuraSDKVersion >= "8.0.0":
    from PyQt6.QtCore import QTimer
else:
    from PyQt5.QtCore import QTimer

import time
import json
import re
import base64
import os.path
import ipaddress

from typing import Any, Dict, List, Union, Optional, TYPE_CHECKING

try:
    ìmport_exceptions = (SyntaxError, FileNotFoundError, ModuleNotFoundError, ImportError)
except NameError:
    # Python 3.5 does not know the ModuleNotFoundError
    ìmport_exceptions = (SyntaxError, FileNotFoundError, ImportError)

if TYPE_CHECKING:
    # for MYPY, fall back to the system-installed version
    from zeroconf import (
        Zeroconf,
        ServiceBrowser,
        ServiceStateChange,
        ServiceInfo,
        DNSAddress,
    )
else:
    try:
        # import the included version of python-zeroconf
        # expand search path so local copies of zeroconf, ifaddr and async-timeout can be imported
        import sys
        import importlib.util

        original_path = list(sys.path)
        original_zeroconf_module = None

        if "zeroconf" in sys.modules:
            Logger.log(
                "d",
                "The zeroconf module is already imported; flush it to use a newer version",
            )
            original_zeroconf_module = sys.modules.pop("zeroconf")

        plugin_path = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, os.path.join(plugin_path, "ifaddr"))
        sys.path.insert(0, os.path.join(plugin_path, "async-timeout"))

        zeroconf_spec = importlib.util.spec_from_file_location(
            "zeroconf",
            os.path.join(plugin_path, "python-zeroconf", "src", "zeroconf", "__init__.py"),
        )
        zeroconf_module = importlib.util.module_from_spec(zeroconf_spec)
        sys.modules["zeroconf"] = zeroconf_module

        zeroconf_spec.loader.exec_module(
            zeroconf_module
        )  # must be called after adding zeroconf to sys.modules

        from zeroconf import (
            Zeroconf,
            ServiceBrowser,
            ServiceStateChange,
            ServiceInfo,
            DNSAddress,
            __version__ as zeroconf_version,
        )

        # restore original path
        sys.path = original_path

        Logger.log("d", "Using included Zeroconf module version %s" % zeroconf_version)
    except ìmport_exceptions as exception:
        # fall back to the system-installed version, or what comes with Cura
        Logger.logException("e", "Failed to load included version of Zeroconf module")

        # restore original path
        sys.path = original_path
        if original_zeroconf_module:
            sys.modules["zeroconf"] = original_zeroconf_module

        try:
            from zeroconf import (
                Zeroconf,
                ServiceBrowser,
                ServiceStateChange,
                ServiceInfo,
                DNSAddress,
                __version__ as zeroconf_version,
            )

            Logger.log(
                "w", "Falling back to default Zeroconf module version %s" % zeroconf_version
            )
        except ImportError:
            Zeroconf = None
            ServiceBrowser = None
            ServiceStateChange = None
            ServiceInfo = None
            DNSAddress = None

            Logger.log(
                "w", "Zeroconf could not be loaded; Auto-discovery is not available"
            )


if TYPE_CHECKING:
    from cura.PrinterOutput.PrinterOutputModel import PrinterOutputModel

##  This plugin handles the connection detection & creation of output device objects for OctoPrint-connected printers.
#   Zero-Conf is used to detect printers, which are saved in a dict.
#   If we discover an instance that has the same key as the active machine instance a connection is made.
@signalemitter
class OctoPrintOutputDevicePlugin(OutputDevicePlugin):
    def __init__(self) -> None:
        super().__init__()
        self._zeroconf = None  # type: Optional[Zeroconf]
        self._browser = None  # type: Optional[ServiceBrowser]
        self._instances = {}  # type: Dict[str, OctoPrintOutputDevice]

        # Because the model needs to be created in the same thread as the QMLEngine, we use a signal.
        self.addInstanceSignal.connect(self.addInstance)
        self.removeInstanceSignal.connect(self.removeInstance)
        Application.getInstance().globalContainerStackChanged.connect(
            self.reCheckConnections
        )

        # Load custom instances from preferences
        self._preferences = Application.getInstance().getPreferences()
        self._preferences.addPreference("octoprint/manual_instances", "{}")

        self._preferences.addPreference("octoprint/use_zeroconf", True)

        try:
            self._manual_instances = json.loads(
                self._preferences.getValue("octoprint/manual_instances")
            )
        except ValueError:
            self._manual_instances = {}  # type: Dict[str, Any]
        if not isinstance(self._manual_instances, dict):
            self._manual_instances = {}  # type: Dict[str, Any]

        self._name_regex = re.compile(r"OctoPrint instance (\".*\"\.|on )(.*)\.")

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
        if self._zeroconf:
            self._zeroconf.close()
            self._zeroconf = None  # type: Optional[Zeroconf]

        if self._browser:
            self._browser.cancel()
            self._browser = None  # type: Optional[ServiceBrowser]
            self._printers = []  # type: List[PrinterOutputModel]

        instance_keys = list(self._instances.keys())
        for key in instance_keys:
            self.removeInstance(key)

        # Add manual instances from preference
        for name, properties in self._manual_instances.items():
            additional_properties = {
                b"path": properties["path"].encode("utf-8"),
                b"useHttps": b"true" if properties.get("useHttps", False) else b"false",
                b"userName": properties.get("userName", "").encode("utf-8"),
                b"password": properties.get("password", "").encode("utf-8"),
                b"manual": b"true",
            }  # These additional properties use bytearrays to mimick the output of zeroconf
            self.addInstance(
                name, properties["address"], properties["port"], additional_properties
            )

        self.instanceListChanged.emit()

        # Don't start zeroconf discovery if it is disabled
        if not self._preferences.getValue("octoprint/use_zeroconf"):
            self._keep_alive_timer.stop()
            return

        try:
            self._zeroconf = Zeroconf()
        except Exception:
            self._zeroconf = None  # type: Optional[Zeroconf]
            self._keep_alive_timer.stop()
            Logger.logException(
                "e", "Failed to create Zeroconf instance. Auto-discovery will not work."
            )

        if self._zeroconf:
            self._browser = ServiceBrowser(
                self._zeroconf, "_octoprint._tcp.local.", [self._onServiceChanged]
            )
            if self._browser and self._browser.is_alive():
                self._keep_alive_timer.start()
            else:
                Logger.log(
                    "w",
                    "Failed to create Zeroconf browser. Auto-discovery will not work.",
                )
                self._keep_alive_timer.stop()

    def _keepDiscoveryAlive(self) -> None:
        if not self._browser or not self._browser.is_alive():
            if self._consecutive_zeroconf_restarts < 5:
                Logger.log(
                    "w",
                    "Zeroconf discovery has died, restarting discovery of OctoPrint instances.",
                )
                self._consecutive_zeroconf_restarts += 1
                self.startDiscovery()
            else:
                if self._zeroconf:
                    self._zeroconf.close()
                    self._zeroconf = None  # type: Optional[Zeroconf]
                Logger.log(
                    "e",
                    "Giving up restarting Zeroconf browser after 5 consecutive attempts. Auto-discovery will not work.",
                )
        else:
            # ZeroConf has been alive and well for the past 2 seconds
            self._consecutive_zeroconf_restarts = 0
            self._keep_alive_timer.start()

    def addManualInstance(
        self,
        name: str,
        address: str,
        port: int,
        path: str,
        useHttps: bool = False,
        userName: str = "",
        password: str = "",
    ) -> None:
        self._manual_instances[name] = {
            "address": address,
            "port": port,
            "path": path,
            "useHttps": useHttps,
            "userName": userName,
            "password": password,
        }
        self._preferences.setValue(
            "octoprint/manual_instances", json.dumps(self._manual_instances)
        )

        properties = {
            b"path": path.encode("utf-8"),
            b"useHttps": b"true" if useHttps else b"false",
            b"userName": userName.encode("utf-8"),
            b"password": password.encode("utf-8"),
            b"manual": b"true",
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
            self._preferences.setValue(
                "octoprint/manual_instances", json.dumps(self._manual_instances)
            )

    ##  Stop looking for devices on network.
    def stop(self) -> None:
        self._keep_alive_timer.stop()

        if self._browser:
            self._browser.cancel()
        self._browser = None  # type: Optional[ServiceBrowser]

        if self._zeroconf:
            self._zeroconf.close()

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
                self._configureAndConnectInstance(
                    self._instances[key], global_container_stack
                )
            else:
                if self._instances[key].isConnected():
                    self._instances[key].close()

    ##  Because the model needs to be created in the same thread as the QMLEngine, we use a signal.
    def addInstance(
        self, name: str, address: str, port: int, properties: Dict[bytes, bytes]
    ) -> None:
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        instance = OctoPrintOutputDevice(name, address, port, properties)
        self._instances[instance.getId()] = instance
        if instance.getId() == global_container_stack.getMetaDataEntry("octoprint_id"):
            self._configureAndConnectInstance(instance, global_container_stack)

    def _configureAndConnectInstance(
        self, instance: OctoPrintOutputDevice, global_container_stack: ContainerStack
    ) -> None:
        api_key = global_container_stack.getMetaDataEntry("octoprint_api_key", "")

        instance.setApiKey(self._deobfuscateString(api_key))
        instance.setShowCamera(
            parseBool(
                global_container_stack.getMetaDataEntry("octoprint_show_camera", "true")
            )
        )
        instance.setConfirmUploadOptions(
            parseBool(
                global_container_stack.getMetaDataEntry(
                    "octoprint_confirm_upload_options", "false"
                )
            )
        )
        instance.connectionStateChanged.connect(self._onInstanceConnectionStateChanged)
        instance.connect()

    def removeInstance(self, name: str) -> None:
        instance = self._instances.pop(name, None)
        if instance:
            if instance.isConnected():
                instance.connectionStateChanged.disconnect(
                    self._onInstanceConnectionStateChanged
                )
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
    def _onServiceChanged(
        self,
        zeroconf: Zeroconf,
        service_type: str,
        name: str,
        state_change: ServiceStateChange,
    ) -> None:
        if state_change == ServiceStateChange.Added:
            result = self._name_regex.match(name)
            if result:
                if result.group(1) == "on ":
                    instance_name = result.group(2)
                else:
                    instance_name = result.group(1) + result.group(2)
            else:
                instance_name = name

            Logger.log("d", "Bonjour service added: %s" % instance_name)

            address = ""
            try:
                info = zeroconf.get_service_info(service_type, name)
                for scoped_address in info.parsed_scoped_addresses():
                    address = self._validateIP(scoped_address)
                    if address:
                        break

            except AttributeError:
                info = ServiceInfo(service_type, name)
                # First try getting info from zeroconf cache
                for record in zeroconf.cache.entries_with_name(name.lower()):
                    info.update_record(zeroconf, time.time(), record)

                for record in zeroconf.cache.entries_with_name(info.server):
                    info.update_record(zeroconf, time.time(), record)
                    if not isinstance(record, DNSAddress):
                        continue
                    address = self._validateIP(record.address)
                    if address:
                        break

            # Request more data if info is not complete
            if not address or not info.port:
                Logger.log("d", "Trying to get address of %s", instance_name)
                requested_info = zeroconf.get_service_info(service_type, name)

                if not requested_info:
                    Logger.log(
                        "w", "Could not get information about %s" % instance_name
                    )
                    return

                info = requested_info

            if address and info.port:
                self.addInstanceSignal.emit(
                    instance_name, address, info.port, info.properties
                )
            else:
                Logger.log(
                    "d",
                    "Discovered instance named %s but received no address",
                    instance_name,
                )

        elif state_change == ServiceStateChange.Removed:
            self.removeInstanceSignal.emit(str(name))

    def _validateIP(self, address: str) -> str:
        ip = None  # type: Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address]]
        try:
            ip = ipaddress.IPv4Address(address)  # IPv4
        except ipaddress.AddressValueError:
            ip = ipaddress.IPv6Address(address)  # IPv6
        except:
            return ""

        if ip and not ip.is_link_local:  # don't accept 169.254.x.x address
            return str(ip) if ip.version == 4 else "[%s]" % str(ip)
        else:
            return ""
