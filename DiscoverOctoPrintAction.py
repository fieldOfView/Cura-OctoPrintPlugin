# Copyright (c) 2022 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

from UM.i18n import i18nCatalog
from UM.Logger import Logger
from UM.Version import Version
from UM.Settings.DefinitionContainer import DefinitionContainer
from UM.OutputDevice.OutputDevicePlugin import OutputDevicePlugin
from UM.Settings.ContainerRegistry import ContainerRegistry

from cura.CuraApplication import CuraApplication
from cura.MachineAction import MachineAction
from cura.Settings.CuraStackBuilder import CuraStackBuilder

try:
    from cura.ApplicationMetadata import CuraSDKVersion
except ImportError: # Cura <= 3.6
    CuraSDKVersion = "6.0.0"
USE_QT5 = False
if CuraSDKVersion >= "8.0.0":
    from PyQt6.QtCore import pyqtSignal, pyqtProperty, pyqtSlot, QUrl, QObject, QTimer
    from PyQt6.QtGui import QDesktopServices
    from PyQt6.QtNetwork import (
        QNetworkRequest,
        QNetworkAccessManager,
        QNetworkReply,
        QSslConfiguration,
        QSslSocket,
    )

    QNetworkAccessManagerOperations = QNetworkAccessManager.Operation
    QNetworkRequestKnownHeaders = QNetworkRequest.KnownHeaders
    QNetworkRequestAttributes = QNetworkRequest.Attribute
    QSslSocketPeerVerifyModes = QSslSocket.PeerVerifyMode

else:
    from PyQt5.QtCore import pyqtSignal, pyqtProperty, pyqtSlot, QUrl, QObject, QTimer
    from PyQt5.QtGui import QDesktopServices
    from PyQt5.QtNetwork import (
        QNetworkRequest,
        QNetworkAccessManager,
        QNetworkReply,
        QSslConfiguration,
        QSslSocket,
    )

    QNetworkAccessManagerOperations = QNetworkAccessManager
    QNetworkRequestKnownHeaders = QNetworkRequest
    QNetworkRequestAttributes = QNetworkRequest
    QSslSocketPeerVerifyModes = QSslSocket

    USE_QT5 = True

from .NetworkReplyTimeout import NetworkReplyTimeout
from .PowerPlugins import PowerPlugins
from .OctoPrintOutputDevicePlugin import OctoPrintOutputDevicePlugin
from .OctoPrintOutputDevice import OctoPrintOutputDevice

import os.path
import json
import base64

from typing import cast, Any, Tuple, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from UM.Settings.ContainerInterface import ContainerInterface

catalog = i18nCatalog("octoprint")


class DiscoverOctoPrintAction(MachineAction):
    def __init__(self, parent: QObject = None) -> None:
        super().__init__(
            "DiscoverOctoPrintAction", catalog.i18nc("@action", "Connect OctoPrint")
        )

        self._application = CuraApplication.getInstance()
        self._network_plugin = None  # type: Optional[OctoPrintOutputDevicePlugin]

        qml_folder = "qml" if not USE_QT5 else "qml_qt5"

        self._qml_url = os.path.join(qml_folder, "DiscoverOctoPrintAction.qml")

        #  QNetwork manager needs to be created in advance. If we don't it can happen that it doesn't correctly
        #  hook itself into the event loop, which results in events never being fired / done.
        self._network_manager = QNetworkAccessManager()
        self._network_manager.finished.connect(self._onRequestFinished)

        self._settings_reply = None  # type: Optional[QNetworkReply]
        self._settings_reply_timeout = None  # type: Optional[NetworkReplyTimeout]

        self._instance_supports_appkeys = False
        self._appkey_reply = None  # type: Optional[QNetworkReply]
        self._appkey_request = None  # type: Optional[QNetworkRequest]
        self._appkey_instance_id = ""

        self._appkey_poll_timer = QTimer()
        self._appkey_poll_timer.setInterval(500)
        self._appkey_poll_timer.setSingleShot(True)
        self._appkey_poll_timer.timeout.connect(self._pollApiKey)

        # Try to get version information from plugin.json
        plugin_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "plugin.json"
        )
        try:
            with open(plugin_file_path) as plugin_file:
                plugin_info = json.load(plugin_file)
                self._plugin_version = plugin_info["version"]
        except:
            # The actual version info is not critical to have so we can continue
            self._plugin_version = "0.0"
            Logger.logException("w", "Could not get version information for the plugin")

        self._user_agent = (
            "%s/%s %s/%s"
            % (
                self._application.getApplicationName(),
                self._application.getVersion(),
                "OctoPrintPlugin",
                self._plugin_version,
            )
        ).encode()

        self._settings_instance = None  # type: Optional[OctoPrintOutputDevice]

        self._instance_responded = False
        self._instance_in_error = False
        self._instance_api_key_accepted = False
        self._instance_supports_sd = False
        self._instance_supports_camera = False
        self._instance_installed_plugins = []  # type: List[str]

        self._power_plugins_manager = PowerPlugins()

        # Load keys cache from preferences
        self._preferences = self._application.getPreferences()
        self._preferences.addPreference("octoprint/keys_cache", "")

        try:
            self._keys_cache = json.loads(
                self._deobfuscateString(
                    self._preferences.getValue("octoprint/keys_cache")
                )
            )
        except ValueError:
            self._keys_cache = {}  # type: Dict[str, Any]
        if not isinstance(self._keys_cache, dict):
            self._keys_cache = {}  # type: Dict[str, Any]

        self._additional_components = None  # type:Optional[QObject]

        ContainerRegistry.getInstance().containerAdded.connect(self._onContainerAdded)
        self._application.engineCreatedSignal.connect(
            self._createAdditionalComponentsView
        )

    @pyqtProperty(str, constant=True)
    def pluginVersion(self) -> str:
        return self._plugin_version

    @pyqtSlot()
    def startDiscovery(self) -> None:
        if not self._plugin_id:
            return
        if not self._network_plugin:
            self._network_plugin = cast(
                OctoPrintOutputDevicePlugin,
                self._application.getOutputDeviceManager().getOutputDevicePlugin(
                    self._plugin_id
                ),
            )
            if not self._network_plugin:
                return
            self._network_plugin.addInstanceSignal.connect(self._onInstanceDiscovery)
            self._network_plugin.removeInstanceSignal.connect(self._onInstanceDiscovery)
            self._network_plugin.instanceListChanged.connect(self._onInstanceDiscovery)
            self.instancesChanged.emit()
        else:
            # Restart bonjour discovery
            self._network_plugin.startDiscovery()

    def _onInstanceDiscovery(self, *args) -> None:
        self.instancesChanged.emit()

    @pyqtSlot(str)
    def removeManualInstance(self, name: str) -> None:
        if not self._network_plugin:
            return

        self._network_plugin.removeManualInstance(name)

    @pyqtSlot(str, str, int, str, bool, str, str)
    def setManualInstance(
        self,
        name: str,
        address: str,
        port: int,
        path: str,
        useHttps: bool,
        userName: str = "",
        password: str = "",
    ) -> None:
        if not self._network_plugin:
            return

        # This manual printer could replace a current manual printer
        self._network_plugin.removeManualInstance(name)

        self._network_plugin.addManualInstance(
            name, address, port, path, useHttps, userName, password
        )

    def _onContainerAdded(self, container: "ContainerInterface") -> None:
        # Add this action as a supported action to all machine definitions
        if (
            isinstance(container, DefinitionContainer)
            and container.getMetaDataEntry("type") == "machine"
            and container.getMetaDataEntry("supports_usb_connection")
        ):

            self._application.getMachineActionManager().addSupportedAction(
                container.getId(), self.getKey()
            )

    instancesChanged = pyqtSignal()
    appKeysSupportedChanged = pyqtSignal()
    appKeyReceived = pyqtSignal()
    instanceIdChanged = pyqtSignal()

    @pyqtProperty("QVariantList", notify=instancesChanged)
    def discoveredInstances(self) -> List[Any]:
        if self._network_plugin:
            instances = list(self._network_plugin.getInstances().values())
            instances.sort(key=lambda k: k.name)
            return instances
        else:
            return []

    @pyqtSlot(str)
    def setInstanceId(self, key: str) -> None:
        global_container_stack = self._application.getGlobalContainerStack()
        if global_container_stack:
            global_container_stack.setMetaDataEntry("octoprint_id", key)

        if self._network_plugin:
            # Ensure that the connection states are refreshed.
            self._network_plugin.reCheckConnections()

        self.instanceIdChanged.emit()

    @pyqtProperty(str, notify=instanceIdChanged)
    def instanceId(self) -> str:
        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            return ""

        return global_container_stack.getMetaDataEntry("octoprint_id", "")

    @pyqtSlot(str)
    def requestApiKey(self, instance_id: str) -> None:
        (
            instance,
            base_url,
            basic_auth_username,
            basic_auth_password,
        ) = self._getInstanceInfo(instance_id)
        if not base_url:
            return

        ## Request appkey
        self._appkey_instance_id = instance_id
        self._appkey_request = self._createRequest(
            QUrl(base_url + "plugin/appkeys/request"),
            basic_auth_username,
            basic_auth_password,
        )
        self._appkey_request.setRawHeader(b"Content-Type", b"application/json")
        data = json.dumps({"app": "Cura"})
        self._appkey_reply = self._network_manager.post(
            self._appkey_request, data.encode()
        )

    @pyqtSlot()
    def cancelApiKeyRequest(self) -> None:
        if self._appkey_reply:
            if self._appkey_reply.isRunning():
                self._appkey_reply.abort()
            self._appkey_reply = None

        self._appkey_request = None  # type: Optional[QNetworkRequest]

        self._appkey_poll_timer.stop()

    def _pollApiKey(self) -> None:
        if not self._appkey_request:
            return
        self._appkey_reply = self._network_manager.get(self._appkey_request)

    @pyqtSlot(str)
    def probeAppKeySupport(self, instance_id: str) -> None:
        (
            instance,
            base_url,
            basic_auth_username,
            basic_auth_password,
        ) = self._getInstanceInfo(instance_id)
        if not base_url or not instance:
            return

        instance.getAdditionalData()

        self._instance_supports_appkeys = False
        self.appKeysSupportedChanged.emit()

        appkey_probe_request = self._createRequest(
            QUrl(base_url + "plugin/appkeys/probe"),
            basic_auth_username,
            basic_auth_password,
        )
        self._appkey_reply = self._network_manager.get(appkey_probe_request)

    @pyqtSlot(str, str)
    def testApiKey(self, instance_id: str, api_key: str) -> None:
        (
            instance,
            base_url,
            basic_auth_username,
            basic_auth_password,
        ) = self._getInstanceInfo(instance_id)
        if not base_url:
            return

        self._instance_responded = False
        self._instance_api_key_accepted = False
        self._instance_supports_sd = False
        self._instance_supports_camera = False
        self._instance_installed_plugins = []  # type: List[str]
        self.selectedInstanceSettingsChanged.emit()

        if self._settings_reply:
            if self._settings_reply.isRunning():
                self._settings_reply.abort()
            self._settings_reply = None
        if self._settings_reply_timeout:
            self._settings_reply_timeout = None

        if api_key != "":
            Logger.log(
                "d",
                "Trying to access OctoPrint instance at %s with the provided API key."
                % base_url,
            )

            ## Request 'settings' dump
            settings_request = self._createRequest(
                QUrl(base_url + "api/settings"),
                basic_auth_username,
                basic_auth_password,
            )
            settings_request.setRawHeader(b"X-Api-Key", api_key.encode())
            self._settings_reply = self._network_manager.get(settings_request)
            self._settings_reply_timeout = NetworkReplyTimeout(
                self._settings_reply, 20000, self._onRequestFailed
            )

            self._settings_instance = instance

    @pyqtSlot(str)
    def setApiKey(self, api_key: str) -> None:
        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            return

        global_container_stack.setMetaDataEntry(
            "octoprint_api_key",
            base64.b64encode(api_key.encode("ascii")).decode("ascii"),
        )

        self._keys_cache[self.instanceId] = api_key
        keys_cache = base64.b64encode(
            json.dumps(self._keys_cache).encode("ascii")
        ).decode("ascii")
        self._preferences.setValue("octoprint/keys_cache", keys_cache)

        if self._network_plugin:
            # Ensure that the connection states are refreshed.
            self._network_plugin.reCheckConnections()

    ##  Get the stored API key of an instance, or the one stored in the machine instance
    #   \return key String containing the key of the machine.
    @pyqtSlot(str, result=str)
    def getApiKey(self, instance_id: str) -> str:
        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            return ""

        if instance_id == self.instanceId:
            api_key = self._deobfuscateString(
                global_container_stack.getMetaDataEntry("octoprint_api_key", "")
            )
        else:
            api_key = self._keys_cache.get(instance_id, "")

        return api_key

    selectedInstanceSettingsChanged = pyqtSignal()

    @pyqtProperty(bool, notify=selectedInstanceSettingsChanged)
    def instanceResponded(self) -> bool:
        return self._instance_responded

    @pyqtProperty(bool, notify=selectedInstanceSettingsChanged)
    def instanceInError(self) -> bool:
        return self._instance_in_error

    @pyqtProperty(bool, notify=selectedInstanceSettingsChanged)
    def instanceApiKeyAccepted(self) -> bool:
        return self._instance_api_key_accepted

    @pyqtProperty(bool, notify=selectedInstanceSettingsChanged)
    def instanceSupportsSd(self) -> bool:
        return self._instance_supports_sd

    @pyqtProperty(bool, notify=selectedInstanceSettingsChanged)
    def instanceSupportsCamera(self) -> bool:
        return self._instance_supports_camera

    @pyqtProperty("QStringList", notify=selectedInstanceSettingsChanged)
    def instanceInstalledPlugins(self) -> List[str]:
        return self._instance_installed_plugins

    @pyqtProperty("QVariantList", notify=selectedInstanceSettingsChanged)
    def instanceAvailablePowerPlugins(self) -> List[Dict[str, str]]:
        available_plugins = self._power_plugins_manager.getAvailablePowerPlugs()
        return [
            {"key": plug_id, "text": plug_data["name"]}
            for (plug_id, plug_data) in available_plugins.items()
        ]

    @pyqtProperty(bool, notify=appKeysSupportedChanged)
    def instanceSupportsAppKeys(self) -> bool:
        return self._instance_supports_appkeys

    @pyqtSlot(str, str, str)
    def setContainerMetaDataEntry(
        self, container_id: str, key: str, value: str
    ) -> None:
        containers = ContainerRegistry.getInstance().findContainers(id=container_id)
        if not containers:
            Logger.log(
                "w",
                "Could not set metadata of container %s because it was not found.",
                container_id,
            )
            return

        containers[0].setMetaDataEntry(key, value)

    @pyqtSlot(bool)
    def applyGcodeFlavorFix(self, apply_fix: bool) -> None:
        global_container_stack = self._application.getGlobalContainerStack()
        if not global_container_stack:
            return

        gcode_flavor = "RepRap (Marlin/Sprinter)" if apply_fix else "UltiGCode"
        if (
            global_container_stack.getProperty("machine_gcode_flavor", "value")
            == gcode_flavor
        ):
            # No need to add a definition_changes container if the setting is not going to be changed
            return

        # Make sure there is a definition_changes container to store the machine settings
        definition_changes_container = global_container_stack.definitionChanges
        if (
            definition_changes_container
            == ContainerRegistry.getInstance().getEmptyInstanceContainer()
        ):
            definition_changes_container = (
                CuraStackBuilder.createDefinitionChangesContainer(
                    global_container_stack, global_container_stack.getId() + "_settings"
                )
            )

        definition_changes_container.setProperty(
            "machine_gcode_flavor", "value", gcode_flavor
        )

        # Update the has_materials metadata flag after switching gcode flavor
        definition = global_container_stack.getBottom()
        if (
            not definition
            or definition.getProperty("machine_gcode_flavor", "value") != "UltiGCode"
            or definition.getMetaDataEntry("has_materials", False)
        ):

            # In other words: only continue for the UM2 (extended), but not for the UM2+
            return

        has_materials = (
            global_container_stack.getProperty("machine_gcode_flavor", "value")
            != "UltiGCode"
        )

        material_container = global_container_stack.material

        if has_materials:
            global_container_stack.setMetaDataEntry("has_materials", True)

            # Set the material container to a sane default
            if (
                material_container
                == ContainerRegistry.getInstance().getEmptyInstanceContainer()
            ):
                search_criteria = {
                    "type": "material",
                    "definition": "fdmprinter",
                    "id": global_container_stack.getMetaDataEntry("preferred_material"),
                }
                materials = ContainerRegistry.getInstance().findInstanceContainers(
                    **search_criteria
                )
                if materials:
                    global_container_stack.material = materials[0]
        else:
            # The metadata entry is stored in an ini, and ini files are parsed as strings only.
            # Because any non-empty string evaluates to a boolean True, we have to remove the entry to make it False.
            if "has_materials" in global_container_stack.getMetaData():
                global_container_stack.removeMetaDataEntry("has_materials")

            global_container_stack.material = (
                ContainerRegistry.getInstance().getEmptyInstanceContainer()
            )

        self._application.globalContainerStackChanged.emit()

    @pyqtSlot(str)
    def openWebPage(self, url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def _createAdditionalComponentsView(self) -> None:
        Logger.log(
            "d", "Creating additional ui components for OctoPrint-connected printers."
        )

        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "qml", "OctoPrintComponents.qml"
        )
        self._additional_components = self._application.createQmlComponent(
            path, {"manager": self}
        )
        if not self._additional_components:
            Logger.log(
                "w",
                "Could not create additional components for OctoPrint-connected printers.",
            )
            return

        self._application.addAdditionalComponent(
            "monitorButtons",
            self._additional_components.findChild(QObject, "openOctoPrintButton"),
        )

    def _onRequestFailed(self, reply: QNetworkReply) -> None:
        if reply.operation() == QNetworkAccessManagerOperations.GetOperation:
            if (
                "api/settings" in reply.url().toString()
            ):  # OctoPrint settings dump from /settings:
                Logger.log(
                    "w",
                    "Connection refused or timeout when trying to access OctoPrint at %s"
                    % reply.url().toString(),
                )
                self._instance_in_error = True
                self.selectedInstanceSettingsChanged.emit()

    ##  Handler for all requests that have finished.
    def _onRequestFinished(self, reply: QNetworkReply) -> None:

        http_status_code = reply.attribute(QNetworkRequestAttributes.HttpStatusCodeAttribute)
        if not http_status_code:
            # Received no or empty reply
            self._onRequestFailed(reply)
            return

        json_data = None

        if reply.operation() == QNetworkAccessManagerOperations.PostOperation:
            if (
                "/plugin/appkeys/request" in reply.url().toString()
            ):  # Initial AppKey request
                if http_status_code == 201 or http_status_code == 202:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log(
                            "w", "Received invalid JSON from octoprint instance."
                        )

                    base_url = reply.url().toString()
                    base_url = base_url[:base_url.find("/plugin/appkeys/request")]

                    if json_data:
                        app_token = json_data["app_token"]  # unused; app_token is included in location header
                        auth_dialog_url = json_data["auth_dialog"] if "auth_dialog" in json_data else base_url
                    else:
                        (
                            instance,
                            base_url,
                            basic_auth_username,
                            basic_auth_password,
                        ) = self._getInstanceInfo(self._appkey_instance_id)

                        auth_dialog_url = base_url

                    if auth_dialog_url:
                        self.openWebPage(auth_dialog_url)

                    Logger.log("w", "Start polling for AppKeys decision")
                    if not self._appkey_request:
                        return
                    self._appkey_request.setUrl(
                        reply.header(QNetworkRequestKnownHeaders.LocationHeader)
                    )
                    self._appkey_request.setRawHeader(b"Content-Type", b"")
                    self._appkey_poll_timer.start()
                elif http_status_code == 404:
                    Logger.log(
                        "w", "This instance of OctoPrint does not support AppKeys"
                    )
                    self._appkey_request = None  # type: Optional[QNetworkRequest]
                else:
                    response = bytes(reply.readAll()).decode()
                    Logger.log(
                        "w",
                        "Unknown response when requesting an AppKey: %d. OctoPrint said %s"
                        % (http_status_code, response),
                    )
                    self._appkey_request = None  # type: Optional[QNetworkRequest]

        if reply.operation() == QNetworkAccessManagerOperations.GetOperation:
            if (
                "/plugin/appkeys/probe" in reply.url().toString()
            ):  # Probe for AppKey support
                if http_status_code == 204:
                    self._instance_supports_appkeys = True
                else:
                    self._instance_supports_appkeys = False
                self.appKeysSupportedChanged.emit()

            if (
                "/plugin/appkeys/request" in reply.url().toString()
            ):  # Periodic AppKey request poll
                if http_status_code == 202:
                    self._appkey_poll_timer.start()
                elif http_status_code == 200:
                    Logger.log("d", "AppKey granted")
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log(
                            "w", "Received invalid JSON from octoprint instance."
                        )

                    if json_data:
                        api_key = json_data["api_key"]
                        self._keys_cache[
                            self._appkey_instance_id
                        ] = api_key  # store api key in key cache

                        self.appKeyReceived.emit()
                elif http_status_code == 404:
                    Logger.log("d", "AppKey denied")
                else:
                    response = bytes(reply.readAll()).decode()
                    Logger.log(
                        "w",
                        "Unknown response when waiting for an AppKey: %d. OctoPrint said %s"
                        % (http_status_code, response),
                    )

                if http_status_code != 202:
                    self._appkey_request = None  # type: Optional[QNetworkRequest]

            if (
                "api/settings" in reply.url().toString()
            ):  # OctoPrint settings dump from /settings:
                self._instance_in_error = False

                if http_status_code == 200:
                    Logger.log("d", "API key accepted by OctoPrint.")
                    self._instance_api_key_accepted = True

                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log(
                            "w", "Received invalid JSON from octoprint instance."
                        )
                        json_data = {}

                    if "feature" in json_data and "sdSupport" in json_data["feature"]:
                        self._instance_supports_sd = json_data["feature"]["sdSupport"]

                    if "webcam" in json_data and "streamUrl" in json_data["webcam"]:
                        stream_url = json_data["webcam"]["streamUrl"]
                        if stream_url:  # not empty string or None
                            self._instance_supports_camera = True

                    if "plugins" in json_data:
                        self._power_plugins_manager.parsePluginData(
                            json_data["plugins"]
                        )
                        self._instance_installed_plugins = list(
                            json_data["plugins"].keys()
                        )

                    if self._settings_instance:
                        api_key = bytes(reply.request().rawHeader(b"X-Api-Key")).decode(
                            "utf-8"
                        )

                        self._settings_instance.setApiKey(
                            api_key
                        )  # store api key in key cache
                        if self._settings_instance.getId() == self.instanceId:
                            self.setApiKey(api_key)

                        self._settings_instance.resetOctoPrintUserName()
                        self._settings_instance.getAdditionalData()
                        self._settings_instance.parseSettingsData(json_data)

                    self._settings_instance = None

                elif http_status_code == 401:
                    Logger.log("d", "Invalid API key for OctoPrint.")
                    self._instance_api_key_accepted = False

                elif http_status_code == 502 or http_status_code == 503:
                    Logger.log("d", "OctoPrint is not running.")
                    self._instance_api_key_accepted = False
                    self._instance_in_error = True

                self._instance_responded = True
                self.selectedInstanceSettingsChanged.emit()

    def _createRequest(
        self, url: str, basic_auth_username: str = "", basic_auth_password: str = ""
    ) -> QNetworkRequest:
        request = QNetworkRequest(url)
        try:
            request.setAttribute(QNetworkRequest.FollowRedirectsAttribute, True)
        except AttributeError:
            # in Qt6, this is no longer possible (or required), see https://doc.qt.io/qt-6/network-changes-qt6.html#redirect-policies
            pass
        request.setRawHeader(b"User-Agent", self._user_agent)

        if basic_auth_username and basic_auth_password:
            data = base64.b64encode(
                ("%s:%s" % (basic_auth_username, basic_auth_password)).encode()
            ).decode("utf-8")
            request.setRawHeader(b"Authorization", ("Basic %s" % data).encode())

        # ignore SSL errors (eg for self-signed certificates)
        ssl_configuration = QSslConfiguration.defaultConfiguration()
        ssl_configuration.setPeerVerifyMode(QSslSocketPeerVerifyModes.VerifyNone)
        request.setSslConfiguration(ssl_configuration)

        return request

    ##  Utility handler to base64-decode a string (eg an obfuscated API key), if it has been encoded before
    def _deobfuscateString(self, source: str) -> str:
        try:
            return base64.b64decode(source.encode("ascii")).decode("ascii")
        except UnicodeDecodeError:
            return source

    def _getInstanceInfo(
        self, instance_id: str
    ) -> Tuple[Optional[OctoPrintOutputDevice], str, str, str]:
        if not self._network_plugin:
            return (None, "", "", "")
        instance = self._network_plugin.getInstanceById(instance_id)
        if not instance:
            return (None, "", "", "")

        return (
            instance,
            instance.baseURL,
            instance.getProperty("userName"),
            instance.getProperty("password"),
        )
