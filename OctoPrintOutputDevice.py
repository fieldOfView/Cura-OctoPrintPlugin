# Copyright (c) 2019 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

from UM.i18n import i18nCatalog
from UM.Logger import Logger
from UM.Signal import signalemitter
from UM.Message import Message
from UM.Util import parseBool
from UM.Mesh.MeshWriter import MeshWriter
from UM.PluginRegistry import PluginRegistry

from cura.CuraApplication import CuraApplication

from cura.PrinterOutputDevice import PrinterOutputDevice, ConnectionState
from cura.PrinterOutput.NetworkedPrinterOutputDevice import NetworkedPrinterOutputDevice
from cura.PrinterOutput.PrinterOutputModel import PrinterOutputModel
from cura.PrinterOutput.PrintJobOutputModel import PrintJobOutputModel

from cura.PrinterOutput.GenericOutputController import GenericOutputController

from PyQt5.QtNetwork import QHttpMultiPart, QHttpPart, QNetworkRequest, QNetworkAccessManager, QNetworkReply
from PyQt5.QtCore import QUrl, QTimer, pyqtSignal, pyqtProperty, pyqtSlot, QCoreApplication
from PyQt5.QtGui import QImage, QDesktopServices

import json
import os.path
import re
from time import time
import base64
from io import StringIO
from enum import IntEnum

from typing import cast, Any, Callable, Dict, List, Optional, Union, TYPE_CHECKING
if TYPE_CHECKING:
    from UM.Scene.SceneNode import SceneNode #For typing.
    from UM.FileHandler.FileHandler import FileHandler #For typing.

i18n_catalog = i18nCatalog("cura")

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
        Closed = ConnectionState.closed          # type: ignore
        Connecting = ConnectionState.connecting  # type: ignore
        Connected = ConnectionState.connected    # type: ignore
        Busy = ConnectionState.busy              # type: ignore
        Error = ConnectionState.error            # type: ignore

##  OctoPrint connected (wifi / lan) printer using the OctoPrint API
@signalemitter
class OctoPrintOutputDevice(NetworkedPrinterOutputDevice):
    def __init__(self, instance_id: str, address: str, port: int, properties: dict, **kwargs) -> None:
        super().__init__(device_id = instance_id, address = address, properties = properties, **kwargs)

        self._address = address
        self._port = port
        self._path = properties.get(b"path", b"/").decode("utf-8")
        if self._path[-1:] != "/":
            self._path += "/"
        self._id = instance_id
        self._properties = properties  # Properties dict as provided by zero conf

        self._gcode_stream = StringIO()

        self._auto_print = True
        self._forced_queue = False

        # We start with a single extruder, but update this when we get data from octoprint
        self._number_of_extruders_set = False
        self._number_of_extruders = 1

        # Try to get version information from plugin.json
        plugin_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.json")
        try:
            with open(plugin_file_path) as plugin_file:
                plugin_info = json.load(plugin_file)
                plugin_version = plugin_info["version"]
        except:
            # The actual version info is not critical to have so we can continue
            plugin_version = "Unknown"
            Logger.logException("w", "Could not get version information for the plugin")

        self._user_agent_header = "User-Agent".encode()
        self._user_agent = ("%s/%s %s/%s" % (
            CuraApplication.getInstance().getApplicationName(),
            CuraApplication.getInstance().getVersion(),
            "OctoPrintPlugin",
            plugin_version
        )) # NetworkedPrinterOutputDevice defines this as string, so we encode this later

        self._api_prefix = "api/"
        self._api_header = "X-Api-Key".encode()
        self._api_key = b""

        self._protocol = "https" if properties.get(b'useHttps') == b"true" else "http"
        self._base_url = "%s://%s:%d%s" % (self._protocol, self._address, self._port, self._path)
        self._api_url = self._base_url + self._api_prefix

        self._basic_auth_header = "Authorization".encode()
        self._basic_auth_data = None
        basic_auth_username = properties.get(b"userName", b"").decode("utf-8")
        basic_auth_password = properties.get(b"password", b"").decode("utf-8")
        if basic_auth_username and basic_auth_password:
            data = base64.b64encode(("%s:%s" % (basic_auth_username, basic_auth_password)).encode()).decode("utf-8")
            self._basic_auth_data = ("basic %s" % data).encode()

        try:
            major_api_version = CuraApplication.getInstance().getAPIVersion().getMajor()
        except AttributeError:
            # UM.Application.getAPIVersion was added for API > 6 (Cura 4)
            # Since this plugin version is only compatible with Cura 3.5 and newer, it is safe to assume API 5
            major_api_version = 5

        if major_api_version <= 5:
            # In Cura 3.x, the monitor item only shows the camera stream
            self._monitor_view_qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MonitorItem3x.qml")
        else:
            # In Cura 4.x, the monitor item shows the camera stream as well as the monitor sidebar
            self._monitor_view_qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MonitorItem4x.qml")

        name = self._id
        matches = re.search(r"^\"(.*)\"\._octoprint\._tcp.local$", name)
        if matches:
            name = matches.group(1)

        self.setPriority(2) # Make sure the output device gets selected above local file output
        self.setName(name)
        self.setShortDescription(i18n_catalog.i18nc("@action:button", "Print with OctoPrint"))
        self.setDescription(i18n_catalog.i18nc("@properties:tooltip", "Print with OctoPrint"))
        self.setIconName("print")
        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connected to OctoPrint on {0}").format(self._id))

        self._post_reply = None

        self._progress_message = None # type: Union[None, Message]
        self._error_message = None # type: Union[None, Message]
        self._connection_message = None # type: Union[None, Message]

        self._queued_gcode_commands = [] # type: List[str]
        self._queued_gcode_timer = QTimer()
        self._queued_gcode_timer.setInterval(0)
        self._queued_gcode_timer.setSingleShot(True)
        self._queued_gcode_timer.timeout.connect(self._sendQueuedGcode)

        # TODO; Add preference for update intervals
        self._update_fast_interval = 2000
        self._update_slow_interval = 10000
        self._update_timer = QTimer()
        self._update_timer.setInterval(self._update_fast_interval)
        self._update_timer.setSingleShot(False)
        self._update_timer.timeout.connect(self._update)

        self._show_camera = False
        self._camera_mirror = False
        self._camera_rotation = 0
        self._camera_url = ""
        self._camera_shares_proxy = False

        self._sd_supported = False

        self._plugin_data = {} #type: Dict[str, Any]

        self._output_controller = GenericOutputController(self)

    def getProperties(self) -> Dict[bytes, bytes]:
        return self._properties

    @pyqtSlot(str, result = str)
    def getProperty(self, key: str) -> str:
        key_b = key.encode("utf-8")
        if key_b in self._properties:
            return self._properties.get(key_b, b"").decode("utf-8")
        else:
            return ""

    ##  Get the unique key of this machine
    #   \return key String containing the key of the machine.
    @pyqtSlot(result = str)
    def getId(self) -> str:
        return self._id

    ##  Set the API key of this OctoPrint instance
    def setApiKey(self, api_key: str) -> None:
        self._api_key = api_key.encode()

    ##  Name of the instance (as returned from the zeroConf properties)
    @pyqtProperty(str, constant = True)
    def name(self) -> str:
        return self._name

    ##  Version (as returned from the zeroConf properties)
    @pyqtProperty(str, constant=True)
    def octoprintVersion(self) -> str:
        return self._properties.get(b"version", b"").decode("utf-8")

    ## IPadress of this instance
    @pyqtProperty(str, constant=True)
    def ipAddress(self) -> str:
        return self._address

    ## IPadress of this instance
    #  Overridden from NetworkedPrinterOutputDevice because OctoPrint does not
    #  send the ip address with zeroconf
    @pyqtProperty(str, constant=True)
    def address(self) -> str:
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

    cameraOrientationChanged = pyqtSignal()

    @pyqtProperty("QVariantMap", notify = cameraOrientationChanged)
    def cameraOrientation(self) -> Dict[str, Any]:
        return {
            "mirror": self._camera_mirror,
            "rotation": self._camera_rotation,
        }

    cameraUrlChanged = pyqtSignal()

    @pyqtProperty("QUrl", notify = cameraUrlChanged)
    def cameraUrl(self) -> QUrl:
        return QUrl(self._camera_url)

    def setShowCamera(self, show_camera: bool) -> None:
        if show_camera != self._show_camera:
            self._show_camera = show_camera
            self.showCameraChanged.emit()

    showCameraChanged = pyqtSignal()

    @pyqtProperty(bool, notify = showCameraChanged)
    def showCamera(self) -> bool:
        return self._show_camera

    def _update(self) -> None:
        ## Request 'general' printer data
        self.get("printer", self._onRequestFinished)

        ## Request print_job data
        self.get("job", self._onRequestFinished)

    def _createEmptyRequest(self, target: str, content_type: Optional[str] = "application/json") -> QNetworkRequest:
        request = QNetworkRequest(QUrl(self._api_url + target))
        request.setRawHeader(self._user_agent_header, self._user_agent.encode())
        request.setRawHeader(self._api_header, self._api_key)
        if content_type is not None:
            request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")
        if self._basic_auth_data:
            request.setRawHeader(self._basic_auth_header, self._basic_auth_data)
        return request

    def close(self) -> None:
        self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Closed))
        if self._progress_message:
            self._progress_message.hide()
        if self._error_message:
            self._error_message.hide()
        self._update_timer.stop()

    ##  Start requesting data from the instance
    def connect(self) -> None:
        self._createNetworkManager()

        self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Connecting))
        self._update()  # Manually trigger the first update, as we don't want to wait a few secs before it starts.

        Logger.log("d", "Connection with instance %s with url %s started", self._id, self._base_url)
        self._update_timer.start()

        self._last_response_time = None
        self._setAcceptsCommands(False)
        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connecting to OctoPrint on {0}").format(self._id))

        ## Request 'settings' dump
        self.get("settings", self._onRequestFinished)

    ##  Stop requesting data from the instance
    def disconnect(self) -> None:
        Logger.log("d", "Connection with instance %s with url %s stopped", self._id, self._base_url)
        self.close()

    def pausePrint(self) -> None:
        self._sendJobCommand("pause")

    def resumePrint(self) -> None:
        if not self._printers[0].activePrintJob:
            return

        if self._printers[0].activePrintJob.state == "paused":
            self._sendJobCommand("pause")
        else:
            self._sendJobCommand("start")

    def cancelPrint(self) -> None:
        self._sendJobCommand("cancel")

    def requestWrite(self, nodes: List["SceneNode"], file_name: Optional[str] = None, limit_mimetypes: bool = False, file_handler: Optional["FileHandler"] = None, **kwargs: str) -> None:
        global_container_stack = CuraApplication.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        # Make sure post-processing plugin are run on the gcode
        self.writeStarted.emit(self)

        # Get the g-code through the GCodeWriter plugin
        # This produces the same output as "Save to File", adding the print settings to the bottom of the file
        gcode_writer = cast(MeshWriter, PluginRegistry.getInstance().getPluginObject("GCodeWriter"))
        self._gcode_stream = StringIO()
        if not gcode_writer.write(self._gcode_stream, None):
            Logger.log("e", "GCodeWrite failed: %s" % gcode_writer.getInformation())
            return

        if self._error_message:
            self._error_message.hide()
            self._error_message = None

        if self._progress_message:
            self._progress_message.hide()
            self._progress_message = None

        self._auto_print = parseBool(global_container_stack.getMetaDataEntry("octoprint_auto_print", True))
        self._forced_queue = False

        if self.activePrinter.state not in ["idle", ""]:
            Logger.log("d", "Tried starting a print, but current state is %s" % self.activePrinter.state)
            if not self._auto_print:
                # Allow queueing the job even if OctoPrint is currently busy if autoprinting is disabled
                self._error_message = None
            elif self.activePrinter.state == "offline":
                self._error_message = Message(i18n_catalog.i18nc("@info:status", "The printer is offline. Unable to start a new job."))
            else:
                self._error_message = Message(i18n_catalog.i18nc("@info:status", "OctoPrint is busy. Unable to start a new job."))

            if self._error_message:
                self._error_message.addAction("Queue", i18n_catalog.i18nc("@action:button", "Queue job"), "", i18n_catalog.i18nc("@action:tooltip", "Queue this print job so it can be printed later"))
                self._error_message.actionTriggered.connect(self._queuePrint)
                self._error_message.show()
                return

        self._startPrint()

    def _queuePrint(self, message_id: Optional[str] = None, action_id: Optional[str] = None) -> None:
        if self._error_message:
            self._error_message.hide()
        self._forced_queue = True
        self._startPrint()

    def _startPrint(self) -> None:
        global_container_stack = CuraApplication.getInstance().getGlobalContainerStack()
        if not global_container_stack:
            return

        if self._auto_print and not self._forced_queue:
            CuraApplication.getInstance().getController().setActiveStage("MonitorStage")

            # cancel any ongoing preheat timer before starting a print
            try:
                self._printers[0].stopPreheatTimers()
            except AttributeError:
                # stopPreheatTimers was added after Cura 3.3 beta
                pass

        self._progress_message = Message(i18n_catalog.i18nc("@info:status", "Sending data to OctoPrint"), 0, False, -1)
        self._progress_message.addAction("Cancel", i18n_catalog.i18nc("@action:button", "Cancel"), "", "")
        self._progress_message.actionTriggered.connect(self._cancelSendGcode)
        self._progress_message.show()

        job_name = CuraApplication.getInstance().getPrintInformation().jobName.strip()
        if job_name is "":
            job_name = "untitled_print"
        file_name = "%s.gcode" % job_name

        ##  Create multi_part request
        post_parts = [] # type: List[QHttpPart]

        ##  Create parts (to be placed inside multipart)
        post_part = QHttpPart()
        post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"select\"")
        post_part.setBody(b"true")
        post_parts.append(post_part)

        if self._auto_print and not self._forced_queue:
            post_part = QHttpPart()
            post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"print\"")
            post_part.setBody(b"true")
            post_parts.append(post_part)

        post_part = QHttpPart()
        post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"file\"; filename=\"%s\"" % file_name)
        post_part.setBody(self._gcode_stream.getvalue().encode())
        post_parts.append(post_part)

        destination = "local"
        if self._sd_supported and parseBool(global_container_stack.getMetaDataEntry("octoprint_store_sd", False)):
            destination = "sdcard"

        try:
            ##  Post request + data
            post_request = self._createEmptyRequest("files/" + destination)
            self._post_reply = self.postFormWithParts("files/" + destination, post_parts, on_finished=self._onRequestFinished, on_progress=self._onUploadProgress)

        except IOError:
            self._progress_message.hide()
            self._error_message = Message(i18n_catalog.i18nc("@info:status", "Unable to send data to OctoPrint."))
            self._error_message.show()
        except Exception as e:
            self._progress_message.hide()
            Logger.log("e", "An exception occurred in network connection: %s" % str(e))

        self._gcode_stream = StringIO()

    def _cancelSendGcode(self, message_id: Optional[str] = None, action_id: Optional[str] = None) -> None:
        if self._post_reply:
            Logger.log("d", "Stopping upload because the user pressed cancel.")
            try:
                self._post_reply.uploadProgress.disconnect(self._onUploadProgress)
            except TypeError:
                pass  # The disconnection can fail on mac in some cases. Ignore that.

            self._post_reply.abort()
            self._post_reply = None
        if self._progress_message:
            self._progress_message.hide()

    def sendCommand(self, command: str) -> None:
        self._queued_gcode_commands.append(command)
        self._queued_gcode_timer.start()

    # Send gcode commands that are queued in quick succession as a single batch
    def _sendQueuedGcode(self) -> None:
        if self._queued_gcode_commands:
            self._sendCommandToApi("printer/command", self._queued_gcode_commands)
            Logger.log("d", "Sent gcode command to OctoPrint instance: %s", self._queued_gcode_commands)
            self._queued_gcode_commands = [] # type: List[str]

    def _sendJobCommand(self, command: str) -> None:
        self._sendCommandToApi("job", command)
        Logger.log("d", "Sent job command to OctoPrint instance: %s", command)

    def _sendCommandToApi(self, end_point: str, commands: Union[str, List[str]]) -> None:
        if isinstance(commands, list):
            data = json.dumps({"commands": commands})
        else:
            data = json.dumps({"command": commands})
        self.post(end_point, data, self._onRequestFinished)

    ## Overloaded from NetworkedPrinterOutputDevice.post() to backport https://github.com/Ultimaker/Cura/pull/4678
    def post(self, url: str, data: Union[str, bytes],
             on_finished: Optional[Callable[[QNetworkReply], None]],
             on_progress: Optional[Callable[[int, int], None]] = None) -> None:
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

    ##  Handler for all requests that have finished.
    def _onRequestFinished(self, reply: QNetworkReply) -> None:
        if reply.error() == QNetworkReply.TimeoutError:
            Logger.log("w", "Received a timeout on a request to the instance")
            self._connection_state_before_timeout = self._connection_state
            self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Error))
            return

        if self._connection_state_before_timeout and reply.error() == QNetworkReply.NoError:  #  There was a timeout, but we got a correct answer again.
            if self._last_response_time:
                Logger.log("d", "We got a response from the instance after %s of silence", time() - self._last_response_time)
            self.setConnectionState(self._connection_state_before_timeout)
            self._connection_state_before_timeout = None

        if reply.error() == QNetworkReply.NoError:
            self._last_response_time = time()

        http_status_code = reply.attribute(QNetworkRequest.HttpStatusCodeAttribute)
        if not http_status_code:
            # Received no or empty reply
            return

        error_handled = False

        if reply.operation() == QNetworkAccessManager.GetOperation:
            if self._api_prefix + "printer" in reply.url().toString():  # Status update from /printer.
                if not self._printers:
                    self._createPrinterList()

                # An OctoPrint instance has a single printer.
                printer = self._printers[0]
                update_pace = self._update_slow_interval

                if http_status_code == 200:
                    update_pace = self._update_fast_interval

                    if not self.acceptsCommands:
                        self._setAcceptsCommands(True)
                        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connected to OctoPrint on {0}").format(self._id))

                    if self._connection_state == UnifiedConnectionState.Connecting:
                        self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Connected))
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from octoprint instance.")
                        json_data = {}

                    if "temperature" in json_data:
                        if not self._number_of_extruders_set:
                            self._number_of_extruders = 0
                            while "tool%d" % self._number_of_extruders in json_data["temperature"]:
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
                                hotend_temperatures = json_data["temperature"]["tool%d" % index]
                                extruder.updateTargetHotendTemperature(hotend_temperatures["target"])
                                extruder.updateHotendTemperature(hotend_temperatures["actual"])
                            else:
                                extruder.updateTargetHotendTemperature(0)
                                extruder.updateHotendTemperature(0)

                        if "bed" in json_data["temperature"]:
                            bed_temperatures = json_data["temperature"]["bed"]
                            actual_temperature = bed_temperatures["actual"] if bed_temperatures["actual"] is not None else -1
                            printer.updateBedTemperature(actual_temperature)
                            target_temperature = bed_temperatures["target"] if bed_temperatures["target"] is not None else -1
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
                    printer.updateState(printer_state)

                elif http_status_code == 401:
                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    self.setConnectionText(i18n_catalog.i18nc("@info:status", "OctoPrint on {0} does not allow access to print").format(self._id))
                    error_handled = True

                elif http_status_code == 409:
                    if self._connection_state == UnifiedConnectionState.Connecting:
                        self.setConnectionState(cast(ConnectionState, UnifiedConnectionState.Connected))

                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    self.setConnectionText(i18n_catalog.i18nc("@info:status", "The printer connected to OctoPrint on {0} is not operational").format(self._id))
                    error_handled = True

                elif http_status_code == 502 or http_status_code == 503:
                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    self.setConnectionText(i18n_catalog.i18nc("@info:status", "OctoPrint on {0} is not running").format(self._id))
                    error_handled = True

                else:
                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    Logger.log("w", "Received an unexpected returncode: %d", http_status_code)

                if update_pace != self._update_timer.interval():
                    self._update_timer.setInterval(update_pace)

            elif self._api_prefix + "job" in reply.url().toString():  # Status update from /job:
                if not self._printers:
                    return  # Ignore the data for now, we don't have info about a printer yet.
                printer = self._printers[0]

                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from octoprint instance.")
                        json_data = {}

                    if printer.activePrintJob is None:
                        print_job = PrintJobOutputModel(output_controller=self._output_controller)
                        printer.updateActivePrintJob(print_job)
                    else:
                        print_job = printer.activePrintJob

                    print_job_state = "offline"
                    if "state" in json_data:
                        if json_data["state"] == "Error":
                            print_job_state = "error"
                        elif json_data["state"] == "Pausing":
                            print_job_state = "pausing"
                        elif json_data["state"] == "Paused":
                            print_job_state = "paused"
                        elif json_data["state"] == "Printing":
                            print_job_state = "printing"
                        elif json_data["state"] == "Cancelling":
                            print_job_state = "abort"
                        elif json_data["state"] == "Operational":
                            print_job_state = "ready"
                            printer.updateState("idle")
                    print_job.updateState(print_job_state)

                    print_time = json_data["progress"]["printTime"]
                    if print_time:
                        print_job.updateTimeElapsed(print_time)
                        if json_data["progress"]["completion"]: # not 0 or None or ""
                            print_job.updateTimeTotal(print_time / (json_data["progress"]["completion"] / 100))
                        else:
                            print_job.updateTimeTotal(0)
                    else:
                        print_job.updateTimeElapsed(0)
                        print_job.updateTimeTotal(0)

                    print_job.updateName(json_data["job"]["file"]["name"])
                else:
                    pass  # See generic error handler below

            elif self._api_prefix + "settings" in reply.url().toString():  # OctoPrint settings dump from /settings:
                if http_status_code == 200:
                    try:
                        json_data = json.loads(bytes(reply.readAll()).decode("utf-8"))
                    except json.decoder.JSONDecodeError:
                        Logger.log("w", "Received invalid JSON from octoprint instance.")
                        json_data = {}

                    if "feature" in json_data and "sdSupport" in json_data["feature"]:
                        self._sd_supported = json_data["feature"]["sdSupport"]

                    if "webcam" in json_data and "streamUrl" in json_data["webcam"]:
                        self._camera_shares_proxy = False
                        stream_url = json_data["webcam"]["streamUrl"]
                        if not stream_url: #empty string or None
                            self._camera_url = ""
                        elif stream_url[:4].lower() == "http": # absolute uri
                            self._camera_url = stream_url
                        elif stream_url[:2] == "//": # protocol-relative
                            self._camera_url = "%s:%s" % (self._protocol, stream_url)
                        elif stream_url[:1] == ":": # domain-relative (on another port)
                            self._camera_url = "%s://%s%s" % (self._protocol, self._address, stream_url)
                        elif stream_url[:1] == "/": # domain-relative (on same port)
                            self._camera_url = "%s://%s:%d%s" % (self._protocol, self._address, self._port, stream_url)
                            self._camera_shares_proxy = True
                        else:
                            Logger.log("w", "Unusable stream url received: %s", stream_url)
                            self._camera_url = ""

                        Logger.log("d", "Set OctoPrint camera url to %s", self._camera_url)
                        self.cameraUrlChanged.emit()

                        if "rotate90" in json_data["webcam"]:
                            self._camera_rotation = -90 if json_data["webcam"]["rotate90"] else 0
                            if json_data["webcam"]["flipH"] and json_data["webcam"]["flipV"]:
                                self._camera_mirror = False
                                self._camera_rotation += 180
                            elif json_data["webcam"]["flipH"]:
                                self._camera_mirror = True
                                self._camera_rotation += 180
                            elif json_data["webcam"]["flipV"]:
                                self._camera_mirror = True
                            else:
                                self._camera_mirror = False
                            self.cameraOrientationChanged.emit()

                    if "plugins" in json_data:
                        self._plugin_data = json_data["plugins"]

        elif reply.operation() == QNetworkAccessManager.PostOperation:
            if self._api_prefix + "files" in reply.url().toString():  # Result from /files command:
                if http_status_code == 201:
                    Logger.log("d", "Resource created on OctoPrint instance: %s", reply.header(QNetworkRequest.LocationHeader).toString())
                else:
                    pass  # See generic error handler below

                reply.uploadProgress.disconnect(self._onUploadProgress)
                if self._progress_message:
                    self._progress_message.hide()

                if self._forced_queue or not self._auto_print:
                    location = reply.header(QNetworkRequest.LocationHeader)
                    if location:
                        file_name = QUrl(reply.header(QNetworkRequest.LocationHeader).toString()).fileName()
                        message = Message(i18n_catalog.i18nc("@info:status", "Saved to OctoPrint as {0}").format(file_name))
                    else:
                        message = Message(i18n_catalog.i18nc("@info:status", "Saved to OctoPrint"))
                    message.addAction("open_browser", i18n_catalog.i18nc("@action:button", "OctoPrint..."), "globe",
                                        i18n_catalog.i18nc("@info:tooltip", "Open the OctoPrint web interface"))
                    message.actionTriggered.connect(self._openOctoPrint)
                    message.show()

            elif self._api_prefix + "job" in reply.url().toString():  # Result from /job command (eg start/pause):
                if http_status_code == 204:
                    Logger.log("d", "Octoprint job command accepted")
                else:
                    pass  # See generic error handler below

            elif self._api_prefix + "printer/command" in reply.url().toString():  # Result from /printer/command (gcode statements):
                if http_status_code == 204:
                    Logger.log("d", "Octoprint gcode command(s) accepted")
                else:
                    pass  # See generic error handler below

        else:
            Logger.log("d", "OctoPrintOutputDevice got an unhandled operation %s", reply.operation())

        if not error_handled and http_status_code >= 400:
            # Received an error reply
            error_string = bytes(reply.readAll()).decode("utf-8")
            if not error_string:
                error_string = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute)
            if self._error_message:
                self._error_message.hide()
            self._error_message = Message(error_string, title=i18n_catalog.i18nc("@label", "OctoPrint error"))
            self._error_message.show()
            return

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
                self._progress_message = Message(i18n_catalog.i18nc("@info:status", "Storing data on OctoPrint"), 0, False, -1)
                self._progress_message.show()
        else:
            self._progress_message.setProgress(0)

    def _createPrinterList(self) -> None:
        printer = PrinterOutputModel(output_controller=self._output_controller, number_of_extruders=self._number_of_extruders)
        printer.updateName(self.name)
        self._printers = [printer]
        self.printersChanged.emit()

    def _openOctoPrint(self, message_id: Optional[str] = None, action_id: Optional[str] = None) -> None:
        QDesktopServices.openUrl(QUrl(self._base_url))
