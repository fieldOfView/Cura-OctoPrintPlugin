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

    if __matchVersion():
        return {
	        "output_device": OctoPrintOutputDevicePlugin.OctoPrintOutputDevicePlugin(),
	        "machine_action": DiscoverOctoPrintAction.DiscoverOctoPrintAction()
        }
    else:
        Logger.log("w", "Plugin not loaded because of a version mismatch")
        return {}

def __matchVersion():
    cura_version = Application.getInstance().getVersion()
    if cura_version == "master":
        Logger.log("d", "Running Cura from source, ignoring version of the plugin")
        return True
    cura_version = Version(cura_version)
    cura_version = Version([cura_version.getMajor(), cura_version.getMinor()])

    # Get version information from plugin.json
    plugin_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "plugin.json")
    try:
        with open(plugin_file_path) as plugin_file:
            plugin_info = json.load(plugin_file)
            minimum_cura_version = Version(plugin_info["minimum_cura_version"])
            maximum_cura_version = Version(plugin_info["maximum_cura_version"])
    except:
        Logger.log("w", "Could not get version information for the plugin")
        return False

    if cura_version >= minimum_cura_version and cura_version <= maximum_cura_version:
        return True
    else:
        Logger.log("d", "This version of the plugin is not compatible with this version of Cura. Please check for an update.")
        return False