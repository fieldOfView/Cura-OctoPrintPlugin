project(OctoPrintPlugin NONE)
cmake_minimum_required(VERSION 2.8.12)

install(FILES
    __init__.py
    plugin.json
    DiscoverOctoPrintAction.py
    OctoPrintOutputDevicePlugin.py
    OctoPrintOutputDevice.py
    OctoPrintOutputController.py
    NetworkReplyTimeout.py
    NetworkMJPGImage.py
    PowerPlugins.py
    WebcamsModel.py
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

install(FILES
    ifaddr/README.rst
    ifaddr/LICENSE.txt
    DESTINATION lib/cura/plugins/OctoPrintPlugin/ifaddr
)

install(FILES
    ifaddr/ifaddr/__init__.py
    ifaddr/ifaddr/_posix.py
    ifaddr/ifaddr/_win32.py
    ifaddr/ifaddr/_shared.py
    ifaddr/ifaddr/test_ifaddr.py
    DESTINATION lib/cura/plugins/OctoPrintPlugin/ifaddr/ifaddr
)
