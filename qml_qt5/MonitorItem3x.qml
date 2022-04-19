// Copyright (c) 2022 Aldo Hoeben / fieldOfView
// OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import QtQuick 2.7
import QtQuick.Controls 2.3

import UM 1.3 as UM
import OctoPrintPlugin 1.0 as OctoPrintPlugin

Component
{
    Item
    {
        property var webcamsModel: OutputDevice != null ? OutputDevice.webcamsModel : null
        property int activeIndex: 0

        OctoPrintPlugin.NetworkMJPGImage
        {
            id: cameraImage
            visible: OutputDevice != null ? OutputDevice.showCamera : false

            source: (OutputDevice != null && activeIndex in webcamsModel.items) ? webcamsModel.items[activeIndex].stream_url : ""
            rotation: (OutputDevice != null && activeIndex in webcamsModel.items) ? webcamsModel.items[activeIndex].rotation : 0
            mirror: (OutputDevice != null && activeIndex in webcamsModel.items) ? webcamsModel.items[activeIndex].mirror : false

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
                    return (imageWidth / imageHeight) > (maximumWidth / maximumHeight);
                }
                else
                {
                    return (imageWidth / imageHeight) > (maximumHeight / maximumWidth);
                }
            }
            property real _width:
            {
                if (!rotatedImage)
                {
                    return Math.min(maximumWidth, imageWidth * screenScaleFactor * maximumZoom);
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
            anchors.horizontalCenter: parent.horizontalCenter
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
            visible: (webcamsModel != null) ? webcamsModel.rowCount() > 1 : false

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

                delegate: Button
                {
                    id: control
                    text: model != null ? model.name : ""
                    checkable: true
                    checked: cameraImage.source == model.stream_url

                    anchors.verticalCenter: parent.verticalCenter
                    ButtonGroup.group: webcamSelectorGroup
                    height: UM.Theme.getSize("sidebar_header_mode_toggle").height

                    background: Rectangle
                    {
                        color: (control.checked || control.pressed) ? UM.Theme.getColor("action_button_active") : control.hovered ? UM.Theme.getColor("action_button_hovered") : UM.Theme.getColor("action_button")
                        border.width: control.checked ? UM.Theme.getSize("default_lining").width * 2 : UM.Theme.getSize("default_lining").width
                        border.color: (control.checked || control.pressed) ? UM.Theme.getColor("action_button_active_border") : control.hovered ? UM.Theme.getColor("action_button_hovered_border"): UM.Theme.getColor("action_button_border")
                    }

                    contentItem: Label
                    {
                        text: control.text
                        font: UM.Theme.getFont("default")
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                        renderType: Text.NativeRendering
                        elide: Text.ElideRight
                        color: (control.pressed) ? UM.Theme.getColor("action_button_active_text") : (control.hovered) ?  UM.Theme.getColor("action_button_hovered_text") : UM.Theme.getColor("action_button_text");
                    }

                    onClicked: activeIndex = index
                }
            }

            ButtonGroup { id: webcamSelectorGroup }
        }
    }
}