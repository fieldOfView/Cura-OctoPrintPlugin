# Copyright (c) 2022 Aldo Hoeben / fieldOfView
# OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

from collections import OrderedDict
from typing import Any, Tuple, List, Dict


class PowerPlugins:
    def __init__(self) -> None:
        self._available_plugs = OrderedDict()  # type: Dict[str, Any]

    def parsePluginData(self, plugin_data: Dict[str, Any]) -> None:
        self._available_plugs = OrderedDict()  # type: Dict[str, Any]

        # plugins that only support a single plug
        simple_plugins = [
            ("psucontrol", "PSU Control", []),
            ("mystromswitch", "MyStrom Switch", ["ip"]),
            ("ikea_tradfri", "IKEA Trådfri", ["gateway_ip", "selected_outlet"]),
        ]  # type: List[Tuple[str, str, List[str]]]
        for (plugin_id, plugin_name, additional_data) in simple_plugins:
            if plugin_id in plugin_data:
                plug_data = plugin_data[plugin_id]
                all_config_set = True
                for config_item in additional_data:
                    if not plug_data.get(config_item, None):
                        all_config_set = False
                        break
                if all_config_set:
                    plug = OrderedDict([("plugin", plugin_id), ("name", plugin_name)])
                    self._available_plugs[self._createPlugId(plug)] = plug

        # plugins that have a `label` and `ip` specified in `arrSmartplugs`
        common_api_plugins = [
            ("tplinksmartplug", "TP-Link Smartplug", []),  # ip
            ("orvibos20", "Orvibo S20", []),  # ip
            ("wemoswitch", "Wemo Switch", []),  # ip
            ("tuyasmartplug", "Tuya Smartplug", []),  # label
            (
                "domoticz",
                "Domoticz",
                ["idx", "username", "password"],
            ),  # ip, idx, username, password
            (
                "tasmota",
                "Tasmota",
                ["idx"],
            ),  # ip, idx, username, password, backlog_delay
        ]  # type: List[Tuple[str, str, List[str]]]
        for (plugin_id, plugin_name, additional_data) in common_api_plugins:
            if plugin_id in plugin_data and "arrSmartplugs" in plugin_data[plugin_id]:
                for plug_data in plugin_data[plugin_id]["arrSmartplugs"]:
                    if plug_data.get("ip", ""):
                        plug_label = plug_data.get("label", "")
                        plug = OrderedDict(
                            [
                                ("plugin", plugin_id),
                                (
                                    "name",
                                    "%s (%s)" % (plug_label, plugin_name)
                                    if plug_label
                                    else plugin_name,
                                ),
                                ("label", plug_label),
                                ("ip", plug_data["ip"]),
                            ]
                        )
                        for key in additional_data:
                            plug[key] = plug_data.get(key, "")
                        self._available_plugs[self._createPlugId(plug)] = plug

        # `tasmota_mqtt` has a slightly different settings dialect
        if "tasmota_mqtt" in plugin_data:
            plugin_id = "tasmota_mqtt"
            plugin_name = "Tasmota MQTT"
            for plug_data in plugin_data[plugin_id]["arrRelays"]:
                if plug_data.get("topic", "") and plug_data.get("relayN", ""):
                    plug = OrderedDict(
                        [
                            ("plugin", plugin_id),
                            (
                                "name",
                                "%s/%s (%s)"
                                % (
                                    plug_data["topic"],
                                    plug_data["relayN"],
                                    plugin_name,
                                ),
                            ),
                            ("topic", plug_data["topic"]),
                            ("relayN", plug_data["relayN"]),
                        ]
                    )
                    self._available_plugs[self._createPlugId(plug)] = plug

    def _createPlugId(self, plug_data: Dict[str, Any]) -> str:
        interesting_bits = [v for (k, v) in plug_data.items() if k != "name"]
        return "/".join(interesting_bits)

    def getAvailablePowerPlugs(self) -> Dict[str, Any]:
        return self._available_plugs

    def getSetStateCommand(
        self, plug_id: str, state: bool
    ) -> Tuple[str, Dict[str, Any]]:
        if plug_id not in self._available_plugs:
            return ("", {})

        plugin_id = self._available_plugs[plug_id]["plugin"]
        end_point = "plugin/" + plugin_id

        if plugin_id == "psucontrol":
            return (
                end_point,
                OrderedDict([("command", "turnPSUOn" if state else "turnPSUOff")]),
            )

        if plugin_id == "mystromswitch":
            return (
                end_point,
                OrderedDict(
                    [("command", "enableRelais" if state else "disableRelais")]
                ),
            )

        plug_data = self._available_plugs[plug_id]
        command = OrderedDict([("command", "turnOn" if state else "turnOff")])
        arguments = []  # type: List[str]
        if plugin_id in ["tplinksmartplug", "orvibos20", "wemoswitch"]:
            # ip
            arguments = ["ip"]
        elif plugin_id == "domoticz":
            # ip, idx, username, password
            arguments = ["ip", "idx", "username", "password"]
        elif plugin_id == "tasmota_mqtt":
            # topic, relayN
            arguments = ["topic", "relayN"]
        elif plugin_id == "tasmota":
            # ip, idx
            arguments = ["ip", "idx"]
        elif plugin_id == "tuyasmartplug":
            # label
            arguments = ["label"]

        for key in arguments:
            command[key] = plug_data[key]

        return (end_point, command)
