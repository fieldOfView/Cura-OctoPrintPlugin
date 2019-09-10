# Copyright (c) 2019 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import os, json

from . import OctoPrintOutputDevicePlugin
from . import DiscoverOctoPrintAction
from . import NetworkMJPGImage

from UM.Version import Version
from UM.Application import Application
from UM.Logger import Logger

from PyQt5.QtQml import qmlRegisterType

def getMetaData():
    return {}

def register(app):
    qmlRegisterType(NetworkMJPGImage.NetworkMJPGImage, "OctoPrintPlugin", 1, 0, "NetworkMJPGImage")

    return {
        "output_device": OctoPrintOutputDevicePlugin.OctoPrintOutputDevicePlugin(),
        "machine_action": DiscoverOctoPrintAction.DiscoverOctoPrintAction()
    }
