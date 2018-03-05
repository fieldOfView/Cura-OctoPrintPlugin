import QtQuick 2.2

Component
{
    Item
    {
        Image
        {
            id: cameraImage
            property real maximumZoom: 2
            property bool rotatedImage: (OutputDevice.cameraOrientation.rotation / 90) % 2
            property bool proportionalHeight:
            {
                if (sourceSize.height == 0 || maximumHeight == 0)
                {
                    return true;
                }
                if (!rotatedImage)
                {
                    return (sourceSize.width / sourceSize.height) > (maximumWidth / maximumHeight);
                }
                else
                {
                    return (sourceSize.width / sourceSize.height) > (maximumHeight / maximumWidth);
                }
            }
            property real _width:
            {
                if (!rotatedImage)
                {
                    return Math.min(maximumWidth, sourceSize.width * screenScaleFactor * maximumZoom);
                }
                else
                {
                    return Math.min(maximumHeight, sourceSize.width * screenScaleFactor * maximumZoom);
                }
            }
            property real _height:
            {
                if (!rotatedImage)
                {
                    return Math.min(maximumHeight, sourceSize.height * screenScaleFactor * maximumZoom);
                }
                else
                {
                    return Math.min(maximumWidth, sourceSize.height * screenScaleFactor * maximumZoom);
                }
            }
            width: proportionalHeight ? _width : sourceSize.width * _height / sourceSize.height
            height: !proportionalHeight ? _height : sourceSize.height * _width / sourceSize.width
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.verticalCenter: parent.verticalCenter

            Component.onCompleted:
            {
                if (visible && OutputDevice.activePrinter != null && OutputDevice.activePrinter.camera != null)
                {
                        OutputDevice.activePrinter.camera.start();
                }
            }
            onVisibleChanged:
            {
                if (OutputDevice.activePrinter != null && OutputDevice.activePrinter.camera != null)
                {
                    if (visible)
                    {
                        OutputDevice.activePrinter.camera.start();
                    } else
                    {
                        OutputDevice.activePrinter.camera.stop();
                    }
                }
            }
            source:
            {
                if(OutputDevice.activePrinter != null && OutputDevice.activePrinter.camera != null && OutputDevice.activePrinter.camera.latestImage)
                {
                    return OutputDevice.activePrinter.camera.latestImage;
                }
                return "";
            }

            rotation: OutputDevice.cameraOrientation.rotation
            mirror: OutputDevice.cameraOrientation.mirror
        }
    }
}