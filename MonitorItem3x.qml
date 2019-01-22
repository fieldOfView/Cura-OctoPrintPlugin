// Copyright (c) 2019 Aldo Hoeben / fieldOfView
// OctoPrintPlugin is released under the terms of the AGPLv3 or higher.

import QtQuick 2.2
import OctoPrintPlugin 1.0 as OctoPrintPlugin

Component
{
    Item
    {
        OctoPrintPlugin.NetworkMJPGImage
        {
            id: cameraImage
            visible: OutputDevice != null ? OutputDevice.showCamera : false

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
            source: OutputDevice.cameraUrl

            rotation: OutputDevice.cameraOrientation.rotation
            mirror: OutputDevice.cameraOrientation.mirror
        }
    }
}