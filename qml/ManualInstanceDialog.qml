// Copyright (c) 2022 Aldo Hoeben / fieldOfView
// OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import QtQuick 2.15
import QtQuick.Controls 2.0

import UM 1.5 as UM
import Cura 1.0 as Cura


UM.Dialog
{
    id: manualInstanceDialog
    property string previousName
    property string previousAddress
    property alias nameText: nameField.text
    property alias addressText: addressField.text
    property alias portText: portField.text
    property alias pathText: pathField.text
    property alias userNameText: userNameField.text
    property alias passwordText: passwordField.text
    property alias httpsChecked: httpsCheckbox.checked

    title: catalog.i18nc("@title:window", "Manually added OctoPrint instance")

    buttonSpacing: UM.Theme.getSize("default_margin").width
    minimumWidth: 400 * screenScaleFactor
    minimumHeight: 300 * screenScaleFactor
    width: minimumWidth
    height: minimumHeight

    property int firstColumnWidth: Math.floor(width * 0.4) - 2 * margin
    property int secondColumnWidth: Math.floor(width * 0.6) - 2 * margin

    signal showDialog(string name, string address, string port, string path_, bool useHttps, string userName, string password)
    onShowDialog: function(name, address, port, path_, useHttps, userName, password)
    {
        previousName = name;
        nameText = name;
        addressText = address;
        previousAddress = address;
        portText = port;
        pathText = path_;
        httpsChecked = useHttps;
        userNameText = userName;
        passwordText = password;

        manualInstanceDialog.show();
        if (nameText != "")
        {
            nameField.forceActiveFocus();
        }
        else
        {
            addressField.forceActiveFocus();
        }
    }

    onAccepted:
    {
        if(previousName != nameText)
        {
            manager.removeManualInstance(previousName);
        }
        if(portText == "")
        {
            portText = (!httpsChecked) ? base.defaultHTTP : base.defaultHTTPS; // default http or https port
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
            httpsChecked,
            userNameText,
            passwordText
        );
    }

    function parseAddressField()
    {
        var useAddressForName = false
        if (nameText == manualInstanceDialog.previousAddress || nameText == "")
        {
            useAddressForName = true
        }
        manualInstanceDialog.previousAddress = addressText

        var index = addressText.indexOf("://")
        if(index >= 0)
        {
            var protocol = addressText.substr(0,index)
            if(protocol.toLowerCase() == "http" && httpsChecked) {
                httpsChecked = false
                if(portField.text == defaultHTTPS)
                {
                    portField.text = defaultHTTP
                }
            }
            else if(protocol.toLowerCase() == "https" && !httpsChecked) {
                httpsChecked = true
                if(portField.text == defaultHTTP)
                {
                    portField.text = defaultHTTPS
                }
            }
            addressText = addressText.substr(index + 3)
        }

        index = addressText.indexOf("@")
        if(index >= 0)
        {
            var auth = addressText.substr(0,index).split(":")
            userNameText = auth[0]
            if(auth.length>1)
            {
                passwordText = auth[1]
            }
            addressText = addressText.substr(index+1)
        }

        index = addressText.indexOf("/")
        if(index >= 0)
        {
            pathField.text = addressText.substr(index)
            addressText = addressText.substr(0,index)
        }

        index = addressText.indexOf(":")
        if(index >= 0)
        {
            var port = parseInt(addressText.substr(index+1))
            if (!isNaN(port)) {
                portField.text = port.toString()
            }
            addressText = addressText.substr(0,index)
        }

        if(useAddressForName)
        {
            nameText = addressText
        }
    }

    Grid
    {
        Timer
        {
            id: parseAddressFieldTimer
            interval: 1000
            onTriggered: manualInstanceDialog.parseAddressField()
        }

        columns: 2
        width: parent.width
        verticalItemAlignment: Grid.AlignVCenter
        rowSpacing: UM.Theme.getSize("default_lining").height
        columnSpacing: UM.Theme.getSize("default_margin").width

        UM.Label
        {
            text: catalog.i18nc("@label","Instance Name")
            width: manualInstanceDialog.firstColumnWidth
        }

        Cura.TextField
        {
            id: nameField
            maximumLength: 20
            width: manualInstanceDialog.secondColumnWidth
            validator: RegularExpressionValidator
            {
                regularExpression: /[a-zA-Z0-9\.\-\_\:\[\]]*/
            }
        }

        UM.Label
        {
            text: catalog.i18nc("@label","IP Address or Hostname")
            width: manualInstanceDialog.firstColumnWidth
        }

        Cura.TextField
        {
            id: addressField
            maximumLength: 253
            width: manualInstanceDialog.secondColumnWidth
            validator: RegularExpressionValidator
            {
                regularExpression: /[a-zA-Z0-9\.\-\_\:\/\@]*/
            }
            onTextChanged: parseAddressFieldTimer.restart()
        }

        UM.Label
        {
            text: catalog.i18nc("@label","Port Number")
            width: manualInstanceDialog.firstColumnWidth
        }

        Cura.TextField
        {
            id: portField
            maximumLength: 5
            width: manualInstanceDialog.secondColumnWidth
            validator: RegularExpressionValidator
            {
                regularExpression: /[0-9]*/
            }
            onTextChanged:
            {
                if(httpsChecked && text == base.defaultHTTP)
                {
                    httpsChecked = false
                }
                else if(!httpsChecked && text == base.defaultHTTPS)
                {
                    httpsChecked = true
                }
            }
        }

        UM.Label
        {
            text: catalog.i18nc("@label","Path")
            width: manualInstanceDialog.firstColumnWidth
        }

        Cura.TextField
        {
            id: pathField
            maximumLength: 30
            width: manualInstanceDialog.secondColumnWidth
            validator: RegularExpressionValidator
            {
                regularExpression: /[a-zA-Z0-9\.\-\_\/]*/
            }
        }

        Item
        {
            width: 1
            height: UM.Theme.getSize("default_margin").height
        }

        Item
        {
            width: 1
            height: UM.Theme.getSize("default_margin").height
        }

        Item
        {
            width: 1
            height: 1
        }

        UM.Label
        {
            wrapMode: Text.WordWrap
            width: manualInstanceDialog.secondColumnWidth
            text: catalog.i18nc("@label","In order to use HTTPS or a HTTP username and password, you need to configure a reverse proxy or another service.")
        }

        UM.Label
        {
            text: catalog.i18nc("@label","Use HTTPS")
            width: manualInstanceDialog.firstColumnWidth
        }

        UM.CheckBox
        {
            id: httpsCheckbox
            width: height
            height: userNameField.height
            onClicked:
            {
                if(checked && portField.text == base.defaultHTTP)
                {
                    portField.text = base.defaultHTTPS
                }
                else if(!checked && portField.text == base.defaultHTTPS)
                {
                    portField.text = base.defaultHTTP
                }
            }
        }

        UM.Label
        {
            text: catalog.i18nc("@label","HTTP username")
            width: manualInstanceDialog.firstColumnWidth
        }

        Cura.TextField
        {
            id: userNameField
            maximumLength: 64
            width: manualInstanceDialog.secondColumnWidth
        }

        UM.Label
        {
            text: catalog.i18nc("@label","HTTP password")
            width: manualInstanceDialog.firstColumnWidth
        }

        Cura.TextField
        {
            id: passwordField
            maximumLength: 64
            width: manualInstanceDialog.secondColumnWidth
            echoMode: TextInput.PasswordEchoOnEdit
        }
    }

    rightButtons: [
        Cura.SecondaryButton {
            text: catalog.i18nc("@action:button","Cancel")
            onClicked:
            {
                manualInstanceDialog.reject()
                manualInstanceDialog.hide()
            }
        },
        Cura.PrimaryButton {
            text: catalog.i18nc("@action:button", "Ok")
            onClicked:
            {
                if (parseAddressFieldTimer.running)
                {
                    parseAddressFieldTimer.stop()
                    manualInstanceDialog.parseAddressField()
                }
                manualInstanceDialog.accept()
                manualInstanceDialog.hide()
            }
            enabled: manualInstanceDialog.nameText.trim() != "" && manualInstanceDialog.addressText.trim() != ""
        }
    ]
}