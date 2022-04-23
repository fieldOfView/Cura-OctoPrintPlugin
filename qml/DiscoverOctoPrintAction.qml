// Copyright (c) 2022 Aldo Hoeben / fieldOfView
// OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import QtQuick 2.1
import QtQuick.Controls 2.0

import UM 1.5 as UM
import Cura 1.0 as Cura


Cura.MachineAction
{
    id: base

    readonly property string defaultHTTP: "80"
    readonly property string defaultHTTPS: "443"

    anchors.fill: parent;
    property var selectedInstance: null
    property string activeMachineId:
    {
        if (Cura.MachineManager.activeMachineId != undefined)
        {
            return Cura.MachineManager.activeMachineId;
        }
        else if (Cura.MachineManager.activeMachine !== null)
        {
            return Cura.MachineManager.activeMachine.id;
        }

        CuraApplication.log("There does not seem to be an active machine");
        return "";
    }

    onVisibleChanged:
    {
        if(!visible)
        {
            manager.cancelApiKeyRequest();
        }
    }

    function boolCheck(value) //Hack to ensure a good match between python and qml.
    {
        if(value == "True")
        {
            return true
        }else if(value == "False" || value == undefined)
        {
            return false
        }
        else
        {
            return value
        }
    }

    Column
    {
        anchors.fill: parent;
        id: discoverOctoPrintAction

        spacing: UM.Theme.getSize("default_margin").height
        width: parent.width

        UM.I18nCatalog { id: catalog; name:"octoprint" }

        Item
        {
            width: parent.width
            height: pageTitle.height

            UM.Label
            {
                id: pageTitle
                text: catalog.i18nc("@title", "Connect to OctoPrint")
                font: UM.Theme.getFont("large_bold")
            }

            UM.Label
            {
                id: pluginVersion
                anchors.bottom: pageTitle.bottom
                anchors.right: parent.right
                text: manager.pluginVersion
                font.pointSize: 8
            }
        }

        UM.Label
        {
            id: pageDescription
            width: parent.width
            text: catalog.i18nc("@label", "Select your OctoPrint instance from the list below.")
        }

        Row
        {
            spacing: UM.Theme.getSize("default_lining").width

            Cura.SecondaryButton
            {
                id: addButton
                text: catalog.i18nc("@action:button", "Add");
                onClicked:
                {
                    manualInstanceDialog.showDialog("", "", base.defaultHTTP, "/", false, "", "");
                }
            }

            Cura.SecondaryButton
            {
                id: editButton
                text: catalog.i18nc("@action:button", "Edit")
                enabled: base.selectedInstance != null && base.selectedInstance.getProperty("manual") == "true"
                onClicked:
                {
                    manualInstanceDialog.showDialog(
                        base.selectedInstance.name, base.selectedInstance.ipAddress,
                        base.selectedInstance.port, base.selectedInstance.path,
                        base.selectedInstance.getProperty("useHttps") == "true",
                        base.selectedInstance.getProperty("userName"), base.selectedInstance.getProperty("password")
                    );
                }
            }

            Cura.SecondaryButton
            {
                id: removeButton
                text: catalog.i18nc("@action:button", "Remove")
                enabled: base.selectedInstance != null && base.selectedInstance.getProperty("manual") == "true"
                onClicked: manager.removeManualInstance(base.selectedInstance.name)
            }

            Cura.SecondaryButton
            {
                id: rediscoverButton
                text: catalog.i18nc("@action:button", "Refresh")
                enabled: useZeroconf.checked
                onClicked: manager.startDiscovery()
            }
        }

        Row
        {
            width: parent.width
            spacing: UM.Theme.getSize("default_margin").width

            Rectangle
            {
                width: Math.floor(parent.width * 0.4)
                height: base.height - (parent.y + UM.Theme.getSize("default_margin").height)

                color: UM.Theme.getColor("main_background")
                border.width: UM.Theme.getSize("default_lining").width
                border.color: UM.Theme.getColor("thick_lining")

                ListView
                {
                    id: listview

                    clip: true
                    ScrollBar.vertical: UM.ScrollBar {}

                    anchors.fill: parent
                    anchors.margins: UM.Theme.getSize("default_lining").width

                    model: manager.discoveredInstances
                    onModelChanged:
                    {
                        var selectedId = manager.instanceId;
                        for(var i = 0; i < model.length; i++) {
                            if(model[i].getId() == selectedId)
                            {
                                currentIndex = i;
                                return
                            }
                        }
                        currentIndex = -1;
                    }

                    currentIndex: activeIndex
                    onCurrentIndexChanged:
                    {
                        base.selectedInstance = listview.model[currentIndex];
                        apiCheckDelay.throttledCheck();
                    }

                    Component.onCompleted: manager.startDiscovery()

                    delegate: Rectangle
                    {
                        height: childrenRect.height
                        color: ListView.isCurrentItem ? UM.Theme.getColor("text_selection") : UM.Theme.getColor("main_background")
                        width: parent.width
                        UM.Label
                        {
                            anchors.left: parent.left
                            anchors.leftMargin: UM.Theme.getSize("default_margin").width
                            anchors.right: parent.right
                            text: listview.model[index].name
                            elide: Text.ElideRight
                            font.italic: listview.model[index].key == manager.instanceId
                            wrapMode: Text.NoWrap
                        }

                        MouseArea
                        {
                            anchors.fill: parent;
                            onClicked:
                            {
                                if(!parent.ListView.isCurrentItem)
                                {
                                    parent.ListView.view.currentIndex = index;
                                }
                            }
                        }
                    }
                }

                Item
                {
                    id: objectListFooter

                    width: parent.width
                    anchors.bottom: parent.bottom

                    UM.CheckBox
                    {
                        id: useZeroconf
                        text: catalog.i18nc("@label", "Automatically discover local OctoPrint instances")
                        checked: boolCheck(UM.Preferences.getValue("octoprint/use_zeroconf"))
                        onClicked:
                        {
                            if(checked != boolCheck(UM.Preferences.getValue("octoprint/use_zeroconf")))
                            {
                                UM.Preferences.setValue("octoprint/use_zeroconf", checked);
                                manager.startDiscovery();
                            }
                        }
                    }
                }
            }

            Column
            {
                width: Math.floor(parent.width * 0.6)
                spacing: UM.Theme.getSize("default_margin").height
                UM.Label
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    text: base.selectedInstance ? base.selectedInstance.name : ""
                    font: UM.Theme.getFont("large_bold")
                    elide: Text.ElideRight
                }
                Grid
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    columns: 2
                    rowSpacing: UM.Theme.getSize("default_lining").height
                    verticalItemAlignment: Grid.AlignVCenter
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        text: catalog.i18nc("@label", "Address")
                    }
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.75)
                        wrapMode: Text.WordWrap
                        text: base.selectedInstance ? "%1:%2".arg(base.selectedInstance.ipAddress).arg(String(base.selectedInstance.port)) : ""
                    }
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        text: catalog.i18nc("@label", "Version")
                    }
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.75)
                        text: base.selectedInstance ? base.selectedInstance.octoPrintVersion : ""
                    }
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        text: catalog.i18nc("@label", "API Key")
                    }
                    Row
                    {
                        spacing: UM.Theme.getSize("default_margin").width
                        Cura.TextField
                        {
                            id: apiKey
                            width: Math.floor(parent.parent.width * (requestApiKey.visible ? 0.5 : 0.8) - UM.Theme.getSize("default_margin").width)
                            leftPadding: 0
                            rightPadding: 0
                            echoMode: activeFocus ? TextInput.Normal : TextInput.Password
                            onTextChanged: apiCheckDelay.throttledCheck()
                        }

                        Cura.SecondaryButton
                        {
                            id: requestApiKey
                            visible: manager.instanceSupportsAppKeys
                            enabled: !manager.instanceApiKeyAccepted
                            text: catalog.i18nc("@action", "Request...")
                            onClicked:
                            {
                                manager.requestApiKey(base.selectedInstance.getId());
                            }
                        }

                    }
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        text: catalog.i18nc("@label", "Username")
                    }
                    UM.Label
                    {
                        width: Math.floor(parent.width * 0.75)
                        text: base.selectedInstance ? base.selectedInstance.octoPrintUserName : ""
                    }

                    Connections
                    {
                        target: base
                        function onSelectedInstanceChanged()
                        {
                            if(base.selectedInstance)
                            {
                                manager.probeAppKeySupport(base.selectedInstance.getId());
                                apiCheckDelay.lastKey = "\0";
                                apiKey.text = manager.getApiKey(base.selectedInstance.getId());
                                apiKey.select(0,0);
                            }
                        }
                    }
                    Connections
                    {
                        target: manager
                        function onAppKeyReceived()
                        {
                            apiCheckDelay.lastKey = "\0";
                            apiKey.text = manager.getApiKey(base.selectedInstance.getId())
                            apiKey.select(0,0);
                        }
                    }
                    Timer
                    {
                        id: apiCheckDelay
                        interval: 500

                        property bool checkOnTrigger: false
                        property string lastKey: "\0"

                        function throttledCheck()
                        {
                            checkOnTrigger = true;
                            restart();
                        }
                        function check()
                        {
                            if(apiKey.text != lastKey)
                            {
                                lastKey = apiKey.text;
                                manager.testApiKey(base.selectedInstance.getId(), apiKey.text);
                                checkOnTrigger = false;
                                restart();
                            }
                        }
                        onTriggered:
                        {
                            if(checkOnTrigger)
                            {
                                check();
                            }
                        }
                    }
                }

                UM.Label
                {
                    visible: base.selectedInstance != null && text != ""
                    text:
                    {
                        var result = ""
                        if (apiKey.text == "")
                        {
                            result = catalog.i18nc("@label", "Please enter the API key to access OctoPrint.");
                        }
                        else
                        {
                            if(manager.instanceInError)
                            {
                                return catalog.i18nc("@label", "OctoPrint is not available.")
                            }
                            if(manager.instanceResponded)
                            {
                                if(manager.instanceApiKeyAccepted)
                                {
                                    return "";
                                }
                                else
                                {
                                    result = catalog.i18nc("@label", "The API key is invalid.");
                                }
                            }
                            else
                            {
                                return catalog.i18nc("@label", "Checking the API key...")
                            }
                        }
                        result += " " + catalog.i18nc("@label", "You can get the API key through the OctoPrint web page.");
                        return result;
                    }
                    width: parent.width - UM.Theme.getSize("default_margin").width
                }

                Column
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    spacing: UM.Theme.getSize("default_lining").height

                    UM.CheckBox
                    {
                        id: autoPrintCheckBox
                        text: catalog.i18nc("@label", "Start print job after uploading")
                        enabled: manager.instanceApiKeyAccepted
                        checked: Cura.ContainerManager.getContainerMetaDataEntry(activeMachineId, "octoprint_auto_print") != "false"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(activeMachineId, "octoprint_auto_print", String(checked))
                        }
                    }
                    UM.CheckBox
                    {
                        id: autoSelectCheckBox
                        text: catalog.i18nc("@label", "Select print job after uploading")
                        enabled: manager.instanceApiKeyAccepted && !autoPrintCheckBox.checked
                        checked: Cura.ContainerManager.getContainerMetaDataEntry(activeMachineId, "octoprint_auto_select") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(activeMachineId, "octoprint_auto_select", String(checked))
                        }
                    }
                    Row
                    {
                        spacing: UM.Theme.getSize("default_margin").width

                        UM.CheckBox
                        {
                            id: autoPowerControlCheckBox
                            text: catalog.i18nc("@label", "Turn on printer with")
                            visible: autoPowerControlPlugs.visible
                            enabled: autoPrintCheckBox.checked
                            anchors.verticalCenter: autoPowerControlPlugs.verticalCenter
                            checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(activeMachineId, "octoprint_power_control") == "true"
                            onClicked:
                            {
                                manager.setContainerMetaDataEntry(activeMachineId, "octoprint_power_control", String(checked))
                            }
                        }
                        Connections
                        {
                            target: manager
                            function onInstanceAvailablePowerPluginsChanged()
                            {
                                autoPowerControlPlugsModel.populateModel()
                            }
                        }

                        Cura.ComboBox
                        {
                            id: autoPowerControlPlugs
                            visible: manager.instanceApiKeyAccepted && model.count > 0
                            enabled: autoPrintCheckBox.checked
                            property bool populatingModel: false
                            textRole: "text"
                            model: ListModel
                            {
                                id: autoPowerControlPlugsModel

                                Component.onCompleted: populateModel()

                                function populateModel()
                                {
                                    autoPowerControlPlugs.populatingModel = true;
                                    clear();

                                    var current_index = -1;

                                    var power_plugs = manager.instanceAvailablePowerPlugins;
                                    var current_key = Cura.ContainerManager.getContainerMetaDataEntry(activeMachineId, "octoprint_power_plug");
                                    if (current_key == "" && power_plugs.length > 0)
                                    {
                                        current_key = power_plugs[0].key;
                                        manager.setContainerMetaDataEntry(activeMachineId, "octoprint_power_plug", current_key);
                                    }

                                    for(var i in power_plugs)
                                    {
                                        append({
                                            key: power_plugs[i].key,
                                            text: power_plugs[i].text
                                        });
                                        if(power_plugs[i].key == current_key)
                                        {
                                            current_index = i;
                                        }
                                    }
                                    if(current_index == -1 && current_key != "")
                                    {
                                        append({
                                            key: current_key,
                                            text: catalog.i18nc("@label", "Unknown plug")
                                        });
                                        current_index = count - 1;
                                    }

                                    autoPowerControlPlugs.currentIndex = current_index;
                                    autoPowerControlPlugs.populatingModel = false;
                                }
                            }
                            onActivated:
                            {
                                if(!populatingModel && model.get(index))
                                {
                                    manager.setContainerMetaDataEntry(activeMachineId, "octoprint_power_plug", model.get(index).key);
                                }
                            }

                        }
                    }
                    UM.CheckBox
                    {
                        id: autoConnectCheckBox
                        text: catalog.i18nc("@label", "Connect to printer before sending print job")
                        enabled: manager.instanceApiKeyAccepted && autoPrintCheckBox.checked && !autoPowerControlCheckBox.checked
                        checked: enabled && Cura.ContainerManager.getContainerMetaDataEntry(activeMachineId, "octoprint_auto_connect") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(activeMachineId, "octoprint_auto_connect", String(checked))
                        }
                    }
                    UM.CheckBox
                    {
                        id: storeOnSdCheckBox
                        text: catalog.i18nc("@label", "Store G-code on the SD card of the printer")
                        enabled: manager.instanceSupportsSd
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(activeMachineId, "octoprint_store_sd") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(activeMachineId, "octoprint_store_sd", String(checked))
                        }
                    }
                    UM.Label
                    {
                        visible: storeOnSdCheckBox.checked
                        width: parent.width
                        text: catalog.i18nc("@label", "Note: Transferring files to the printer SD card takes very long. Using this option is not recommended.")
                    }
                    UM.CheckBox
                    {
                        id: confirmUploadOptionsCheckBox
                        text: catalog.i18nc("@label", "Confirm print job options before sending")
                        checked: Cura.ContainerManager.getContainerMetaDataEntry(activeMachineId, "octoprint_confirm_upload_options") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(activeMachineId, "octoprint_confirm_upload_options", String(checked))
                        }
                    }
                    UM.CheckBox
                    {
                        id: showCameraCheckBox
                        text: catalog.i18nc("@label", "Show webcam image")
                        enabled: manager.instanceSupportsCamera
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(activeMachineId, "octoprint_show_camera") != "false"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(activeMachineId, "octoprint_show_camera", String(checked))
                        }
                    }
                    UM.CheckBox
                    {
                        id: fixGcodeFlavor
                        text: catalog.i18nc("@label", "Set G-code flavor to \"Marlin\"")
                        checked: true
                        visible: machineGCodeFlavorProvider.properties.value == "UltiGCode"
                    }
                    UM.Label
                    {
                        text: catalog.i18nc("@label", "Note: Printing UltiGCode using OctoPrint does not work. Setting G-code flavor to \"Marlin\" fixes this, but overrides material settings on your printer.")
                        width: parent.width - UM.Theme.getSize("default_margin").width
                        visible: fixGcodeFlavor.visible
                    }
                }

                Flow
                {
                    visible: base.selectedInstance != null
                    spacing: UM.Theme.getSize("default_margin").width

                    Cura.SecondaryButton
                    {
                        text: catalog.i18nc("@action", "Open in browser...")
                        onClicked: manager.openWebPage(base.selectedInstance.baseURL)
                    }

                    Cura.SecondaryButton
                    {
                        text:
                        {
                            if (base.selectedInstance !== null)
                            {
                                if (base.selectedInstance.getId() == manager.instanceId && manager.instanceApiKeyAccepted)
                                {
                                    return catalog.i18nc("@action:button", "Disconnect");
                                }
                            }
                            return  catalog.i18nc("@action:button", "Connect")
                        }
                        enabled: base.selectedInstance !== null && apiKey.text != "" && manager.instanceApiKeyAccepted
                        onClicked:
                        {
                            if(base.selectedInstance.getId() == manager.instanceId && manager.instanceApiKeyAccepted) {
                                manager.setInstanceId("")
                            }
                            else
                            {
                                manager.setInstanceId(base.selectedInstance.getId())
                                manager.setApiKey(apiKey.text)

                                if(fixGcodeFlavor.visible)
                                {
                                    manager.applyGcodeFlavorFix(fixGcodeFlavor.checked)
                                }
                            }
                            completed()
                        }
                    }
                }
            }
        }
    }

    UM.SettingPropertyProvider
    {
        id: machineGCodeFlavorProvider

        containerStackId: activeMachineId
        key: "machine_gcode_flavor"
        watchedProperties: [ "value" ]
        storeIndex: 4
    }

    ManualInstanceDialog
    {
        id: manualInstanceDialog
    }
}