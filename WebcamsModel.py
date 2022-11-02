# Copyright (c) 2022 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

try:
    from cura.ApplicationMetadata import CuraSDKVersion
except ImportError: # Cura <= 3.6
    CuraSDKVersion = "6.0.0"
if CuraSDKVersion >= "8.0.0":
    from PyQt6.QtCore import Qt
else:
    from PyQt5.QtCore import Qt

from UM.Qt.ListModel import ListModel
from UM.Logger import Logger

from typing import List, Dict, Any, Union


class WebcamsModel(ListModel):
    def __init__(
        self,
        protocol: str,
        address: str,
        port: int = 80,
        basic_auth_string: str = "",
        parent=None,
    ) -> None:
        super().__init__(parent)

        self._protocol = protocol
        self._address = address
        self._port = port
        self._basic_auth_string = basic_auth_string

        try:
            user_role = Qt.ItemDataRole.UserRole
        except AttributeError:
            user_role = Qt.UserRole

        self.addRoleName(user_role + 1, "name")
        self.addRoleName(user_role + 2, "stream_url")
        self.addRoleName(user_role + 3, "rotation")
        self.addRoleName(user_role + 4, "mirror")

    def deserialise(self, data: List[Dict[str, Any]]) -> None:
        items = []

        for webcam in data:
            item = {
                "name": "_default",
                "stream_url": "",
                "rotation": 0,
                "mirror": False,
            }

            stream_url = ""
            if "streamUrl" in webcam and webcam["streamUrl"] != None:  # from /webcam/
                stream_url = webcam["streamUrl"].strip()
            elif "URL" in webcam and webcam["URL"] != None:  # from /plugins/multicam
                stream_url = webcam["URL"].strip()

            if not stream_url:  # empty string or None
                continue
            elif stream_url[:4].lower() == "http":  # absolute uri
                item["stream_url"] = stream_url
            elif stream_url[:2] == "//":  # protocol-relative
                item["stream_url"] = "%s:%s" % (self._protocol, stream_url)
            elif stream_url[:1] == ":":  # domain-relative (on another port)
                item["stream_url"] = "%s://%s%s" % (
                    self._protocol,
                    self._address,
                    stream_url,
                )
            elif stream_url[:1] == "/":  # domain-relative (on same port)
                if not self._basic_auth_string:
                    item["stream_url"] = "%s://%s:%d%s" % (
                        self._protocol,
                        self._address,
                        self._port,
                        stream_url,
                    )
                else:
                    item["stream_url"] = "%s://%s@%s:%d%s" % (
                        self._protocol,
                        self._basic_auth_string,
                        self._address,
                        self._port,
                        stream_url,
                    )
            else:
                Logger.log("w", "Unusable stream url received: %s", stream_url)
                item["stream_url"] = ""

            if "rotate90" in webcam:
                item["rotation"] = -90 if webcam["rotate90"] else 0
                if webcam["flipH"] and webcam["flipV"]:
                    item["mirror"] = False
                    item["rotation"] += 180  # type: ignore
                elif webcam["flipH"]:
                    item["mirror"] = True
                    item["rotation"] += 180  # type: ignore
                elif webcam["flipV"]:
                    item["mirror"] = True
                else:
                    item["mirror"] = False

            if "name" in webcam and webcam["name"] != None:
                item["name"] = webcam["name"]

            items.append(item)

        if self._items != items:
            self.setItems(items)
