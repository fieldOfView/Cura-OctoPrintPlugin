# OctoPrintPlugin
Cura plugin which enables printing directly to OctoPrint and monitoring the progress

This plugin started out as a fork of the UM3NetworkPrinting plugin:
https://github.com/Ultimaker/Cura/tree/2.4/plugins/UM3NetworkPrinting

Installation
----
* Marketplace (recommended):
  The plugin is available through the Cura Marketplace as the OctoPrint Connection plugin
* Manually:
  Download or clone the repository into [Cura configuration folder]/plugins/OctoPrintPlugin
  The configuration folder can be found via Help -> Show Configuration Folder inside Cura.
* Cura PPA (*Ubuntu):
  - Add the cura PPA via (if not already done): `sudo add-apt-repository ppa:thopiekar/cura`
  - Update APT via: `sudo apt update`
  - Install the plugin via: `sudo apt install cura-plugin-octoprint`


How to use
----
- Make sure OctoPrint is up and running, and the discovery plugin is not disabled
- In Cura, add a Printer matching the 3d printer you have connected to OctoPrint
- Select "Connect to OctoPrint" on the Printers pane of the preferences.
- Select your OctoPrint instance from the list and enter the API key which is
  available in the OctoPrint settings.
- From this point on, the print monitor should be functional and you should be
  able to switch to "Print to Octoprint" on the bottom of the sidebar.

Notes on UltiGCode (Ultimaker 2/Ultimaker 2+)
----
The Ultimaker 2(+) family uses a flavor of GCode named UltiGCode. Unfortunately printing
using UltiGCode flavor does not work when printing over the USB connection. That is why
using OctoPrint does not work with UltiGCode flavor.

zeroconf
----
This plugin contains a fork of the python zeroconf module by jstasiak which is licensed under the LGPL-2.1:
https://github.com/jstasiak/python-zeroconf
This fork is included with the plugin because the version that is included with Cura itself is old and contains bugs.