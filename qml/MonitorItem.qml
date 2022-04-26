// Copyright (c) 2022 Aldo Hoeben / fieldOfView
// OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import QtQuick 2.10
import QtQuick.Controls 2.3

import UM 1.5 as UM
import Cura 1.1 as Cura
import OctoPrintPlugin 1.0 as OctoPrintPlugin

Component
{
    id: monitorItem

    Item
    {
        property var webcamsModel: OutputDevice != null ? OutputDevice.webcamsModel : null
        property int activeIndex: 0

        OctoPrintPlugin.NetworkMJPGImage
        {
            id: cameraImage
            visible: OutputDevice != null ? OutputDevice.showCamera : false

            source: (OutputDevice != null && activeIndex < webcamsModel.count) ? webcamsModel.items[activeIndex].stream_url : ""
            rotation: (OutputDevice != null && activeIndex < webcamsModel.count) ? webcamsModel.items[activeIndex].rotation : 0
            mirror: (OutputDevice != null && activeIndex < webcamsModel.count) ? webcamsModel.items[activeIndex].mirror : false

            property real maximumWidthMinusSidebar: maximumWidth - sidebar.width - 2 * UM.Theme.getSize("default_margin").width
            property real maximumZoom: 2
            property bool rotatedImage: (rotation / 90) % 2
            property bool proportionalHeight:
            {
                if (imageHeight == 0 || maximumHeight == 0)
                {
                    return true;
                }
                if (!rotatedImage)
                {
                    return (imageWidth / imageHeight) > (maximumWidthMinusSidebar / maximumHeight);
                }
                else
                {
                    return (imageWidth / imageHeight) > (maximumHeight / maximumWidthMinusSidebar);
                }
            }
            property real _width:
            {
                if (!rotatedImage)
                {
                    return Math.min(maximumWidthMinusSidebar, imageWidth * screenScaleFactor * maximumZoom);
                }
                else
                {
                    return Math.min(maximumHeight, imageWidth * screenScaleFactor * maximumZoom);
                }
            }
            property real _height:
            {
                if (!rotatedImage)
                {
                    return Math.min(maximumHeight, imageHeight * screenScaleFactor * maximumZoom);
                }
                else
                {
                    return Math.min(maximumWidth, imageHeight * screenScaleFactor * maximumZoom);
                }
            }
            width: proportionalHeight ? _width : imageWidth * _height / imageHeight
            height: !proportionalHeight ? _height : imageHeight * _width / imageWidth
            anchors.horizontalCenter: horizontalCenterItem.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter

            Component.onCompleted:
            {
                if (visible)
                {
                    start();
                }
            }
            onVisibleChanged:
            {
                if (visible)
                {
                    start();
                } else
                {
                    stop();
                }
            }
        }

        Row
        {
            id: webcamSelectorContainer
            spacing: Math.round(UM.Theme.getSize("default_margin").width / 2)
            visible: (webcamsModel != null) ? webcamsModel.count > 1 : false

            anchors
            {
                horizontalCenter: cameraImage.horizontalCenter
                top: cameraImage.top
                topMargin: UM.Theme.getSize("default_margin").height
            }

            Repeater
            {
                id: webcamSelector
                model: webcamsModel

                delegate: Cura.ActionButton
                {
                    id: control
                    text: model.name.toUpperCase()
                    checkable: true
                    checked: cameraImage.source == model.stream_url

                    anchors.verticalCenter: parent.verticalCenter
                    ButtonGroup.group: webcamSelectorGroup
                    height: UM.Theme.getSize("setting_control").height

                    onClicked: activeIndex = index

                    background: Rectangle
                    {
                        implicitHeight: control.height
                        radius: UM.Theme.getSize("action_button_radius").width

                        color: (control.checked) ? UM.Theme.getColor("main_window_header_button_background_active") : UM.Theme.getColor("main_window_header_button_background_hovered")
                        opacity: (control.checked || control.hovered) ? 1 : 0.5
                    }

                    contentItem: UM.Label
                    {
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.verticalCenter: parent.verticalCenter
                        height: control.height

                        text: control.text
                        font: UM.Theme.getFont("medium")
                        color: (control.checked) ? UM.Theme.getColor("main_window_header_button_text_active") : (control.hovered) ? UM.Theme.getColor("main_window_header_button_text_hovered") : UM.Theme.getColor("main_window_header_button_text_inactive")
                    }
                }
            }

            ButtonGroup { id: webcamSelectorGroup }
        }

        Item
        {
            id: horizontalCenterItem
            anchors.left: parent.left
            anchors.right: sidebar.left
        }

        Cura.RoundedRectangle
        {
            id: sidebarBackground

            width: UM.Theme.getSize("print_setup_widget").width
            anchors
            {
                right: parent.right
                top: parent.top
                topMargin: UM.Theme.getSize("default_margin").height
                bottom: actionsPanel.top
                bottomMargin: UM.Theme.getSize("default_margin").height
            }

            border.width: UM.Theme.getSize("default_lining").width
            border.color: UM.Theme.getColor("lining")
            color: UM.Theme.getColor("main_background")

            cornerSide: Cura.RoundedRectangle.Direction.Left
            radius: UM.Theme.getSize("default_radius").width
        }

        Cura.PrintMonitor {
            id: sidebar

            width: UM.Theme.getSize("print_setup_widget").width - UM.Theme.getSize("default_margin").height * 2
            anchors
            {
                top: parent.top
                bottom: actionsPanel.top
                leftMargin: UM.Theme.getSize("default_margin").width
                right: parent.right
                rightMargin: UM.Theme.getSize("default_margin").width
            }
        }

        Cura.RoundedRectangle
        {
            id: actionsPanel

            border.width: UM.Theme.getSize("default_lining").width
            border.color: UM.Theme.getColor("lining")
            color: UM.Theme.getColor("main_background")

            cornerSide: Cura.RoundedRectangle.Direction.Left
            radius: UM.Theme.getSize("default_radius").width

            anchors.bottom: parent.bottom
            anchors.right: parent.right

            anchors.bottomMargin: UM.Theme.getSize("default_margin").width
            anchors.topMargin: UM.Theme.getSize("default_margin").height

            width: UM.Theme.getSize("print_setup_widget").width
            height: monitorButton.height

            // MonitorButton is actually the bottom footer panel.
            Cura.MonitorButton
            {
                id: monitorButton
                width: parent.width
                anchors.top: parent.top
            }
        }
    }
}