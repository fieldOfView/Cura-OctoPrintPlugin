# Copyright (c) 2022 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

from UM.Application import Application
from UM.Version import Version
from UM.Util import parseBool

try:
    from cura.ApplicationMetadata import CuraSDKVersion
except ImportError: # Cura <= 3.6
    CuraSDKVersion = "6.0.0"
USE_QT5 = False
if CuraSDKVersion >= "8.0.0":
    from PyQt6.QtCore import QObject, pyqtSignal, pyqtProperty, pyqtSlot
else:
    from PyQt5.QtCore import QObject, pyqtSignal, pyqtProperty, pyqtSlot
    USE_QT5 = True

import os.path

from typing import Any, Tuple, List, Dict, Callable, Optional


class UploadOptions(QObject):
    def __init__(self) -> None:
        super().__init__()
        self._application = Application.getInstance()

        self._proceed_callback = None  # type: Optional[Callable]

        self._file_name = ""
        self._file_path = ""

        self._auto_select = False
        self._auto_print = False

        self._qml_folder = "qml" if not USE_QT5 else "qml_qt5"


    def configure(self, global_container_stack, file_name) -> None:
        self.setAutoPrint(
            parseBool(
                global_container_stack.getMetaDataEntry("octoprint_auto_print", True)
            )
        )
        self.setAutoSelect(
            parseBool(
                global_container_stack.getMetaDataEntry("octoprint_auto_select", False)
            )
        )

        file_name_segments = file_name.split("/")
        self.setFileName(file_name_segments.pop())
        self.setFilePath("/".join(file_name_segments))

    def setProceedCallback(self, callback: Callable) -> None:
        self._proceed_callback = callback

    def showOptionsDialog(self) -> None:
        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), self._qml_folder, "UploadOptions.qml"
        )

        self._settings_dialog = self._application.createQmlComponent(
            path, {"manager": self}
        )
        if self._settings_dialog:
            self._settings_dialog.show()

    @pyqtSlot()
    def acceptOptionsDialog(self) -> None:
        if self._proceed_callback:
            self._proceed_callback()

    fileNameChanged = pyqtSignal()

    def setFileName(self, file_name: str) -> None:
        self._file_name = file_name
        self.fileNameChanged.emit()

    @pyqtProperty(str, notify=fileNameChanged, fset=setFileName)
    def fileName(self) -> str:
        return self._file_name

    filePathChanged = pyqtSignal()

    def setFilePath(self, file_path: str) -> None:
        self._file_path = file_path
        self.filePathChanged.emit()

    @pyqtProperty(str, notify=filePathChanged, fset=setFilePath)
    def filePath(self) -> str:
        return self._file_path

    autoSelectChanged = pyqtSignal()

    def setAutoSelect(self, auto_select: bool) -> None:
        self._auto_select = auto_select
        self.autoSelectChanged.emit()

    @pyqtProperty(bool, notify=autoSelectChanged, fset=setAutoSelect)
    def autoSelect(self) -> bool:
        return self._auto_select

    autoPrintChanged = pyqtSignal()

    def setAutoPrint(self, auto_print: bool) -> None:
        self._auto_print = auto_print
        self.autoPrintChanged.emit()

    @pyqtProperty(bool, notify=autoPrintChanged, fset=setAutoPrint)
    def autoPrint(self) -> bool:
        return self._auto_print
