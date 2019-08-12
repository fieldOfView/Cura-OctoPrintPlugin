// Copyright (c) 2019 Aldo Hoeben / fieldOfView
// OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import QtQuick 2.2
import UM 1.2 as UM
import Cura 1.0 as Cura
import OctoPrintPlugin 1.0 as OctoPrintPlugin

Component
{
    id: monitorItem

    Item
    {
        OctoPrintPlugin.NetworkMJPGImage
        {
            id: cameraImage
            visible: OutputDevice != null ? OutputDevice.showCamera : false

            property real maximumWidthMinusSidebar: maximumWidth - sidebar.width - 2 * UM.Theme.getSize("default_margin").width
            property real maximumZoom: 2
            property bool rotatedImage: (OutputDevice.cameraOrientation.rotation / 90) % 2
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
            source: OutputDevice.cameraUrl

            rotation: OutputDevice.cameraOrientation.rotation
            mirror: OutputDevice.cameraOrientation.mirror
        }

        Item
        {
            id: horizontalCenterItem
            anchors.left: parent.left
            anchors.right: sidebar.left
        }

        Cura.RoundedRectangle
        {
            id: sidebar

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

            Cura.PrintMonitor {
                width: parent.width
                anchors
                {
                    left: parent.left
                    leftMargin: UM.Theme.getSize("default_margin").width
                    right: parent.right
                    rightMargin: UM.Theme.getSize("default_margin").width
                }
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

            width: UM.Theme.getSize("print_setup_widget").width
            height: monitorButton.height + UM.Theme.getSize("default_margin").height

            // MonitorButton is actually the bottom footer panel.
            Cura.MonitorButton
            {
                id: monitorButton
                width: parent.width
                anchors.top: parent.top
                anchors.topMargin: UM.Theme.getSize("default_margin").height
            }
        }
    }
}