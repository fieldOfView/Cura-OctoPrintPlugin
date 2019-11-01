project(OctoPrintPlugin NONE)
cmake_minimum_required(VERSION 2.8.12)

install(FILES
    __init__.py
    plugin.json
    DiscoverOctoPrintAction.py
    OctoPrintOutputDevice.py
    OctoPrintOutputDevicePlugin.py
    NetworkMJPGImage.py
    zeroconf.py
    LICENSE
    README.md
    DESTINATION lib/cura/plugins/OctoPrintPlugin
)

install(FILES
    qml/DiscoverOctoPrintAction.qml
    qml/OctoPrintComponents.qml
    qml/MonitorItem3x.qml
    qml/MonitorItem4x.qml
    DESTINATION lib/cura/plugins/OctoPrintPlugin/qml
)
