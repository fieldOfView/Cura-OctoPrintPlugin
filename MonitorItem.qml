import QtQuick 2.2

Component
{
    Image
    {
        id: cameraImage
        width: sourceSize.width
        height: sourceSize.height * width / sourceSize.width
        anchors.horizontalCenter: parent.horizontalCenter

        onVisibleChanged:
        {
            if(visible)
            {
                OutputDevice.startCamera()
            } else
            {
                OutputDevice.stopCamera()
            }
        }
        source:
        {
            if(OutputDevice.cameraImage)
            {
                return OutputDevice.cameraImage;
            }
            return "";
        }

        rotation: OutputDevice.cameraOrientation.rotation
        mirror: OutputDevice.cameraOrientation.mirror
    }
}