project(OctoPrintPlugin NONE)
cmake_minimum_required(VERSION 2.8.12)

install(FILES
    __init__.py
    plugin.json
    DiscoverOctoPrintAction.py
    OctoPrintOutputDevice.py
    OctoPrintOutputDevicePlugin.py
    OctoPrintPowerPlugins.py
    NetworkReplyTimeout.py
    NetworkMJPGImage.py
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

install(FILES
    python-zeroconf/README.rst
    python-zeroconf/COPYING
    DESTINATION lib/cura/plugins/OctoPrintPlugin/python-zeroconf
)

install(FILES
    python-zeroconf/zeroconf/__init__.py
    DESTINATION lib/cura/plugins/OctoPrintPlugin/python-zeroconf/zeroconf
)