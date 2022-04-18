// Copyright (c) 2022 Aldo Hoeben / fieldOfView
// OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import UM 1.2 as UM
import Cura 1.0 as Cura

import QtQuick 2.2
import QtQuick.Controls 2.0

Item
{
    id: base

    property bool printerConnected: Cura.MachineManager.printerOutputDevices.length != 0
    property bool octoPrintConnected: printerConnected && Cura.MachineManager.printerOutputDevices[0].toString().indexOf("OctoPrintOutputDevice") == 0

    Cura.SecondaryButton
    {
        objectName: "openOctoPrintButton"
        height: UM.Theme.getSize("save_button_save_to_button").height
        tooltip: catalog.i18nc("@info:tooltip", "Open the OctoPrint web interface")
        text: catalog.i18nc("@action:button", "OctoPrint...")
        onClicked: manager.openWebPage(Cura.MachineManager.printerOutputDevices[0].baseURL)
        visible: octoPrintConnected
    }

    UM.I18nCatalog{id: catalog; name:"octoprint"}
}