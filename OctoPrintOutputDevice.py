from UM.i18n import i18nCatalog
from UM.Application import Application
from UM.Logger import Logger
from UM.Signal import signalemitter
from UM.Message import Message
from UM.Util import parseBool

from cura.PrinterOutputDevice import PrinterOutputDevice, ConnectionState
from cura.PrinterOutput.NetworkedPrinterOutputDevice import NetworkedPrinterOutputDevice
from cura.PrinterOutput.PrinterOutputModel import PrinterOutputModel
from cura.PrinterOutput.PrintJobOutputModel import PrintJobOutputModel
from cura.PrinterOutput.NetworkCamera import NetworkCamera

from cura.PrinterOutput.GenericOutputController import GenericOutputController

from PyQt5.QtNetwork import QHttpMultiPart, QHttpPart, QNetworkRequest, QNetworkAccessManager, QNetworkReply
from PyQt5.QtCore import QUrl, QTimer, pyqtSignal, pyqtProperty, pyqtSlot, QCoreApplication
from PyQt5.QtGui import QImage, QDesktopServices

import json
import os.path
import re
from time import time
import base64
from typing import Any, Dict, List

i18n_catalog = i18nCatalog("cura")


##  OctoPrint connected (wifi / lan) printer using the OctoPrint API
@signalemitter
class OctoPrintOutputDevice(NetworkedPrinterOutputDevice):
    def __init__(self, instance_id: str, address: str, port: int, properties: dict, parent = None) -> None:
        super().__init__(device_id = instance_id, address = address, properties = properties, parent = parent)

        self._address = address
        self._port = port
        self._path = properties.get(b"path", b"/").decode("utf-8")
        if self._path[-1:] != "/":
            self._path += "/"
        self._id = instance_id
        self._properties = properties  # Properties dict as provided by zero conf

        self._gcode = []
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
            Application.getInstance().getApplicationName(),
            Application.getInstance().getVersion(),
            "OctoPrintPlugin",
            Application.getInstance().getVersion()
        )) # NetworkedPrinterOutputDevice defines this as string, so we encode this later

        self._api_prefix = "api/"
        self._api_header = "X-Api-Key".encode()
        self._api_key = None

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

        self._monitor_view_qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "MonitorItem.qml")

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

        #   QNetwork manager needs to be created in advance. If we don't it can happen that it doesn't correctly
        #   hook itself into the event loop, which results in events never being fired / done.
        self._manager = QNetworkAccessManager()
        self._manager.finished.connect(self._onRequestFinished)

        ##  Ensure that the qt networking stuff isn't garbage collected (unless we want it to)
        self._settings_reply = None
        self._printer_reply = None
        self._job_reply = None
        self._command_reply = None

        self._post_reply = None
        self._post_multi_part = None

        self._progress_message = None
        self._error_message = None
        self._connection_message = None

        self._queued_gcode_commands = [] # type: List[str]
        self._queued_gcode_timer = QTimer()
        self._queued_gcode_timer.setInterval(0)
        self._queued_gcode_timer.setSingleShot(True)
        self._queued_gcode_timer.timeout.connect(self._sendQueuedGcode)

        self._update_timer = QTimer()
        self._update_timer.setInterval(2000)  # TODO; Add preference for update interval
        self._update_timer.setSingleShot(False)
        self._update_timer.timeout.connect(self._update)

        self._camera_mirror = ""
        self._camera_rotation = 0
        self._camera_url = ""
        self._camera_shares_proxy = False

        self._sd_supported = False

        self._plugin_data = {} #type: Dict[str, Any]

        self._connection_state_before_timeout = None

        self._last_response_time = None
        self._last_request_time = None
        self._response_timeout_time = 5
        self._recreate_network_manager_time = 30 # If we have no connection, re-create network manager every 30 sec.
        self._recreate_network_manager_count = 1

        self._output_controller = GenericOutputController(self)

    def getProperties(self):
        return self._properties

    @pyqtSlot(str, result = str)
    def getProperty(self, key):
        key = key.encode("utf-8")
        if key in self._properties:
            return self._properties.get(key, b"").decode("utf-8")
        else:
            return ""

    ##  Get the unique key of this machine
    #   \return key String containing the key of the machine.
    @pyqtSlot(result = str)
    def getId(self):
        return self._id

    ##  Set the API key of this OctoPrint instance
    def setApiKey(self, api_key):
        self._api_key = api_key.encode()

    ##  Name of the instance (as returned from the zeroConf properties)
    @pyqtProperty(str, constant = True)
    def name(self):
        return self._name

    ##  Version (as returned from the zeroConf properties)
    @pyqtProperty(str, constant=True)
    def octoprintVersion(self):
        return self._properties.get(b"version", b"").decode("utf-8")

    ## IPadress of this instance
    @pyqtProperty(str, constant=True)
    def ipAddress(self):
        return self._address

    ## IPadress of this instance
    #  Overridden from NetworkedPrinterOutputDevice because OctoPrint does not
    #  send the ip address with zeroconf
    @pyqtProperty(str, constant=True)
    def address(self):
        return self._address

    ## port of this instance
    @pyqtProperty(int, constant=True)
    def port(self):
        return self._port

    ## path of this instance
    @pyqtProperty(str, constant=True)
    def path(self):
        return self._path

    ## absolute url of this instance
    @pyqtProperty(str, constant=True)
    def baseURL(self):
        return self._base_url

    cameraOrientationChanged = pyqtSignal()

    @pyqtProperty("QVariantMap", notify = cameraOrientationChanged)
    def cameraOrientation(self):
        return {
            "mirror": self._camera_mirror,
            "rotation": self._camera_rotation,
        }

    def _update(self):
        if self._last_response_time:
            time_since_last_response = time() - self._last_response_time
        else:
            time_since_last_response = 0
        if self._last_request_time:
            time_since_last_request = time() - self._last_request_time
        else:
            time_since_last_request = float("inf") # An irrelevantly large number of seconds

        # Connection is in timeout, check if we need to re-start the connection.
        # Sometimes the qNetwork manager incorrectly reports the network status on Mac & Windows.
        # Re-creating the QNetworkManager seems to fix this issue.
        if self._last_response_time and self._connection_state_before_timeout:
            if time_since_last_response > self._recreate_network_manager_time * self._recreate_network_manager_count:
                self._recreate_network_manager_count += 1
                # It can happen that we had a very long timeout (multiple times the recreate time).
                # In that case we should jump through the point that the next update won't be right away.
                while time_since_last_response - self._recreate_network_manager_time * self._recreate_network_manager_count > self._recreate_network_manager_time:
                    self._recreate_network_manager_count += 1
                Logger.log("d", "Timeout lasted over 30 seconds (%.1fs), re-checking connection.", time_since_last_response)
                self._createNetworkManager()
                return

        # Check if we have an connection in the first place.
        if not self._manager.networkAccessible():
            if not self._connection_state_before_timeout:
                Logger.log("d", "The network connection seems to be disabled. Going into timeout mode")
                self._connection_state_before_timeout = self._connection_state
                self.setConnectionState(ConnectionState.error)
                self._connection_message = Message(i18n_catalog.i18nc("@info:status",
                                                                      "The connection with the network was lost."))
                self._connection_message.show()
                # Check if we were uploading something. Abort if this is the case.
                # Some operating systems handle this themselves, others give weird issues.
                try:
                    if self._post_reply:
                        Logger.log("d", "Stopping post upload because the connection was lost.")
                        try:
                            self._post_reply.uploadProgress.disconnect(self._onUploadProgress)
                        except TypeError:
                            pass  # The disconnection can fail on mac in some cases. Ignore that.

                        self._post_reply.abort()
                        self._progress_message.hide()
                except RuntimeError:
                    self._post_reply = None  # It can happen that the wrapped c++ object is already deleted.
            return
        else:
            if not self._connection_state_before_timeout:
                self._recreate_network_manager_count = 1

        # Check that we aren't in a timeout state
        if self._last_response_time and self._last_request_time and not self._connection_state_before_timeout:
            if time_since_last_response > self._response_timeout_time and time_since_last_request <= self._response_timeout_time:
                # Go into timeout state.
                Logger.log("d", "We did not receive a response for %s seconds, so it seems OctoPrint is no longer accesible.", time() - self._last_response_time)
                self._connection_state_before_timeout = self._connection_state
                self._connection_message = Message(i18n_catalog.i18nc("@info:status", "The connection with OctoPrint was lost. Check your network-connections."))
                self._connection_message.show()
                self.setConnectionState(ConnectionState.error)

        ## Request 'general' printer data
        self._printer_reply = self._manager.get(self._createApiRequest("printer"))

        ## Request print_job data
        self._job_reply = self._manager.get(self._createApiRequest("job"))

    def _createNetworkManager(self):
        if self._manager:
            self._manager.finished.disconnect(self._onRequestFinished)

        self._manager = QNetworkAccessManager()
        self._manager.finished.connect(self._onRequestFinished)

    def _createApiRequest(self, end_point):
        request = QNetworkRequest(QUrl(self._api_url + end_point))
        request.setRawHeader(self._user_agent_header, self._user_agent.encode())
        request.setRawHeader(self._api_header, self._api_key)
        if self._basic_auth_data:
            request.setRawHeader(self._basic_auth_header, self._basic_auth_data)
        return request

    def close(self):
        self.setConnectionState(ConnectionState.closed)
        if self._progress_message:
            self._progress_message.hide()
        if self._error_message:
            self._error_message.hide()
        self._update_timer.stop()

    def requestWrite(self, node, file_name = None, filter_by_machine = False, file_handler = None, **kwargs):
        self.writeStarted.emit(self)

        active_build_plate = Application.getInstance().getMultiBuildPlateModel().activeBuildPlate
        scene = Application.getInstance().getController().getScene()
        gcode_dict = getattr(scene, "gcode_dict", None)
        if not gcode_dict:
            return
        self._gcode = gcode_dict.get(active_build_plate, None)

        self.startPrint()

    ##  Start requesting data from the instance
    def connect(self):
        self._createNetworkManager()

        self.setConnectionState(ConnectionState.connecting)
        self._update()  # Manually trigger the first update, as we don't want to wait a few secs before it starts.
        Logger.log("d", "Connection with instance %s with url %s started", self._id, self._base_url)
        self._update_timer.start()

        self._last_response_time = None
        self._setAcceptsCommands(False)
        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connecting to OctoPrint on {0}").format(self._id))

        ## Request 'settings' dump
        self._settings_reply = self._manager.get(self._createApiRequest("settings"))

    ##  Stop requesting data from the instance
    def disconnect(self):
        Logger.log("d", "Connection with instance %s with url %s stopped", self._id, self._base_url)
        self.close()

    def pausePrint(self):
        self._sendJobCommand("pause")

    def resumePrint(self):
        if not self._printers[0].activePrintJob:
            return

        if self._printers[0].activePrintJob.state == "paused":
            self._sendJobCommand("pause")
        else:
            self._sendJobCommand("start")

    def cancelPrint(self):
        self._sendJobCommand("cancel")

    def startPrint(self):
        global_container_stack = Application.getInstance().getGlobalContainerStack()
        if not global_container_stack:
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
                # allow queueing the job even if OctoPrint is currently busy if autoprinting is disabled
                self._error_message = None
            elif self.activePrinter.state == "offline":
                self._error_message = Message(i18n_catalog.i18nc("@info:status", "The printer is offline. Unable to start a new job."))
            else:
                self._error_message = Message(i18n_catalog.i18nc("@info:status", "OctoPrint is busy. Unable to start a new job."))

            if self._error_message:
                self._error_message.addAction("Queue", i18n_catalog.i18nc("@action:button", "Queue job"), None, i18n_catalog.i18nc("@action:tooltip", "Queue this print job so it can be printed later"))
                self._error_message.actionTriggered.connect(self._queuePrint)
                self._error_message.show()
                return

        self._startPrint()

    def _queuePrint(self, message_id, action_id):
        if self._error_message:
            self._error_message.hide()
        self._forced_queue = True
        self._startPrint()

    def _startPrint(self):
        if self._auto_print and not self._forced_queue:
            Application.getInstance().getController().setActiveStage("MonitorStage")

            # cancel any ongoing preheat timer before starting a print
            try:
                self._printers[0].stopPreheatTimers()
            except AttributeError:
                # stopPreheatTimers was added after Cura 3.3 beta
                pass

        self._progress_message = Message(i18n_catalog.i18nc("@info:status", "Sending data to OctoPrint"), 0, False, -1)
        self._progress_message.addAction("Cancel", i18n_catalog.i18nc("@action:button", "Cancel"), None, "")
        self._progress_message.actionTriggered.connect(self._cancelSendGcode)
        self._progress_message.show()

        ## Mash the data into single string
        single_string_file_data = ""
        last_process_events = time()
        for line in self._gcode:
            single_string_file_data += line
            if time() > last_process_events + 0.05:
                # Ensure that the GUI keeps updated at least 20 times per second.
                QCoreApplication.processEvents()
                last_process_events = time()

        job_name = Application.getInstance().getPrintInformation().jobName.strip()
        if job_name is "":
            job_name = "untitled_print"
        file_name = "%s.gcode" % job_name

        ##  Create multi_part request
        self._post_multi_part = QHttpMultiPart(QHttpMultiPart.FormDataType)

        ##  Create parts (to be placed inside multipart)
        post_part = QHttpPart()
        post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"select\"")
        post_part.setBody(b"true")
        self._post_multi_part.append(post_part)

        if self._auto_print and not self._forced_queue:
            post_part = QHttpPart()
            post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"print\"")
            post_part.setBody(b"true")
            self._post_multi_part.append(post_part)

        post_part = QHttpPart()
        post_part.setHeader(QNetworkRequest.ContentDispositionHeader, "form-data; name=\"file\"; filename=\"%s\"" % file_name)
        post_part.setBody(single_string_file_data.encode())
        self._post_multi_part.append(post_part)

        destination = "local"
        if self._sd_supported and parseBool(Application.getInstance().getGlobalContainerStack().getMetaDataEntry("octoprint_store_sd", False)):
            destination = "sdcard"

        try:
            ##  Post request + data
            post_request = self._createApiRequest("files/" + destination)
            self._post_reply = self._manager.post(post_request, self._post_multi_part)
            self._post_reply.uploadProgress.connect(self._onUploadProgress)

        except IOError:
            self._progress_message.hide()
            self._error_message = Message(i18n_catalog.i18nc("@info:status", "Unable to send data to OctoPrint."))
            self._error_message.show()
        except Exception as e:
            self._progress_message.hide()
            Logger.log("e", "An exception occurred in network connection: %s" % str(e))

        self._gcode = []

    def _cancelSendGcode(self, message_id, action_id):
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

    def sendCommand(self, command):
        self._queued_gcode_commands.append(command)
        self._queued_gcode_timer.start()

    # Send gcode commands that are queued in quick succession as a single batch
    def _sendQueuedGcode(self):
        if self._queued_gcode_commands:
            self._sendCommandToApi("printer/command", self._queued_gcode_commands)
            Logger.log("d", "Sent gcode command to OctoPrint instance: %s", self._queued_gcode_commands)
            self._queued_gcode_commands = []

    def _sendJobCommand(self, command):
        self._sendCommandToApi("job", command)
        Logger.log("d", "Sent job command to OctoPrint instance: %s", command)

    def _sendCommandToApi(self, end_point, commands):
        command_request = self._createApiRequest(end_point)
        command_request.setHeader(QNetworkRequest.ContentTypeHeader, "application/json")

        if isinstance(commands, list):
            data = json.dumps({"commands": commands})
        else:
            data = json.dumps({"command": commands})
        self._command_reply = self._manager.post(command_request, data.encode())

    ##  Handler for all requests that have finished.
    def _onRequestFinished(self, reply):
        if reply.error() == QNetworkReply.TimeoutError:
            Logger.log("w", "Received a timeout on a request to the instance")
            self._connection_state_before_timeout = self._connection_state
            self.setConnectionState(ConnectionState.error)
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

                if http_status_code == 200:
                    if not self.acceptsCommands:
                        self._setAcceptsCommands(True)
                        self.setConnectionText(i18n_catalog.i18nc("@info:status", "Connected to OctoPrint on {0}").format(self._id))

                    if self._connection_state == ConnectionState.connecting:
                        self.setConnectionState(ConnectionState.connected)
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
                    if self._connection_state == ConnectionState.connecting:
                        self.setConnectionState(ConnectionState.connected)

                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    self.setConnectionText(i18n_catalog.i18nc("@info:status", "The printer connected to OctoPrint on {0} is not operational").format(self._id))
                    error_handled = True
                else:
                    printer.updateState("offline")
                    if printer.activePrintJob:
                        printer.activePrintJob.updateState("offline")
                    Logger.log("w", "Received an unexpected returncode: %d", http_status_code)

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
                        if self._camera_url != "" and len(self._printers) > 0:
                            self._printers[0].setCamera(NetworkCamera(self._camera_url))

                        if "rotate90" in json_data["webcam"]:
                            self._camera_rotation = -90 if json_data["webcam"]["rotate90"] else 0
                            if json_data["webcam"]["flipH"] and json_data["webcam"]["flipV"]:
                                self._camera_mirror = False
                                self._camera_rotation += 180
                            elif json_data["webcam"]["flipH"]:
                                self._camera_mirror = True
                            elif json_data["webcam"]["flipV"]:
                                self._camera_mirror = True
                                self._camera_rotation += 180
                            else:
                                self._camera_mirror = False
                            self.cameraOrientationChanged.emit()

                    if "plugins" in json_data:
                        self._plugin_data = json_data["plugins"]

                        can_update_firmware = "firmwareupdater" in self._plugin_data
                        self._output_controller.setCanUpdateFirmware(can_update_firmware)

        elif reply.operation() == QNetworkAccessManager.PostOperation:
            if self._api_prefix + "files" in reply.url().toString():  # Result from /files command:
                if http_status_code == 201:
                    Logger.log("d", "Resource created on OctoPrint instance: %s", reply.header(QNetworkRequest.LocationHeader).toString())
                else:
                    pass  # See generic error handler below

                reply.uploadProgress.disconnect(self._onUploadProgress)
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
                    message.actionTriggered.connect(self._onMessageActionTriggered)
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
            error_string = reply.attribute(QNetworkRequest.HttpReasonPhraseAttribute).decode("utf-8")
            if self._error_message:
                self._error_message.hide()
            self._error_message = Message(i18n_catalog.i18nc("@info:status", "OctoPrint returned an error: {0}.").format(error_string))
            self._error_message.show()
            return

    def _onUploadProgress(self, bytes_sent, bytes_total):
        if bytes_total > 0:
            # Treat upload progress as response. Uploading can take more than 10 seconds, so if we don't, we can get
            # timeout responses if this happens.
            self._last_response_time = time()

            progress = bytes_sent / bytes_total * 100
            if progress < 100:
                if progress > self._progress_message.getProgress():
                    self._progress_message.setProgress(progress)
            else:
                self._progress_message.hide()
                self._progress_message = Message(i18n_catalog.i18nc("@info:status", "Storing data on OctoPrint"), 0, False, -1)
                self._progress_message.show()
        else:
            self._progress_message.setProgress(0)

    def _createPrinterList(self):
        printer = PrinterOutputModel(output_controller=self._output_controller, number_of_extruders=self._number_of_extruders)
        if self._camera_url != "":
            printer.setCamera(NetworkCamera(self._camera_url))
        printer.updateName(self.name)
        self._printers = [printer]
        self.printersChanged.emit()

    def _onMessageActionTriggered(self, message, action):
        if action == "open_browser":
            QDesktopServices.openUrl(QUrl(self._base_url))
