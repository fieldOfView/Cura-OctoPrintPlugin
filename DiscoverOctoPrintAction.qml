// Copyright (c) 2019 Aldo Hoeben / fieldOfView
// OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import UM 1.2 as UM
import Cura 1.0 as Cura

import QtQuick 2.2
import QtQuick.Controls 1.1
import QtQuick.Layouts 1.1
import QtQuick.Window 2.1

Cura.MachineAction
{
    id: base
    anchors.fill: parent;
    property var selectedInstance: null

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

        SystemPalette { id: palette }
        UM.I18nCatalog { id: catalog; name:"cura" }

        Item
        {
            width: parent.width
            height: pageTitle.height

            Label
            {
                id: pageTitle
                text: catalog.i18nc("@title", "Connect to OctoPrint")
                wrapMode: Text.WordWrap
                font.pointSize: 18
            }

            Label
            {
                id: pluginVersion
                anchors.bottom: pageTitle.bottom
                anchors.right: parent.right
                text: manager.pluginVersion
                wrapMode: Text.WordWrap
                font.pointSize: 8
            }
        }

        Label
        {
            id: pageDescription
            width: parent.width
            wrapMode: Text.WordWrap
            text: catalog.i18nc("@label", "Select your OctoPrint instance from the list below.")
        }

        Row
        {
            spacing: UM.Theme.getSize("default_lining").width

            Button
            {
                id: addButton
                text: catalog.i18nc("@action:button", "Add");
                onClicked:
                {
                    manualPrinterDialog.showDialog("", "", "80", "/", false, "", "");
                }
            }

            Button
            {
                id: editButton
                text: catalog.i18nc("@action:button", "Edit")
                enabled: base.selectedInstance != null && base.selectedInstance.getProperty("manual") == "true"
                onClicked:
                {
                    manualPrinterDialog.showDialog(
                        base.selectedInstance.name, base.selectedInstance.ipAddress,
                        base.selectedInstance.port, base.selectedInstance.path,
                        base.selectedInstance.getProperty("useHttps") == "true",
                        base.selectedInstance.getProperty("userName"), base.selectedInstance.getProperty("password")
                    );
                }
            }

            Button
            {
                id: removeButton
                text: catalog.i18nc("@action:button", "Remove")
                enabled: base.selectedInstance != null && base.selectedInstance.getProperty("manual") == "true"
                onClicked: manager.removeManualInstance(base.selectedInstance.name)
            }

            Button
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

            Item
            {
                width: Math.floor(parent.width * 0.5)
                height: base.height - parent.y

                ScrollView
                {
                    id: objectListContainer
                    frameVisible: true
                    width: parent.width
                    anchors.top: parent.top
                    anchors.bottom: objectListFooter.top
                    anchors.bottomMargin: UM.Theme.getSize("default_margin").height

                    Rectangle
                    {
                        parent: viewport
                        anchors.fill: parent
                        color: palette.light
                    }

                    ListView
                    {
                        id: listview
                        model: manager.discoveredInstances
                        onModelChanged:
                        {
                            var selectedId = manager.getInstanceId();
                            for(var i = 0; i < model.length; i++) {
                                if(model[i].getId() == selectedId)
                                {
                                    currentIndex = i;
                                    return
                                }
                            }
                            currentIndex = -1;
                        }
                        width: parent.width
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
                            color: ListView.isCurrentItem ? palette.highlight : index % 2 ? palette.base : palette.alternateBase
                            width: parent.width
                            Label
                            {
                                anchors.left: parent.left
                                anchors.leftMargin: UM.Theme.getSize("default_margin").width
                                anchors.right: parent.right
                                text: listview.model[index].name
                                color: parent.ListView.isCurrentItem ? palette.highlightedText : palette.text
                                elide: Text.ElideRight
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
                }

                Item
                {
                    id: objectListFooter

                    width: parent.width
                    anchors.bottom: parent.bottom

                    CheckBox
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
                width: Math.floor(parent.width * 0.5)
                spacing: UM.Theme.getSize("default_margin").height
                Label
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: base.selectedInstance ? base.selectedInstance.name : ""
                    font.pointSize: 16
                    elide: Text.ElideRight
                }
                Grid
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    columns: 2
                    rowSpacing: UM.Theme.getSize("default_lining").height
                    verticalItemAlignment: Grid.AlignVCenter
                    Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "Version")
                    }
                    Label
                    {
                        width: Math.floor(parent.width * 0.75)
                        wrapMode: Text.WordWrap
                        text: base.selectedInstance ? base.selectedInstance.octoprintVersion : ""
                    }
                    Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "Address")
                    }
                    Label
                    {
                        width: Math.floor(parent.width * 0.7)
                        wrapMode: Text.WordWrap
                        text: base.selectedInstance ? "%1:%2".arg(base.selectedInstance.ipAddress).arg(String(base.selectedInstance.port)) : ""
                    }
                    Label
                    {
                        width: Math.floor(parent.width * 0.2)
                        wrapMode: Text.WordWrap
                        text: catalog.i18nc("@label", "API Key")
                    }
                    Row
                    {
                        spacing: UM.Theme.getSize("default_lining").width
                        TextField
                        {
                            id: apiKey
                            width: Math.floor(parent.parent.width * (requestApiKey.visible ? 0.5 : 0.8) - UM.Theme.getSize("default_margin").width)
                            onTextChanged: apiCheckDelay.throttledCheck()
                        }

                        Button
                        {
                            id: requestApiKey
                            visible: manager.instanceSupportsAppKeys
                            enabled: !manager.instanceApiKeyAccepted
                            text: catalog.i18nc("@action", "Request...")
                            onClicked:
                            {
                                manager.requestApiKey(
                                    base.selectedInstance.getId(),
                                    base.selectedInstance.baseURL,
                                    base.selectedInstance.getProperty("userName"),
                                    base.selectedInstance.getProperty("password")
                                );
                                manager.openWebPage(base.selectedInstance.baseURL);
                            }
                        }

                    }
                    Connections
                    {
                        target: base
                        onSelectedInstanceChanged:
                        {
                            if(base.selectedInstance)
                            {
                                manager.probeAppKeySupport(
                                    base.selectedInstance.baseURL,
                                    base.selectedInstance.getProperty("userName"),
                                    base.selectedInstance.getProperty("password")
                                );
                                apiCheckDelay.lastKey = "\0";
                                apiKey.text = manager.getApiKey(base.selectedInstance.getId());
                            }
                        }
                    }
                    Connections
                    {
                        target: manager
                        onAppKeyReceived:
                        {
                            apiCheckDelay.lastKey = "\0";
                            apiKey.text = manager.getApiKey(base.selectedInstance.getId())
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
                                manager.testApiKey(
                                    base.selectedInstance.baseURL,
                                    apiKey.text,
                                    base.selectedInstance.getProperty("userName"),
                                    base.selectedInstance.getProperty("password")
                                );
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

                Label
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
                                    result = catalog.i18nc("@label", "The API key is not valid.");
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
                    wrapMode: Text.WordWrap
                }

                Column
                {
                    visible: base.selectedInstance != null
                    width: parent.width
                    spacing: UM.Theme.getSize("default_lining").height

                    CheckBox
                    {
                        id: autoPrintCheckBox
                        text: catalog.i18nc("@label", "Automatically start print job after uploading")
                        enabled: manager.instanceApiKeyAccepted
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachineId, "octoprint_auto_print") != "false"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachineId, "octoprint_auto_print", String(checked))
                        }
                    }
                    CheckBox
                    {
                        id: showCameraCheckBox
                        text: catalog.i18nc("@label", "Show webcam image")
                        enabled: manager.instanceSupportsCamera
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachineId, "octoprint_show_camera") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachineId, "octoprint_show_camera", String(checked))
                        }
                    }
                    CheckBox
                    {
                        id: storeOnSdCheckBox
                        text: catalog.i18nc("@label", "Store G-code on the printer SD card")
                        enabled: manager.instanceSupportsSd
                        checked: manager.instanceApiKeyAccepted && Cura.ContainerManager.getContainerMetaDataEntry(Cura.MachineManager.activeMachineId, "octoprint_store_sd") == "true"
                        onClicked:
                        {
                            manager.setContainerMetaDataEntry(Cura.MachineManager.activeMachineId, "octoprint_store_sd", String(checked))
                        }
                    }
                    Label
                    {
                        visible: storeOnSdCheckBox.checked
                        wrapMode: Text.WordWrap
                        width: parent.width
                        text: catalog.i18nc("@label", "Note: Transfering files to the printer SD card takes very long. Using this option is not recommended.")
                    }
                    CheckBox
                    {
                        id: fixGcodeFlavor
                        text: catalog.i18nc("@label", "Set Gcode flavor to \"Marlin\"")
                        checked: true
                        visible: machineGCodeFlavorProvider.properties.value == "UltiGCode"
                    }
                    Label
                    {
                        text: catalog.i18nc("@label", "Note: Printing UltiGCode using OctoPrint does not work. Setting Gcode flavor to \"Marlin\" fixes this, but overrides material settings on your printer.")
                        width: parent.width - UM.Theme.getSize("default_margin").width
                        wrapMode: Text.WordWrap
                        visible: fixGcodeFlavor.visible
                    }
                }

                Flow
                {
                    visible: base.selectedInstance != null
                    spacing: UM.Theme.getSize("default_margin").width

                    Button
                    {
                        text: catalog.i18nc("@action", "Open in browser...")
                        onClicked: manager.openWebPage(base.selectedInstance.baseURL)
                    }

                    Button
                    {
                        text: catalog.i18nc("@action:button", "Connect")
                        enabled: apiKey.text != "" && manager.instanceApiKeyAccepted
                        onClicked:
                        {
                            if(fixGcodeFlavor.visible)
                            {
                                manager.applyGcodeFlavorFix(fixGcodeFlavor.checked)
                            }
                            manager.setInstanceId(base.selectedInstance.getId())
                            manager.setApiKey(apiKey.text)
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

        containerStackId: Cura.MachineManager.activeMachineId
        key: "machine_gcode_flavor"
        watchedProperties: [ "value" ]
        storeIndex: 4
    }

    UM.Dialog
    {
        id: manualPrinterDialog
        property string oldName
        property alias nameText: nameField.text
        property alias addressText: addressField.text
        property alias portText: portField.text
        property alias pathText: pathField.text
        property alias userNameText: userNameField.text
        property alias passwordText: passwordField.text

        title: catalog.i18nc("@title:window", "Manually added OctoPrint instance")

        minimumWidth: 400 * screenScaleFactor
        minimumHeight: (showAdvancedOptions.checked ? 280 : 160) * screenScaleFactor
        width: minimumWidth
        height: minimumHeight

        signal showDialog(string name, string address, string port, string path_, bool useHttps, string userName, string password)
        onShowDialog:
        {
            oldName = name;
            nameText = name;
            nameField.selectAll();
            nameField.focus = true;

            addressText = address;
            portText = port;
            pathText = path_;
            httpsCheckbox.checked = useHttps;
            userNameText = userName;
            passwordText = password;

            manualPrinterDialog.show();
        }

        onAccepted:
        {
            if(oldName != nameText)
            {
                manager.removeManualInstance(oldName);
            }
            if(portText == "")
            {
                portText = "80"; // default http port
            }
            if(pathText.substr(0,1) != "/")
            {
                pathText = "/" + pathText; // ensure absolute path
            }
            manager.setManualInstance(
                nameText,
                addressText,
                parseInt(portText),
                pathText,
                httpsCheckbox.checked,
                userNameText,
                passwordText
            );
        }

        Column {
            anchors.fill: parent
            spacing: UM.Theme.getSize("default_margin").height

            Grid
            {
                columns: 2
                width: parent.width
                verticalItemAlignment: Grid.AlignVCenter
                rowSpacing: UM.Theme.getSize("default_lining").height

                Label
                {
                    text: catalog.i18nc("@label","Instance Name")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: nameField
                    maximumLength: 20
                    width: Math.floor(parent.width * 0.6)
                    validator: RegExpValidator
                    {
                        regExp: /[a-zA-Z0-9\.\-\_]*/
                    }
                }

                Label
                {
                    text: catalog.i18nc("@label","IP Address or Hostname")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: addressField
                    maximumLength: 30
                    width: Math.floor(parent.width * 0.6)
                    validator: RegExpValidator
                    {
                        regExp: /[a-zA-Z0-9\.\-\_]*/
                    }
                }

                Label
                {
                    text: catalog.i18nc("@label","Port Number")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: portField
                    maximumLength: 5
                    width: Math.floor(parent.width * 0.6)
                    validator: RegExpValidator
                    {
                        regExp: /[0-9]*/
                    }
                }

                Label
                {
                    text: catalog.i18nc("@label","Path")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: pathField
                    maximumLength: 30
                    width: Math.floor(parent.width * 0.6)
                    validator: RegExpValidator
                    {
                        regExp: /[a-zA-Z0-9\.\-\_\/]*/
                    }
                }
            }

            CheckBox
            {
                id: showAdvancedOptions
                text: catalog.i18nc("@label","Show reverse proxy options (advanced)")
            }

            Grid
            {
                columns: 2
                visible: showAdvancedOptions.checked
                width: parent.width
                verticalItemAlignment: Grid.AlignVCenter
                rowSpacing: UM.Theme.getSize("default_lining").height

                Label
                {
                    text: catalog.i18nc("@label","Use HTTPS")
                    width: Math.floor(parent.width * 0.4)
                }

                CheckBox
                {
                    id: httpsCheckbox
                }

                Label
                {
                    text: catalog.i18nc("@label","HTTP user name")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: userNameField
                    maximumLength: 64
                    width: Math.floor(parent.width * 0.6)
                }

                Label
                {
                    text: catalog.i18nc("@label","HTTP password")
                    width: Math.floor(parent.width * 0.4)
                }

                TextField
                {
                    id: passwordField
                    maximumLength: 64
                    width: Math.floor(parent.width * 0.6)
                    echoMode: TextInput.PasswordEchoOnEdit
                }


            }

            Label
            {
                visible: showAdvancedOptions.checked
                wrapMode: Text.WordWrap
                width: parent.width
                text: catalog.i18nc("@label","NB: Only use these options if you access OctoPrint through a reverse proxy.")
            }
        }

        rightButtons: [
            Button {
                text: catalog.i18nc("@action:button","Cancel")
                onClicked:
                {
                    manualPrinterDialog.reject()
                    manualPrinterDialog.hide()
                }
            },
            Button {
                text: catalog.i18nc("@action:button", "Ok")
                onClicked:
                {
                    manualPrinterDialog.accept()
                    manualPrinterDialog.hide()
                }
                enabled: manualPrinterDialog.nameText.trim() != "" && manualPrinterDialog.addressText.trim() != ""
                isDefault: true
            }
        ]
    }
}