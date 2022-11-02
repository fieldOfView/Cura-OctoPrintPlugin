# Copyright (c) 2022 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

from UM.i18n import i18nCatalog
from UM.Logger import Logger
from UM.Signal import signalemitter
from UM.Message import Message
from UM.Util import parseBool
from UM.Version import Version
from UM.Mesh.MeshWriter import MeshWriter
from UM.PluginRegistry import PluginRegistry
from UM.PluginError import PluginNotFoundError

from cura.CuraApplication import CuraApplication

from .OctoPrintOutputController import OctoPrintOutputController
from .PowerPlugins import PowerPlugins
from .WebcamsModel import WebcamsModel
from .UploadOptions import UploadOptions

try:
    # Cura 4.1 and newer
    from cura.PrinterOutput.PrinterOutputDevice import (
        PrinterOutputDevice,
        ConnectionState,
    )
    from cura.PrinterOutput.Models.PrinterOutputModel import PrinterOutputModel
    from cura.PrinterOutput.Models.PrintJobOutputModel import PrintJobOutputModel
except ImportError:
    # Cura 3.5 - Cura 4.0
    from cura.PrinterOutputDevice import PrinterOutputDevice, ConnectionState
    from cura.PrinterOutput.PrinterOutputModel import PrinterOutputModel
    from cura.PrinterOutput.PrintJobOutputModel import PrintJobOutputModel

from cura.PrinterOutput.NetworkedPrinterOutputDevice import NetworkedPrinterOutputDevice

try:
    from cura.ApplicationMetadata import CuraSDKVersion
except ImportError: # Cura <= 3.6
    CuraSDKVersion = "6.0.0"
USE_QT5 = False
if CuraSDKVersion >= "8.0.0":
    from PyQt6.QtNetwork import (
        QHttpPart,
        QNetworkRequest,
        QNetworkAccessManager,
    )
    from PyQt6.QtNetwork import QNetworkReply, QSslConfiguration, QSslSocket
    from PyQt6.QtCore import (
        QUrl,
        QTimer,
        pyqtSignal,
        pyqtProperty,
        pyqtSlot,
        QCoreApplication,
    )
    from PyQt6.QtGui import QImage, QDesktopServices

    QNetworkAccessManagerOperations = QNetworkAccessManager.Operation
    QNetworkRequestKnownHeaders = QNetworkRequest.KnownHeaders
    QNetworkRequestAttributes = QNetworkRequest.Attribute
    QNetworkReplyNetworkErrors = QNetworkReply.NetworkError
    QSslSocketPeerVerifyModes = QSslSocket.PeerVerifyMode

else:
    from PyQt5.QtNetwork import (
        QHttpPart,
        QNetworkRequest,
        QNetworkAccessManager,
    )
    from PyQt5.QtNetwork import QNetworkReply, QSslConfiguration, QSslSocket
    from PyQt5.QtCore import (
        QUrl,
        QTimer,
        pyqtSignal,
        pyqtProperty,
        pyqtSlot,
        QCoreApplication,
    )
    from PyQt5.QtGui import QImage, QDesktopServices

    QNetworkAccessManagerOperations = QNetworkAccessManager
    QNetworkRequestKnownHeaders = QNetworkRequest
    QNetworkRequestAttributes = QNetworkRequest
    QNetworkReplyNetworkErrors = QNetworkReply
    QSslSocketPeerVerifyModes = QSslSocket

    USE_QT5 = True

import json
import os.path
import re
from time import time
import base64
from io import StringIO, BytesIO
from enum import IntEnum
from collections import namedtuple

from typing import cast, Any, Callable, Dict, List, Optional, Union, TYPE_CHECKING

if TYPE_CHECKING:
    from UM.Scene.SceneNode import SceneNode  # For typing.
    from UM.FileHandler.FileHandler import FileHandler  # For typing.

from UM.Resources import Resources

Resources.addSearchPath(
    os.path.join(os.path.abspath(os.path.dirname(__file__)))
)  # Plugin translation file import

i18n_catalog = i18nCatalog("octoprint")

if i18n_catalog.hasTranslationLoaded():
    Logger.log("i", "OctoPrint Plugin translation loaded!")


##  The current processing state of the backend.
#   This shadows PrinterOutputDevice.ConnectionState because its spelling changed
#   between Cura 4.0 beta 1 and beta 2
class UnifiedConnectionState(IntEnum):
    try:
        Closed = ConnectionState.Closed
        Connecting = ConnectionState.Connecting
        Connected = ConnectionState.Connected
        Busy = ConnectionState.Busy
        Error = ConnectionState.Error
    except AttributeError:
        Closed = ConnectionState.closed  # type: ignore
        Connecting = ConnectionState.connecting  # type: ignore
        Connected = ConnectionState.connected  # type: ignore
        Busy = ConnectionState.busy  # type: ignore
        Error = ConnectionState.error  # type: ignore


AxisInformation = namedtuple("AxisInformation", ["speed", "inverted"])

##  OctoPrint connected (wifi / lan) printer using the OctoPrint API
@signalemitter
class OctoPrintOutputDevice(NetworkedPrinterOutputDevice):
    def __init__(
        self, instance_id: str, address: str, port: int, properties: dict, **kwargs
    ) -> None:
        super().__init__(
            device_id=instance_id, address=address, properties=properties, **kwargs
        )

        self._address = address
        self._port = port
        self._path = properties.get(b"path", b"/").decode("utf-8")
        if self._path[-1:] != "/":
            self._path += "/"
        self._id = instance_id
        self._properties = properties  # Properties dict as provided by zero conf

        self._printer_model = ""
        self._printer_name = ""

        self._octoprint_version = self._properties.get(b"version", b"").decode("utf-8")
        self._octoprint_user_name = ""

        self._axis_information = {
            axis: AxisInformation(speed=6000 if axis != "e" else 300, inverted=False)
            for axis in ["x", "y", "z", "e"]
        }

        self._gcode_stream = StringIO()  # type: Union[StringIO, BytesIO]

        self._forced_queue = False
        self._select_and_print_handled_in_upload = False

        # We start with a single extruder, but update this when we get data from octoprint
        self._number_of_extruders_set = False
        self._number_of_extruders = 1

        # Try to get version information from plugin.json
        plugin_file_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "plugin.json"
        )
        try:
            with open(plugin_file_path) as plugin_file:
                plugin_info = json.load(plugin_file)
                plugin_version = plugin_info["version"]
        except:
            # The actual version info is not critical to have so we can continue
            plugin_version = "Unknown"
            Logger.logException("w", "Could not get version information for the plugin")

        application = CuraApplication.getInstance()
        self._user_agent = "%s/%s %s/%s" % (
            application.getApplicationName(),
            application.getVersion(),
            "OctoPrintPlugin",
            plugin_version,
        )  # NetworkedPrinterOutputDevice defines this as string, so we encode this later

        self._api_prefix = "api/"
        self._api_key = b""

        self._protocol = "https" if properties.get(b"useHttps") == b"true" else "http"
        self._base_url = "%s://%s:%d%s" % (
            self._protocol,
            self._address,
            self._port,
            self._path,
        )
        self._api_url = self._base_url + self._api_prefix

        self._basic_auth_data = None
        self._basic_auth_string = ""
        basic_auth_username = properties.get(b"userName", b"").decode("utf-8")
        basic_auth_password = properties.get(b"password", b"").decode("utf-8")
        if basic_auth_username and basic_auth_password:
            data = base64.b64encode(
                ("%s:%s" % (basic_auth_username, basic_auth_password)).encode()
            ).decode("utf-8")
            self._basic_auth_data = ("basic %s" % data).encode()
            self._basic_auth_string = "%s:%s" % (
                basic_auth_username,
                basic_auth_password,
            )

        try:
            major_api_version = application.getAPIVersion().getMajor()
        except AttributeError:
            # UM.Application.getAPIVersion was added for API > 6 (Cura 4)
            # Since this plugin version is only compatible with Cura 3.5 and newer, it is safe to assume API 5
            major_api_version = 5

        qml_folder = "qml" if not USE_QT5 else "qml_qt5"
        if not USE_QT5:
            # In Cura 5.x, the monitor item can only contain QtQuick Controls 2 items
            qml_file = "MonitorItem.qml"
        elif major_api_version > 5:
            # In Cura 4.x, the monitor item shows the camera stream as well as the monitor sidebar
            qml_file = "MonitorItem4x.qml"
        else:
            # In Cura 3.x, the monitor item only shows the camera stream
            qml_file = "MonitorItem3x.qml"

        self._monitor_view_qml_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), qml_folder, qml_file
        )

        name = self._id
        matches = re.search(r"^\"(.*)\"\._octoprint\._tcp.local$", name)
        if matches:
            name = matches.group(1)

        self.setPriority(
            2
        )  # Make sure the output device gets selected above local file output
        self.setName(name)
        self.setShortDescription(
            i18n_catalog.i18nc("@action:button", "Print with OctoPrint")
        )
        self.setDescription(
            i18n_catalog.i18nc("@properties:tooltip", "Print with OctoPrint")
        )
        self.setIconName("print")
        self.setConnectionText(
            i18n_catalog.i18nc("@info:status", "Connected to OctoPrint on {0}").format(
                self._id
            )
        )

        self._post_gcode_reply = None

        self._progress_message = None  # type: Optional[Message]
        self._error_message = None  # type: Optional[Message]
        self._waiting_message = None  # type: Optional[Message]

        self._queued_gcode_commands = []  # type: List[str]

        # TODO; Add preference for update intervals
        self._update_fast_interval = 2000
        self._update_slow_interval = 10000
        self._update_timer = QTimer()
        self._update_timer.setInterval(self._update_fast_interval)
        self._update_timer.setSingleShot(False)
        self._update_timer.timeout.connect(self._update)

        self._show_camera = True
        self._webcams_model = WebcamsModel(
            self._protocol, self._address, self.port, self._basic_auth_string
        )

        self._power_plugins_manager = PowerPlugins()
        self._upload_options = UploadOptions()
        # confirm name, path, autostart etc before print
        self._confirm_upload_options = False

        # store gcode on sd card in printer instead of locally
        self._store_on_sd_supported = False

        # transfer gcode as .ufp files including thumbnail image
        self._ufp_transfer_supported = False

        self._ufp_plugin_version = Version(
            0
        )  # used to determine how gcode files are extracted from .ufp

        # wait for analysis to complete before starting a print
        self._gcode_analysis_requires_wait = False
        self._gcode_analysis_supported = False

        self._waiting_for_analysis = False
        self._waiting_for_printer = False

        self._output_controller = OctoPrintOutputController(self)

        self._polling_end_points = ["printer", "job"]

    @property
    def _store_on_sd(self) -> bool:
        global_container_stack = CuraApplication.getInstance().getGlobalContainerStack()
        if global_container_stack:
            return self._store_on_sd_supported and parseBool(
                global_container_stack.getMetaDataEntry("octoprint_store_sd", False)
            )
        return False

    @property
    def _transfer_as_ufp(self) -> bool:
        return self._ufp_transfer_supported and not self._store_on_sd

    @property
    def _wait_for_analysis(self) -> bool:
        return (
            self._gcode_analysis_requires_wait
            and self._gcode_analysis_supported
            and not self._store_on_sd
        )

    def getProperties(self) -> Dict[bytes, bytes]:
        return self._properties

    @pyqtSlot(str, result=str)
    def getProperty(self, key: str) -> str:
        key_b = key.encode("utf-8")
        if key_b in self._properties:
            return self._properties.get(key_b, b"").decode("utf-8")
        else:
            return ""

    ##  Get the unique key of this machine
    #   \return key String containing the key of the machine.
    @pyqtSlot(result=str)
    def getId(self) -> str:
        return self._id

    ##  Set the API key of this OctoPrint instance
    def setApiKey(self, api_key: str) -> None:
        self._api_key = api_key.encode()

    ##  Name of the instance (as returned from the zeroConf properties)
    @pyqtProperty(str, constant=True)
    def name(self) -> str:
        return self._name

    additionalDataChanged = pyqtSignal()

    ##  Version (as returned from the zeroConf properties or from /api/version)
    @pyqtProperty(str, notify=additionalDataChanged)
    def octoPrintVersion(self) -> str:
        return self._octoprint_version

    @pyqtProperty(str, notify=additionalDataChanged)
    def octoPrintUserName(self) -> str:
        return self._octoprint_user_name

    def resetOctoPrintUserName(self) -> None:
        self._octoprint_user_name = ""

    @pyqtProperty(str, notify=additionalDataChanged)
    def printerName(self) -> str:
        return self._printer_name

    @pyqtProperty(str, notify=additionalDataChanged)
    def printerModel(self) -> str:
        return self._printer_model

    def getAxisInformation(self) -> Dict[str, AxisInformation]:
        return self._axis_information

    ## IPadress of this instance
    @pyqtProperty(str, constant=True)
    def ipAddress(self) -> str:
        return self._address

    ## IPadress of this instance
    #  Overridden from NetworkedPrinterOutputDevice because OctoPrint does not
    #  send the ip address with zeroconf
    @pyqtProperty(str, notify=additionalDataChanged)
    def address(self) -> str:
        if self._octoprint_user_name:
            return "%s@%s" % (self._octoprint_user_name, self._address)
        else:
            return self._address

    ## port of this instance
    @pyqtProperty(int, constant=True)
    def port(self) -> int:
        return self._port

    ## path of this instance
    @pyqtProperty(str, constant=True)
    def path(self) -> str:
        return self._path

    ## absolute url of this instance
    @pyqtProperty(str, constant=True)
    def baseURL(self) -> str:
        return self._base_url

    @pyqtProperty("QVariant", constant=True)
    def webcamsModel(self) -> WebcamsModel:
        return self._webcams_model

    def setShowCamera(self, show_camera: bool) -> None:
        if show_camera != self._show_camera:
            self._show_camera = show_camera
            self.showCameraChanged.emit()

    showCameraChanged = pyqtSignal()

    @pyqtProperty(bool, notify=showCameraChanged)
    def showCamera(self) -> bool:
        return self._show_camera

    def setConfirmUploadOptions(self, confirm_upload_options: bool) -> None:
        if confirm_upload_options != self._confirm_upload_options:
            self._confirm_upload_options = confirm_upload_options
            self.confirmUploadOptionsChanged.emit()

    confirmUploadOptionsChanged = pyqtSignal()

    @pyqtProperty(bool, notify=confirmUploadOptionsChanged)
    def confirmUploadOptions(self) -> bool:
        return self._confirm_upload_options

    def _update(self) -> None:
        for end_point in self._polling_end_points:
            self.get(end_point, self._onRequestFinished)

    def close(self) -> None:
        if self._update_timer:
            self._update_timer.stop()

        self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Closed))
        if self._progress_message:
            self._progress_message.hide()
            self._progress_message = None  # type: Optional[Message]
        if self._error_message:
            self._error_message.hide()
            self._error_message = None  # type: Optional[Message]
        if self._waiting_message:
            self._waiting_message.hide()
            self._waiting_message = None  # type: Optional[Message]

        self._waiting_for_printer = False
        self._waiting_for_analysis = False
        self._polling_end_points = [
            point
            for point in self._polling_end_points
            if not point.startswith("files/")
        ]

    ##  Start requesting data from the instance
    def connect(self) -> None:
        self._createNetworkManager()

        self.setConnectionState(
            cast(ConnectionState, UnifiedConnectionState.Connecting)
        )
        self._update()  # Manually trigger the first update, as we don't want to wait a few secs before it starts.

        Logger.log(
            "d",
            "Connection with instance %s with url %s started",
            self._id,
            self._base_url,
        )
        self._update_timer.start()

        self._last_response_time = None  # type: Optional[float]
        self._setAcceptsCommands(False)
        self.setConnectionText(
            i18n_catalog.i18nc("@info:status", "Connecting to OctoPrint on {0}").format(
                self._id
            )
        )

        ## Request 'settings' dump
        self.get("settings", self._onRequestFinished)

        self.getAdditionalData()

    def getAdditionalData(self) -> None:
        if not self._api_key:
            return

        if not self._octoprint_version:
            self.get("version", self._onRequestFinished)

        if not self._octoprint_user_name and self._api_key:
            self._sendCommandToApi("login", {"passive": True})

        self.get("printerprofiles", self._onRequestFinished)

    ##  Stop requesting data from the instance
    def disconnect(self) -> None:
        Logger.log(
            "d",
            "Connection with instance %s with url %s stopped",
            self._id,
            self._base_url,
        )
        self.close()

    def pausePrint(self) -> None:
        self._sendJobCommand("pause")

    def resumePrint(self) -> None:
        if not self._printers[0].activePrintJob:
            Logger.log("e", "There is no active print job to resume")
            return

        if self._printers[0].activePrintJob.state == "paused":
            self._sendJobCommand("pause")
        else:
            self._sendJobCommand("start")

    def cancelPrint(self) -> None:
        self._sendJobCommand("cancel")

    def requestWrite(
        self,
        nodes: List["SceneNode"],
        file_name: Optional[str] = None,
        limit_mimetypes: bool = False,
        file_handler: Optional["FileHandler"] = None,
        filter_by_machine: bool = False,
        **kwargs
    ) -> None:
        global_container_stack = CuraApplication.getInstance().getGlobalContainerStack()
        if not global_container_stack or not self.activePrinter:
            Logger.log("e", "There is no active printer to send the print")
            return

        self._upload_options.configure(global_container_stack, file_name)

        if self._confirm_upload_options:
            self._upload_options.setProceedCallback(self.proceedRequestWrite)
            self._upload_options.showOptionsDialog()
        else:
            self.proceedRequestWrite()

    def proceedRequestWrite(self) -> None:
        global_container_stack = CuraApplication.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        # Make sure post-processing plugin are run on the gcode
        self.writeStarted.emit(self)

        # Get the g-code through the GCodeWriter plugin
        # This produces the same output as "Save to File", adding the print settings to the bottom of the file
        # The presliced print should always be send using `GCodeWriter`
        print_info = CuraApplication.getInstance().getPrintInformation()
        if not self._transfer_as_ufp or not print_info or print_info.preSliced:
            gcode_writer = cast(
                MeshWriter, PluginRegistry.getInstance().getPluginObject("GCodeWriter")
            )
            self._gcode_stream = StringIO()
        else:
            gcode_writer = cast(
                MeshWriter, PluginRegistry.getInstance().getPluginObject("UFPWriter")
            )
            self._gcode_stream = BytesIO()

        if not gcode_writer.write(self._gcode_stream, None):
            Logger.log("e", "GCodeWrite failed: %s" % gcode_writer.getInformation())
            return

        if self._error_message:
            self._error_message.hide()
            self._error_message = None  # type: Optional[Message]

        if self._progress_message:
            self._progress_message.hide()
            self._progress_message = None  # type: Optional[Message]

        self._forced_queue = False

        use_power_plugin = parseBool(
            global_container_stack.getMetaDataEntry("octoprint_power_control", False)
        )
        auto_connect = parseBool(
            global_container_stack.getMetaDataEntry("octoprint_auto_connect", False)
        )
        if (
            self.activePrinter.state == "offline"
            and self._upload_options.autoPrint
            and (use_power_plugin or auto_connect)
        ):
            wait_for_printer = False
            if use_power_plugin:
                available_plugs = self._power_plugins_manager.getAvailablePowerPlugs()
                power_plug_id = global_container_stack.getMetaDataEntry(
                    "octoprint_power_plug", ""
                )
                if power_plug_id == "" and len(available_plugs) > 0:
                    power_plug_id = list(
                        self._power_plugins_manager.getAvailablePowerPlugs().keys()
                    )[0]

                if power_plug_id in available_plugs:
                    (
                        end_point,
                        command,
                    ) = self._power_plugins_manager.getSetStateCommand(
                        power_plug_id, True
                    )
                    if end_point and command:
                        self._sendCommandToApi(end_point, command)
                        Logger.log(
                            "d",
                            "Sent %s command to endpoint %s"
                            % (command["command"], end_point),
                        )
                        wait_for_printer = True
                    else:
                        Logger.log("e", "No command to power on plug %s", power_plug_id)
                else:
                    Logger.log(
                        "e", "Specified power plug %s is not available", power_plug_id
                    )

            else:  # auto_connect
                self._sendCommandToApi("connection", "connect")
                Logger.log(
                    "d",
                    "Sent command to connect printer to OctoPrint with current settings",
                )

                wait_for_printer = True

            if wait_for_printer:
                self._waiting_message = Message(
                    i18n_catalog.i18nc(
                        "@info:status",
                        "Waiting for OctoPrint to connect to the printer...",
                    ),
                    title=i18n_catalog.i18nc("@label", "OctoPrint"),
                    progress=-1,
                    lifetime=0,
                    dismissable=False,
                    use_inactivity_timer=False,
                )
                self._waiting_message.addAction(
                    "queue",
                    i18n_catalog.i18nc("@action:button", "Queue"),
                    "",
                    i18n_catalog.i18nc(
                        "@action:tooltip",
                        "Stop waiting for the printer and queue the print job instead",
                    ),
                    button_style=Message.ActionButtonStyle.SECONDARY,
                )
                self._waiting_message.addAction(
                    "cancel",
                    i18n_catalog.i18nc("@action:button", "Cancel"),
                    "",
                    i18n_catalog.i18nc("@action:tooltip", "Abort the print job"),
                )
                self._waiting_message.actionTriggered.connect(
                    self._stopWaitingForPrinter
                )

                self._waiting_message.show()
                self._waiting_for_printer = True
                return

        elif self.activePrinter.state not in ["idle", ""]:
            Logger.log(
                "d",
                "Tried starting a print, but current state is %s"
                % self.activePrinter.state,
            )
            error_string = ""
            if not self._upload_options.autoPrint:
                # Allow queueing the job even if OctoPrint is currently busy if autoprinting is disabled
                pass
            elif self.activePrinter.state == "offline":
                error_string = i18n_catalog.i18nc(
                    "@info:status", "The printer is offline. Unable to start a new job."
                )
            else:
                error_string = i18n_catalog.i18nc(
                    "@info:status", "OctoPrint is busy. Unable to start a new job."
                )

            if error_string:
                if self._error_message:
                    self._error_message.hide()
                self._error_message = Message(
                    error_string, title=i18n_catalog.i18nc("@label", "OctoPrint error")
                )
                self._error_message.addAction(
                    "queue",
                    i18n_catalog.i18nc("@action:button", "Queue job"),
                    "",
                    i18n_catalog.i18nc(
                        "@action:tooltip",
                        "Queue this print job so it can be printed later",
                    ),
                )
                self._error_message.actionTriggered.connect(self._queuePrintJob)
                self._error_message.show()
                return

        self._sendPrintJob()

    def _stopWaitingForAnalysis(self, message: Message, action_id: str) -> None:
        self._waiting_message = None  # type:Optional[Message]
        if message:
            message.hide()
        self._waiting_for_analysis = False

        for end_point in self._polling_end_points:
            if "files/" in end_point:
                break
        if "files/" not in end_point:
            Logger.log("e", "Could not find files/ endpoint")
            return

        self._polling_end_points = [
            point
            for point in self._polling_end_points
            if not point.startswith("files/")
        ]

        if action_id == "print":
            self._selectAndPrint(end_point)
        elif action_id == "cancel":
            pass

    def _stopWaitingForPrinter(self, message: Message, action_id: str) -> None:
        self._waiting_message = None  # type:Optional[Message]
        if message:
            message.hide()
        self._waiting_for_printer = False

        if action_id == "queue":
            self._forced_queue = True
            self._sendPrintJob()
        elif action_id == "cancel":
            self._gcode_stream = StringIO()  # type: Union[StringIO, BytesIO]

    def _queuePrintJob(self, message: Message, action_id: str) -> None:
        self._error_message = None  # type:Optional[Message]
        if message:
            message.hide()

        self._forced_queue = True
        self._sendPrintJob()

    def _sendPrintJob(self) -> None:
        global_container_stack = CuraApplication.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        if self._upload_options.autoPrint and not self._forced_queue:
            CuraApplication.getInstance().getController().setActiveStage("MonitorStage")

            # cancel any ongoing preheat timer before starting a print
            try:
                self._printers[0].stopPreheatTimers()
            except AttributeError:
                # stopPreheatTimers was added after Cura 3.3 beta
                pass

        self._progress_message = Message(
            i18n_catalog.i18nc("@info:status", "Sending data to OctoPrint..."),
            title=i18n_catalog.i18nc("@label", "OctoPrint"),
            progress=-1,
            lifetime=0,
            dismissable=False,
            use_inactivity_timer=False,
        )
        self._progress_message.addAction(
            "cancel",
            i18n_catalog.i18nc("@action:button", "Cancel"),
            "",
            i18n_catalog.i18nc("@action:tooltip", "Abort the print job"),
        )

        self._progress_message.actionTriggered.connect(self._cancelSendGcode)
        self._progress_message.show()

        job_name = self._upload_options.fileName.lstrip(" ").rstrip(" ")
        if job_name == "":
            job_name = "untitled_print"
        path = self._upload_options.filePath.lstrip("/ ").rstrip("/ ")
        if path != "":
            job_name = "%s/%s" % (path, job_name)

        print_info = CuraApplication.getInstance().getPrintInformation()

        ##  Presliced print is always send as gcode
        extension = (
            "gcode" if not self._transfer_as_ufp or print_info.preSliced else "ufp"
        )
        file_name = "%s.%s" % (os.path.basename(job_name), extension)

        ##  Create multi_part request
        post_parts = []  # type: List[QHttpPart]

        ##  Create parts (to be placed inside multipart)
        gcode_body = self._gcode_stream.getvalue()
        if isinstance(gcode_body, str):
            # encode StringIO result to bytes
            gcode_body = gcode_body.encode()

        post_parts.append(
            self._createFormPart(
                'name="path"', os.path.dirname(job_name).encode(), "text/plain"
            )
        )
        post_parts.append(
            self._createFormPart(
                'name="file"; filename="%s"' % file_name,
                gcode_body,
                "application/octet-stream",
            )
        )

        if self._store_on_sd or (
            not self._wait_for_analysis and not self._transfer_as_ufp
        ):
            self._select_and_print_handled_in_upload = True

            if not self._forced_queue:
                # tell OctoPrint to start the print when there is no reason to delay doing so
                if self._upload_options.autoSelect or self._upload_options.autoPrint:
                    post_parts.append(
                        self._createFormPart('name="select"', b"true", "text/plain")
                    )
                if self._upload_options.autoPrint:
                    post_parts.append(
                        self._createFormPart('name="print"', b"true", "text/plain")
                    )
        else:
            # otherwise selecting and printing the job is delayed until after the upload
            # see self._onUploadFinished
            self._select_and_print_handled_in_upload = False

        destination = "local"
        if self._store_on_sd:
            destination = "sdcard"

        try:
            ##  Post request + data
            post_gcode_request = self._createEmptyRequest(
                "files/" + destination, content_type="application/x-www-form-urlencoded"
            )
            self._post_gcode_reply = self.postFormWithParts(
                "files/" + destination,
                post_parts,
                on_finished=self._onUploadFinished,
                on_progress=self._onUploadProgress,
            )

        except Exception as e:
            self._progress_message.hide()
            self._error_message = Message(
                i18n_catalog.i18nc("@info:status", "Unable to send data to OctoPrint."),
                title=i18n_catalog.i18nc("@label", "OctoPrint error"),
            )
            self._error_message.show()
            Logger.log("e", "An exception occurred in network connection: %s" % str(e))

        self._gcode_stream = StringIO()  # type: Union[StringIO, BytesIO]

    def _cancelSendGcode(self, message: Message, action_id: str) -> None:
        self._progress_message = None  # type:Optional[Message]
        if message:
            message.hide()

        if self._post_gcode_reply:
            Logger.log("d", "Stopping upload because the user pressed cancel.")
            try:
                self._post_gcode_reply.uploadProgress.disconnect(self._onUploadProgress)
            except TypeError:
                pass  # The disconnection can fail on mac in some cases. Ignore that.

            self._post_gcode_reply.abort()
            self._post_gcode_reply = None  # type:Optional[QNetworkReply]

    def sendCommand(self, command: str) -> None:
        self._queued_gcode_commands.append(command)
        CuraApplication.getInstance().callLater(self._sendQueuedGcode)

    # Send gcode commands that are queued in quick succession as a single batch
    def _sendQueuedGcode(self) -> None:
        if self._queued_gcode_commands:
            self._sendCommandToApi("printer/command", self._queued_gcode_commands)
            Logger.log(
                "d",
                "Sent gcode command to OctoPrint instance: %s",
                self._queued_gcode_commands,
            )
            self._queued_gcode_commands = []  # type: List[str]

    def _sendJobCommand(self, command: str) -> None:
        self._sendCommandToApi("job", command)
        Logger.log("d", "Sent job command to OctoPrint instance: %s", command)

    def _sendCommandToApi(
        self, end_point: str, commands: Union[Dict[str, Any], str, List[str]]
    ) -> None:
        if isinstance(commands, dict):
            data = json.dumps(commands)
        elif isinstance(commands, list):
            data = json.dumps({"commands": commands})
        else:
            data = json.dumps({"command": commands})
        self.post(end_point, data, self._onRequestFinished)

    ##  Handler for all requests that have finished.
    def _onRequestFinished(self, reply: QNetworkReply) -> None:
        if reply.error() == QNetworkReplyNetworkErrors.TimeoutError:
            Logger.log("w", "Received a timeout on a request to the instance")
            self._connection_state_before_timeout = self._connection_state
            self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Error))
            return

        if (
            self._connection_state_before_timeout
            and reply.error() == QNetworkReplyNetworkErrors.NoError
        ):
            #  There was a timeout, but we got a correct answer again.
            if self._last_response_time:
                Logger.log(
                    "d",
                    "We got a response from the instance after %s of silence",
                    time() - self._last_response_time,
                )
            self.setConnectionState(self._connection_state_before_timeout)
            self._connection_state_before_timeout = None

        if reply.error() == QNetworkReplyNetworkErrors.NoError:
            self._last_response_time = time()

        http_status_code = reply.attribute(QNetworkRequestAttributes.HttpStatusCodeAttribute)
        if not http_status_code:
            # Received no or empty reply
            return

        content_type = bytes(reply.rawHeader(b"Content-Type")).decode("utf-8")

        if reply.operation() == QNetworkAccessManagerOperations.GetOperation:
            if self._api_prefix + "printerprofiles" in reply.url().toString():
                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log(
                            "w", "Received invalid JSON from octoprint instance."
                        )
                        json_data = {}

                    for profile_id in json_data["profiles"]:
                        printer_profile = json_data["profiles"][profile_id]
                        if printer_profile.get("current", False):
                            self._printer_name = printer_profile.get("name", "")
                            self._printer_model = printer_profile.get("model", "")

                            try:
                                for axis in ["x", "y", "z", "e"]:
                                    self._axis_information[axis] = AxisInformation(
                                        speed=printer_profile["axes"][axis]["speed"],
                                        inverted=printer_profile["axes"][axis]["inverted"],
                                    )
                            except KeyError:
                                Logger.log(
                                    "w", "Unable to retreive axes information from OctoPrint printer profile."
                                )

                            self.additionalDataChanged.emit()
                            return
                else:
                    Logger.log(
                        "w",
                        "Instance does not report printerprofiles with provided API key",
                    )
                    return

            elif (
                self._api_prefix + "printer" in reply.url().toString()
            ):  # Status update from /printer.
                if not self._printers:
                    self._createPrinterList()

                # An OctoPrint instance has a single printer.
                printer = self._printers[0]
                if not printer:
                    Logger.log("e", "There is no active printer")
                    return
                update_pace = self._update_slow_interval

                if http_status_code == 200:
                    update_pace = self._update_fast_interval

                    if not self.acceptsCommands:
                        self._setAcceptsCommands(True)
                        self.setConnectionText(
                            i18n_catalog.i18nc(
                                "@info:status", "Connected to OctoPrint on {0}"
                            ).format(self._id)
                        )

                    if self._connection_state == UnifiedConnectionState.Connecting:
                        self.setConnectionState(
                            cast(ConnectionState, UnifiedConnectionState.Connected)
                        )
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log(
                            "w", "Received invalid JSON from octoprint instance."
                        )
                        json_data = {}

                    if "temperature" in json_data:
                        if not self._number_of_extruders_set:
                            self._number_of_extruders = 0
                            while (
                                "tool%d" % self._number_of_extruders
                                in json_data["temperature"]
                            ):
                                self._number_of_extruders += 1

                            if self._number_of_extruders > 1:
                                # Recreate list of printers to match the new _number_of_extruders
                                self._createPrinterList()
                                printer = self._printers[0]

                            if self._number_of_extruders > 0:
                                self._number_of_extruders_set = True

                        # Check for hotend temperatures
                        for index in range(0, self._number_of_extruders):
                            extruder = printer.extruders[index]
                            if ("tool%d" % index) in json_data["temperature"]:
                                hotend_temperatures = json_data["temperature"][
                                    "tool%d" % index
                                ]
                                target_temperature = (
                                    hotend_temperatures["target"]
                                    if hotend_temperatures["target"] is not None
                                    else -1
                                )
                                actual_temperature = (
                                    hotend_temperatures["actual"]
                                    if hotend_temperatures["actual"] is not None
                                    else -1
                                )
                                extruder.updateTargetHotendTemperature(
                                    target_temperature
                                )
                                extruder.updateHotendTemperature(actual_temperature)
                            else:
                                extruder.updateTargetHotendTemperature(0)
                                extruder.updateHotendTemperature(0)

                        if "bed" in json_data["temperature"]:
                            bed_temperatures = json_data["temperature"]["bed"]
                            actual_temperature = (
                                bed_temperatures["actual"]
                                if bed_temperatures["actual"] is not None
                                else -1
                            )
                            printer.updateBedTemperature(actual_temperature)
                            target_temperature = (
                                bed_temperatures["target"]
                                if bed_temperatures["target"] is not None
                                else -1
                            )
                            printer.updateTargetBedTemperature(target_temperature)
                        else:
                            printer.updateBedTemperature(-1)
                            printer.updateTargetBedTemperature(0)

                    printer_state = "offline"
                    if "state" in json_data:
                        flags = json_data["state"]["flags"]
                        if flags["error"] or flags["closedOrError"]:
                            printer_state = "error"
                        elif flags["paused"] or flags["pausing"]:
                            printer_state = "paused"
                        elif flags["printing"]:
                            printer_state = "printing"
                        elif flags["cancelling"]:
                            printer_state = "aborted"
                        elif flags["ready"] or flags["operational"]:
                            printer_state = "idle"
                        else:
                            Logger.log(
                                "w",
                                "Encountered unexpected printer state flags: %s"
                                % flags,
                            )
                    printer.updateState(printer_state)

                elif http_status_code == 401 or http_status_code == 403:
                    self._setOffline(
                        printer,
                        i18n_catalog.i18nc(
                            "@info:status",
                            "OctoPrint on {0} does not allow access to the printer state",
                        ).format(self._id),
                    )
                    return

                elif http_status_code == 409:
                    if self._connection_state == UnifiedConnectionState.Connecting:
                        self.setConnectionState(
                            cast(ConnectionState, UnifiedConnectionState.Connected)
                        )

                    self._setOffline(
                        printer,
                        i18n_catalog.i18nc(
                            "@info:status",
                            "The printer connected to OctoPrint on {0} is not operational",
                        ).format(self._id),
                    )
                    return

                elif http_status_code == 502 or http_status_code == 503:
                    Logger.log(
                        "w", "Received an error status code: %d", http_status_code
                    )
                    self._setOffline(
                        printer,
                        i18n_catalog.i18nc(
                            "@info:status", "OctoPrint on {0} is not running"
                        ).format(self._id),
                    )
                    return

                else:
                    self._setOffline(printer)
                    Logger.log(
                        "w", "Received an unexpected status code: %d", http_status_code
                    )

                if update_pace != self._update_timer.interval():
                    self._update_timer.setInterval(update_pace)

            elif (
                self._api_prefix + "job" in reply.url().toString()
            ):  # Status update from /job:
                if not self._printers or not self._printers[0]:
                    return  # Ignore the data for now, we don't have info about a printer yet.
                printer = self._printers[0]

                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log(
                            "w", "Received invalid JSON from octoprint instance."
                        )
                        json_data = {}

                    if printer.activePrintJob is None:
                        print_job = PrintJobOutputModel(
                            output_controller=self._output_controller
                        )
                        printer.updateActivePrintJob(print_job)
                    else:
                        print_job = printer.activePrintJob

                    print_job_state = "offline"
                    if "state" in json_data:
                        state = json_data["state"]
                        if not isinstance(state, str):
                            Logger.log(
                                "e", "Encountered non-string print job state: %s" % state
                            )
                        elif state.startswith("Error"):
                            print_job_state = "error"
                        elif state == "Pausing":
                            print_job_state = "pausing"
                        elif state == "Paused":
                            print_job_state = "paused"
                        elif state.startswith("Printing"):
                            print_job_state = "printing"
                        elif state == "Cancelling":
                            print_job_state = "abort"
                        elif state == "Operational":
                            print_job_state = "ready"
                            printer.updateState("idle")
                        elif (
                            state.startswith("Starting")
                            or state == "Connecting"
                            or state == "Sending file to SD"
                        ):
                            print_job_state = "pre_print"
                        elif state.startswith("Offline"):
                            print_job_state = "offline"
                        else:
                            Logger.log(
                                "w", "Encountered unexpected print job state: %s" % state
                            )
                    print_job.updateState(print_job_state)

                    if "progress" in json_data:
                        print_time = json_data["progress"]["printTime"]
                        completion = json_data["progress"]["completion"]

                        if print_time:
                            print_job.updateTimeElapsed(print_time)

                            print_time_left = json_data["progress"]["printTimeLeft"]
                            if print_time_left:  # not 0 or None or ""
                                print_job.updateTimeTotal(print_time + print_time_left)
                            elif completion:  # not 0 or None or ""
                                print_job.updateTimeTotal(
                                    int(print_time / (completion / 100))
                                )
                            else:
                                print_job.updateTimeTotal(0)
                        else:
                            print_job.updateTimeElapsed(0)
                            print_job.updateTimeTotal(0)

                    if (
                        completion and print_job_state == "pre_print"
                    ):  # completion not not 0 or None or "", state "Sending file to SD"
                        if not self._progress_message:
                            self._progress_message = Message(
                                i18n_catalog.i18nc(
                                    "@info:status",
                                    "Streaming file to the SD card of the printer...",
                                ),
                                0,
                                False,
                                -1,
                                title=i18n_catalog.i18nc("@label", "OctoPrint"),
                            )
                            self._progress_message.show()
                        if completion < 100:
                            self._progress_message.setProgress(completion)
                    else:
                        if (
                            self._progress_message
                            and self._progress_message.getText().startswith(
                                i18n_catalog.i18nc(
                                    "@info:status",
                                    "Streaming file to the SD card of the printer...",
                                )
                            )
                        ):
                            self._progress_message.hide()
                            self._progress_message = None  # type:Optional[Message]

                    print_job.updateName(json_data["job"]["file"]["name"])

                    if self._waiting_for_printer and printer.state == "idle":
                        self._waiting_for_printer = False
                        if self._waiting_message:
                            self._waiting_message.hide()
                        self._waiting_message = None
                        self._sendPrintJob()

                elif http_status_code == 401 or http_status_code == 403:
                    self._setOffline(
                        printer,
                        i18n_catalog.i18nc(
                            "@info:status",
                            "OctoPrint on {0} does not allow access to the job state",
                        ).format(self._id),
                    )
                    return

                elif http_status_code == 502 or http_status_code == 503:
                    Logger.log(
                        "w", "Received an error status code: %d", http_status_code
                    )
                    self._setOffline(
                        printer,
                        i18n_catalog.i18nc(
                            "@info:status", "OctoPrint on {0} is not running"
                        ).format(self._id),
                    )
                    return

                else:
                    pass  # See generic error handler below

            elif (
                self._api_prefix + "settings" in reply.url().toString()
            ):  # OctoPrint settings dump from /settings:
                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log(
                            "w", "Received invalid JSON from octoprint instance."
                        )
                        json_data = {}

                    self.parseSettingsData(json_data)

            elif (
                self._api_prefix + "version" in reply.url().toString()
            ):  # OctoPrint & API version
                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log(
                            "w", "Received invalid JSON from octoprint instance."
                        )
                        json_data = {}

                    if "server" in json_data:
                        self._octoprint_version = json_data["server"]
                        self.additionalDataChanged.emit()

                elif http_status_code == 404:
                    Logger.log("w", "Instance does not support reporting its version")
                    return

            elif (
                self._api_prefix + "files/" in reply.url().toString()
            ):  # Information about a file
                if http_status_code == 200:
                    if not self._waiting_for_analysis:
                        return

                    end_point = reply.url().toString().split(self._api_prefix, 1)[1]

                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log(
                            "w", "Received invalid JSON from octoprint instance."
                        )
                        json_data = {}

                    if (
                        "gcodeAnalysis" in json_data
                        and "progress" in json_data["gcodeAnalysis"]
                    ):
                        Logger.log(
                            "d", "PrintTimeGenius analysis of %s is done" % end_point
                        )

                        self._waiting_for_analysis = False

                        if self._waiting_message:
                            self._waiting_message.hide()
                            self._waiting_message = None

                        self._polling_end_points = [
                            point
                            for point in self._polling_end_points
                            if not point.startswith("files/")
                        ]

                        self._selectAndPrint(end_point)
                    else:
                        Logger.log(
                            "d",
                            "Still waiting for PrintTimeGenius analysis of %s"
                            % end_point,
                        )

        elif reply.operation() == QNetworkAccessManagerOperations.PostOperation:
            if (
                self._api_prefix + "files" in reply.url().toString()
            ):  # Result from /files command to start a print job:
                if http_status_code == 204:
                    Logger.log("d", "OctoPrint file command accepted")

                elif http_status_code == 401 or http_status_code == 403:
                    error_string = i18n_catalog.i18nc(
                        "@info:error",
                        "You are not allowed to start print jobs on OctoPrint with the configured API key.",
                    )
                    self._showErrorMessage(error_string)
                    return

                elif (
                    http_status_code == 404
                    and "files/sdcard/" in reply.url().toString()
                ):
                    Logger.log(
                        "d",
                        "OctoPrint reports an 404 not found error after uploading to SD card, but we ignore that",
                    )
                    return

                else:
                    pass  # See generic error handler below

            elif (
                self._api_prefix + "job" in reply.url().toString()
            ):  # Result from /job command (eg start/pause):
                if http_status_code == 204:
                    Logger.log("d", "OctoPrint job command accepted")

                elif http_status_code == 401 or http_status_code == 403:
                    error_string = i18n_catalog.i18nc(
                        "@info:error",
                        "You are not allowed to control print jobs on OctoPrint with the configured API key.",
                    )
                    self._showErrorMessage(error_string)
                    return

                else:
                    pass  # See generic error handler below

            elif (
                self._api_prefix + "printer/command" in reply.url().toString()
            ):  # Result from /printer/command (gcode statements):
                if http_status_code == 204:
                    Logger.log("d", "OctoPrint gcode command(s) accepted")

                elif http_status_code == 401 or http_status_code == 403:
                    error_string = i18n_catalog.i18nc(
                        "@info:error",
                        "You are not allowed to send gcode commands to OctoPrint with the configured API key.",
                    )
                    self._showErrorMessage(error_string)
                    return

                else:
                    pass  # See generic error handler below

            elif self._api_prefix + "login" in reply.url().toString():
                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log(
                            "w", "Received invalid JSON from octoprint instance."
                        )
                        json_data = {}

                    if "name" in json_data:
                        self._octoprint_user_name = json_data["name"]
                    else:
                        self._octoprint_user_name = i18n_catalog.i18nc(
                            "@label", "Anonymous user"
                        )
                    self.additionalDataChanged.emit()

                elif http_status_code == 404:
                    Logger.log("w", "Instance does not support user authorization")
                    self._octoprint_user_name = i18n_catalog.i18nc(
                        "@label", "Anonymous user"
                    )
                    self.additionalDataChanged.emit()
                    return

                elif http_status_code == 401 or http_status_code == 403:
                    self._octoprint_user_name = i18n_catalog.i18nc(
                        "@label", "Unknown user"
                    )
                    self.additionalDataChanged.emit()

                    error_string = i18n_catalog.i18nc(
                        "@info:error",
                        "You are not allowed to access to OctoPrint with the configured API key.",
                    )
                    self._showErrorMessage(error_string)
                    return

            elif (
                self._api_prefix + "connection/connect" in reply.url().toString()
            ):  # Result from /connection/connect command (eg start/pause):
                if http_status_code == 204:
                    Logger.log("d", "OctoPrint connection command accepted")

                elif http_status_code == 401 or http_status_code == 403:
                    error_string = i18n_catalog.i18nc(
                        "@info:error",
                        "You are not allowed to control printer connections on OctoPrint with the configured API key.",
                    )
                    self._showErrorMessage(error_string)
                    return

                else:
                    pass  # See generic error handler below

        else:
            Logger.log(
                "d",
                "OctoPrintOutputDevice got an unhandled operation %s",
                reply.operation(),
            )

        if http_status_code >= 400:
            if http_status_code == 401 or http_status_code == 403:
                error_string = i18n_catalog.i18nc(
                    "@info:error",
                    "You are not allowed to access OctoPrint with the configured API key.",
                )
            else:
                # Received another error reply
                if content_type == "text/plain":
                    error_string = bytes(reply.readAll()).decode("utf-8")
                    if not error_string:
                        error_string = reply.attribute(
                            QNetworkRequestAttributes.HttpReasonPhraseAttribute
                        )
                    error_string = error_string[:100]
                else:
                    error_string = i18n_catalog.i18nc(
                        "@info:error",
                        "OctoPrint responded with an unknown error",
                    )

            self._showErrorMessage(error_string)
            Logger.log(
                "e",
                "OctoPrintOutputDevice got an error while accessing %s",
                reply.url().toString(),
            )
            Logger.log("e", error_string)

    def _onUploadProgress(self, bytes_sent: int, bytes_total: int) -> None:
        if not self._progress_message:
            return

        if bytes_total > 0:
            # Treat upload progress as response. Uploading can take more than 10 seconds, so if we don't, we can get
            # timeout responses if this happens.
            self._last_response_time = time()

            progress = bytes_sent / bytes_total * 100
            previous_progress = self._progress_message.getProgress()
            if progress < 100:
                if previous_progress is not None and progress > previous_progress:
                    self._progress_message.setProgress(progress)
            else:
                self._progress_message.hide()
                self._progress_message = Message(
                    i18n_catalog.i18nc("@info:status", "Storing data on OctoPrint"),
                    0,
                    False,
                    -1,
                    title=i18n_catalog.i18nc("@label", "OctoPrint"),
                )
                self._progress_message.show()
        else:
            self._progress_message.setProgress(0)

    def _onUploadFinished(self, reply: QNetworkReply) -> None:
        reply.uploadProgress.disconnect(self._onUploadProgress)

        if self._progress_message:
            self._progress_message.hide()
            self._progress_message = None  # type:Optional[Message]

        http_status_code = reply.attribute(QNetworkRequestAttributes.HttpStatusCodeAttribute)
        error_string = ""
        content_type = bytes(reply.rawHeader(b"Content-Type")).decode("utf-8")

        if http_status_code == 401 or http_status_code == 403:
            error_string = i18n_catalog.i18nc(
                "@info:error",
                "You are not allowed to upload files to OctoPrint with the configured API key.",
            )

        elif http_status_code == 409:
            if "files/sdcard" in reply.url().toString():
                error_string = i18n_catalog.i18nc(
                    "@info:error", "Can't store a print job on SD card of the printer at this time."
                )
            else:
                error_string = i18n_catalog.i18nc(
                    "@info:error",
                    "Can't store the print job with the same name as the one that is currently printing.",
                )

        elif http_status_code >= 400:
            if content_type == "text/plain":
                error_string = bytes(reply.readAll()).decode("utf-8")
                if not error_string:
                    error_string = reply.attribute(
                        QNetworkRequestAttributes.HttpReasonPhraseAttribute
                    )
                error_string = error_string[:100]
            else:
                error_string = i18n_catalog.i18nc(
                    "@info:error",
                    "OctoPrint responded with an unknown error",
                )

        if error_string:
            self._showErrorMessage(error_string)
            Logger.log(
                "e",
                "OctoPrintOutputDevice got an %d error uploading to %s",
                http_status_code,
                reply.url().toString(),
            )
            Logger.log("e", error_string)
            return

        location_url = reply.header(QNetworkRequestKnownHeaders.LocationHeader)
        Logger.log(
            "d", "Resource created on OctoPrint instance: %s", location_url.toString()
        )

        end_point = location_url.toString().split(self._api_prefix, 1)[1]
        if self._transfer_as_ufp and end_point.endswith(".ufp"):
            if self._ufp_plugin_version < Version(
                "0.1.7"
            ):  # unfortunately, version 0.1.6 can not be detected
                # before 0.1.6, the plugin extracts gcode from *.ufp files as *.ufp.gcode
                end_point += ".gcode"
            else:
                # since 0.1.6, the plugin extracts gcode from *.ufp files as *.gcode
                end_point = end_point[:-3] + "gcode"

        if self._forced_queue or not self._upload_options.autoPrint:
            if location_url:
                location_path = "/".join(
                    end_point.split("/")[2:]
                )  # remove files/[local or sdcard]
                file_name = location_path + location_url.fileName()
                message = Message(
                    i18n_catalog.i18nc(
                        "@info:status", "Saved to OctoPrint as {0}"
                    ).format(file_name)
                )
            else:
                message = Message(
                    i18n_catalog.i18nc("@info:status", "Saved to OctoPrint")
                )
            message.setTitle(i18n_catalog.i18nc("@label", "OctoPrint"))
            message.addAction(
                "open_browser",
                i18n_catalog.i18nc("@action:button", "OctoPrint..."),
                "globe",
                i18n_catalog.i18nc("@info:tooltip", "Open the OctoPrint web interface"),
            )
            message.actionTriggered.connect(self._openOctoPrint)
            message.show()

            if self._upload_options.autoPrint or self._upload_options.autoSelect:
                self._selectAndPrint(end_point)
        elif (
            self._upload_options.autoPrint
            or self._upload_options.autoSelect
            or self._wait_for_analysis
        ):
            if not self._wait_for_analysis or not self._upload_options.autoPrint:
                if not self._select_and_print_handled_in_upload and (
                    self._upload_options.autoPrint or self._upload_options.autoSelect
                ):
                    self._selectAndPrint(end_point)
                return

            self._waiting_message = Message(
                i18n_catalog.i18nc(
                    "@info:status",
                    "Waiting for OctoPrint to complete G-code analysis...",
                ),
                title=i18n_catalog.i18nc("@label", "OctoPrint"),
                progress=-1,
                lifetime=0,
                dismissable=False,
                use_inactivity_timer=False,
            )
            self._waiting_message.addAction(
                "print",
                i18n_catalog.i18nc("@action:button", "Print now"),
                "",
                i18n_catalog.i18nc(
                    "@action:tooltip",
                    "Stop waiting for the G-code analysis and start printing immediately",
                ),
                button_style=Message.ActionButtonStyle.SECONDARY,
            )
            self._waiting_message.addAction(
                "cancel",
                i18n_catalog.i18nc("@action:button", "Cancel"),
                "",
                i18n_catalog.i18nc("@action:tooltip", "Abort the print job"),
            )
            self._waiting_message.actionTriggered.connect(self._stopWaitingForAnalysis)
            self._waiting_message.show()

            self._waiting_for_analysis = True
            self._polling_end_points.append(
                end_point
            )  # start polling the API for information about this file

    def parseSettingsData(self, json_data: Dict[str, Any]) -> None:
        self._store_on_sd_supported = False
        if "feature" in json_data and "sdSupport" in json_data["feature"]:
            self._store_on_sd_supported = json_data["feature"]["sdSupport"]

        webcam_data = []
        if "webcam" in json_data and "streamUrl" in json_data["webcam"]:
            webcam_data = [json_data["webcam"]]

        if "gcodeAnalysis" in json_data and "runAt" in json_data["gcodeAnalysis"]:
            self._gcode_analysis_requires_wait = (
                json_data["gcodeAnalysis"]["runAt"] == "idle"
            )

        if "plugins" in json_data:
            plugin_data = json_data["plugins"]
            self._power_plugins_manager.parsePluginData(plugin_data)

            if (
                "PrintTimeGenius" in plugin_data
                and "analyzers" in plugin_data["PrintTimeGenius"]
            ):
                for analyzer in plugin_data["PrintTimeGenius"]["analyzers"]:
                    if analyzer.get("enabled", False):
                        self._gcode_analysis_supported = True
                        Logger.log(
                            "d", "Instance needs time after uploading to analyse gcode"
                        )
                        break

                if not self._gcode_analysis_supported:
                    Logger.log(
                        "w",
                        "PrintTimeGenius is installed on the instance, but no analyzers are enabled",
                    )

            if "UltimakerFormatPackage" in plugin_data:
                self._ufp_transfer_supported = False
                try:
                    ufp_writer_plugin = PluginRegistry.getInstance().getPluginObject(
                        "UFPWriter"
                    )
                    self._ufp_transfer_supported = True
                    Logger.log(
                        "d", "Instance supports uploading .ufp instead of .gcode"
                    )
                except PluginNotFoundError:
                    Logger.log(
                        "w",
                        "Instance supports .ufp files but UFPWriter is not available",
                    )
                if self._ufp_transfer_supported:
                    try:
                        self._ufp_plugin_version = Version(
                            plugin_data["UltimakerFormatPackage"]["installed_version"]
                        )
                    except KeyError:
                        self._ufp_plugin_version = Version(0)
                        Logger.log(
                            "d",
                            "OctoPrint-UltimakerFormatPackage plugin version < 0.1.7",
                        )

            if "multicam" in plugin_data:
                webcam_data = plugin_data["multicam"]["multicam_profiles"]

        self._webcams_model.deserialise(webcam_data)

    def _createPrinterList(self) -> None:
        printer = PrinterOutputModel(
            output_controller=self._output_controller,
            number_of_extruders=self._number_of_extruders,
        )
        printer.updateName(self.name)
        self._printers = [printer]
        self.printersChanged.emit()

    def _selectAndPrint(self, end_point: str) -> None:
        command = {"command": "select"}  # type: Dict[str, Any]
        if self._upload_options.autoPrint and not self._forced_queue:
            command["print"] = True

        self._sendCommandToApi(end_point, command)

    def _setOffline(self, printer: PrinterOutputModel, reason: str = "") -> None:
        if not printer:
            Logger.log("e", "There is no active printer")
            return
        if printer.state != "offline":
            printer.updateState("offline")
            if printer.activePrintJob:
                printer.activePrintJob.updateState("offline")
            self.setConnectionText(reason)
            Logger.log("w", reason)

    def _showErrorMessage(self, error_string: str) -> None:
        if self._error_message:
            self._error_message.hide()
        self._error_message = Message(
            error_string, title=i18n_catalog.i18nc("@label", "OctoPrint error")
        )
        self._error_message.show()

    def _openOctoPrint(self, message: Message, action_id: str) -> None:
        QDesktopServices.openUrl(QUrl(self._base_url))

    def _createEmptyRequest(
        self, target: str, content_type: Optional[str] = "application/json"
    ) -> QNetworkRequest:
        request = QNetworkRequest(QUrl(self._api_url + target))
        try:
            request.setAttribute(QNetworkRequestAttributes.FollowRedirectsAttribute, True)
        except AttributeError:
            # in Qt6, this is no longer possible (or required), see https://doc.qt.io/qt-6/network-changes-qt6.html#redirect-policies
            pass

        request.setRawHeader(b"X-Api-Key", self._api_key)
        request.setRawHeader(b"User-Agent", self._user_agent.encode())

        if content_type is not None:
            request.setHeader(QNetworkRequestKnownHeaders.ContentTypeHeader, content_type)

        # ignore SSL errors (eg for self-signed certificates)
        ssl_configuration = QSslConfiguration.defaultConfiguration()
        ssl_configuration.setPeerVerifyMode(QSslSocketPeerVerifyModes.VerifyNone)
        request.setSslConfiguration(ssl_configuration)

        if self._basic_auth_data:
            request.setRawHeader(b"Authorization", self._basic_auth_data)

        return request

    # This is a patched version from NetworkedPrinterOutputdevice, which adds "form_data" instead of "form-data"
    def _createFormPart(
        self, content_header: str, data: bytes, content_type: Optional[str] = None
    ) -> QHttpPart:
        part = QHttpPart()

        if not content_header.startswith("form-data;"):
            content_header = "form-data; " + content_header
        part.setHeader(QNetworkRequestKnownHeaders.ContentDispositionHeader, content_header)
        if content_type is not None:
            part.setHeader(QNetworkRequestKnownHeaders.ContentTypeHeader, content_type)

        part.setBody(data)
        return part

    ## Overloaded from NetworkedPrinterOutputDevice.get() to be permissive of
    #  self-signed certificates
    def get(
        self, url: str, on_finished: Optional[Callable[[QNetworkReply], None]]
    ) -> None:
        self._validateManager()

        request = self._createEmptyRequest(url)
        self._last_request_time = time()

        if not self._manager:
            Logger.log(
                "e", "No network manager was created to execute the GET call with."
            )
            return

        reply = self._manager.get(request)
        self._registerOnFinishedCallback(reply, on_finished)

    ## Overloaded from NetworkedPrinterOutputDevice.post() to backport https://github.com/Ultimaker/Cura/pull/4678
    #  and allow self-signed certificates
    def post(
        self,
        url: str,
        data: Union[str, bytes],
        on_finished: Optional[Callable[[QNetworkReply], None]],
        on_progress: Optional[Callable[[int, int], None]] = None,
    ) -> None:
        self._validateManager()

        request = self._createEmptyRequest(url)
        self._last_request_time = time()

        if not self._manager:
            Logger.log("e", "Could not find manager.")
            return

        body = data if isinstance(data, bytes) else data.encode()  # type: bytes
        reply = self._manager.post(request, body)
        if on_progress is not None:
            reply.uploadProgress.connect(on_progress)
        self._registerOnFinishedCallback(reply, on_finished)
