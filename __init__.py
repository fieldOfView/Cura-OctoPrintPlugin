# Copyright (c) 2022 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import os, json

from . import OctoPrintOutputDevicePlugin
from . import DiscoverOctoPrintAction
from . import NetworkMJPGImage

from UM.Version import Version
from UM.Application import Application
from UM.Logger import Logger

try:
    from cura.ApplicationMetadata import CuraSDKVersion
except ImportError: # Cura <= 3.6
    CuraSDKVersion = "6.0.0"
if CuraSDKVersion >= "8.0.0":
    from PyQt6.QtQml import qmlRegisterType
else:
    from PyQt5.QtQml import qmlRegisterType

def getMetaData():
    return {}


def register(app):
    qmlRegisterType(
        NetworkMJPGImage.NetworkMJPGImage, "OctoPrintPlugin", 1, 0, "NetworkMJPGImage"
    )

    return {
        "output_device": OctoPrintOutputDevicePlugin.OctoPrintOutputDevicePlugin(),
        "machine_action": DiscoverOctoPrintAction.DiscoverOctoPrintAction(),
    }
