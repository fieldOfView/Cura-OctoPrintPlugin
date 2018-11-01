project(OctoPrintPlugin NONE)
cmake_minimum_required(VERSION 2.8.12)

install(FILES
    __init__.py
    plugin.json
    DiscoverOctoPrintAction.py
    DiscoverOctoPrintAction.qml
    OctoPrintComponents.qml
    OctoPrintOutputDevice.py
    OctoPrintOutputDevicePlugin.py
    NetworkMJPGImage.py
    MonitorItem.qml
    LICENSE
    README.md
    DESTINATION lib/cura/plugins/OctoPrintPlugin
)
