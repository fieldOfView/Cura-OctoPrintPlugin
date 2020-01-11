# Copyright (c) 2020 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

from collections import OrderedDict

class OctoPrintPowerPlugins():

    def __init__(self) -> None:
        self._available_plugs = OrderedDict()

    def parsePluginData(self, plugin_data: OrderedDict):
        self._available_plugs = OrderedDict()

        # plugins that only support a single plug
        for (plugin_id, plugin_name) in [
            ("psucontrol", "PSU Control"),
            ("mystromswitch", "MyStrom Switch")
        ]:
            if plugin_id in plugin_data:
                if plugin_id != "mystromswitch" or plugin_data[plugin_id]["ip"]:
                    plug = OrderedDict([
                        ("plugin", plugin_id),
                        ("name", plugin_name)
                    ])
                    self._available_plugs[self._createPlugId(plug)] = plug

        # plugins that have a `label` and `ip` specified in `arrSmartplugs`
        for (plugin_id, plugin_name, additional_data) in [
            ("tplinksmartplug", "TP-Link Smartplug", []), # ip
            ("orvibos20", "Orvibo S20", []), # ip
            ("wemoswitch", "Wemo Switch", []), # ip
            ("tuyasmartplug", "Tuya Smartplug", []), # label
            ("domoticz", "Domoticz", ["idx"]), # ip, idx
            ("tasmota", "Tasmota", ["idx", "username", "password"]), # ip, idx, username, password
        ]:
            if plugin_id in plugin_data and "arrSmartplugs" in plugin_data[plugin_id]:
                for plug_data in plugin_data[plugin_id]["arrSmartplugs"]:
                    if plug_data["ip"] and plug_data["label"]:
                        plug = OrderedDict([
                            ("plugin", plugin_id),
                            ("name", ("%s (%s)" % (plug_data["label"], plugin_name))),
                            ("label", plug_data["label"]),
                            ("ip", plug_data["ip"])
                        ])
                        for key in additional_data:
                            plug[key] = plug_data[key]
                        self._available_plugs[self._createPlugId(plug)] = plug

        # `tasmota_mqtt` has a slightly different settings dialect
        if "tasmota_mqtt" in plugin_data:
            plugin_id = "tasmota_mqtt"
            plugin_name = "Tasmota MQTT"
            for plug_data in plugin_data[plugin_id]["arrRelays"]:
                if plug_data["topic"] and plug_data["relayN"] != "":
                    plug = OrderedDict([
                        ("plugin", plugin_id),
                        ("name", "%s/%s (%s)" % (plug_data["topic"], plug_data["relayN"], plugin_name)),
                        ("topic", plug_data["relayN"]),
                        ("relayN", plug_data["relayN"])
                    ])
                    self._available_plugs[self._createPlugId(plug)] = plug

    def _createPlugId(self, plug_data: OrderedDict) -> str:
        return "/".join(list(plug_data.values()))

    def getAvailablePowerPlugs(self) -> OrderedDict:
        return self._available_plugs

    def getSetStateCommand(self, state: bool, plug_id: str) -> str:
        if plug_id not in self._available_plugs:
            return ""

        plugin_id = self._available_plugs[plug_id]
        end_point = "plugin/" + plugin_id

        if plugin_id == "psucontrol":
            return (end_point, "turnPSUOn" if state else "turnPSUOff")

        if plugin_id == "mystromswitch":
            return (end_point, "enableRelais" if state else "disableRelais")

        plug_data = self._available_plugs[plug_id]
        command_arguments = ["turnOn" if state else "turnOff"]
        if plugin_id in ["tplinksmartplug", "orvibos20", "wemoswitch"]:
            # ip
            command_arguments.append(plug_data["ip"])
        elif plugin_id == "domoticz":
            # ip, idx
            command_arguments.append(plug_data["ip"], plug_data["idx"])
        elif plugin_id == "tasmota_mqtt":
            # topic, relayN
            command_arguments.append(plug_data["topic"], plug_data["relayN"])
        elif plugin_id == "tasmota":
            # ip, idx, username, password
            command_arguments.append(plug_data["ip"], plug_data["idx"], plug_data["username"], plug_data["password"])
        elif plugin_id == "tuyasmartplug":
            # label
            command_arguments.append(plug_data["label"])

        return (end_point, "/".join(command_arguments))