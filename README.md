# OctoPrintPlugin
Cura plugin which enables printing directly to OctoPrint and monitoring the progress.

OctoPrint is a registered trademark. For more information about OctoPrint, see
[octoprint.org](https://octoprint.org).

This plugin started out as a fork of the [UM3NetworkPrinting plugin](https://github.com/Ultimaker/Cura/tree/2.4/plugins/UM3NetworkPrinting)

This plugin is made possible in part by a contribution of [@ErikDeBruijn](https://github.com/ErikDeBruijn)
and my other github sponsors. The development of this plugin can be sponsored via
[Github Sponsors](https://github.com/sponsors/fieldofview) or [Paypal](https://www.paypal.me/fieldofview).

Installation
----
#### Marketplace (recommended):
The plugin is available through the Cura Marketplace as the OctoPrint Connection plugin
#### Manually:
Download or clone the repository into `[Cura configuration folder]/plugins/OctoPrintPlugin`.
When cloning the repository, make sure to use the `--recursive` flag to include the submodules.

The configuration folder can be found via Help -> Show Configuration Folder inside Cura.
This opens the following folder:
* Windows: `%APPDATA%\cura\<Cura version>\`, (usually `C:\Users\<your username>\AppData\Roaming\cura\<Cura version>\`)
* Mac OS: `$HOME/Library/Application Support/cura/<Cura version>/`
* Linux: `$HOME/.local/share/cura/<Cura version>/`

How to use
----
- Make sure OctoPrint is up and running, and the discovery plugin is not disabled
- In Cura, add a local printer matching the 3d printer you have connected to OctoPrint
- Select "Connect to OctoPrint" on the Printers pane of the preferences.
- Select your OctoPrint instance from the list and enter the API key which is
  available in the OctoPrint settings, or push the "Request..." button to request an
  application key from the OctoPrint instance.
- Press the "Connect" button to connect the printer in Cura with the OctoPrint instance.
- From this point on, the print monitor should be functional and you should be
  able to switch to "Print to Octoprint" in the lower right of the Cura window.

Plugins
---
The OctoPrint Connection plugin has special support for the following OctoPrint plugins:

### [Ultimaker Package Format](https://plugins.octoprint.org/plugins/UltimakerFormatPackage/)
Support for including a thubmnail of the model along with the gcode.

### [PSU Control](https://plugins.octoprint.org/plugins/psucontrol/), [TP-Link Smartplug](https://plugins.octoprint.org/plugins/tplinksmartplug/), [Orvibo S20](https://plugins.octoprint.org/plugins/orvibos20/), [Wemo Switch](https://plugins.octoprint.org/plugins/wemoswitch/), [Tuya Smartplug](https://plugins.octoprint.org/plugins/tuyasmartplug/), [Domoticz](https://plugins.octoprint.org/plugins/domoticz/), [Tasmota](https://plugins.octoprint.org/plugins/tasmota/), [MyStrom Switch](https://plugins.octoprint.org/plugins/mystromswitch/), [IKEA Trådfri](https://plugins.octoprint.org/plugins/ikea_tradfri/)
Support turning on the printer before sending a print job to OctoPrint.

### [MultiCam](https://plugins.octoprint.org/plugins/multicam/)
Support for multiple cameras in the monitor view.

### [Print Time Genius](https://plugins.octoprint.org/plugins/PrintTimeGenius)
Delay starting the print until after gcode analysis is done.

Notes on UltiGCode (Ultimaker 2/Ultimaker 2+)
----
The Ultimaker 2(+) family uses a flavor of GCode named UltiGCode. Unfortunately printing
using UltiGCode flavor does not work when printing over the USB connection. That is why
using OctoPrint does not work with UltiGCode flavor.

Included dependencies
----
This plugin contains a submodule/copy of the following dependecies:

### [zeroconf](https://github.com/jstasiak/python-zeroconf) as maintained by jstasiak.
Python-zeroconf is licensed under the LGPL-2.1

The module is included in the OctoPrintPlugin to replace the version that ships with
older versions of Cura because that version has bugs.

### [ifaddr](https://github.com/pydron/ifaddr) as maintained by pydron.
ifaddr is licensed under the MIT license.

### [async-timeout](https://github.com/aio-libs/async-timeout) as maintained by aio-libs
async-timeout is licensed under the Apache License, Version 2.0.

ifaddr and async-timeout are included in the OctoPrintPlugin because it is a dependency
of python-zeroconf and they are not included with older versions of Cura.