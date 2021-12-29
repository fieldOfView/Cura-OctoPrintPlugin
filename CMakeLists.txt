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
    UploadOptions.py
    WebcamsModel.py
    LICENSE
    README.md
    DESTINATION lib/cura/plugins/OctoPrintPlugin
)

install(FILES
    qml/DiscoverOctoPrintAction.qml
    qml/OctoPrintComponents.qml
    qml/ManualInstanceDialog.qml
    qml/MonitorItem3x.qml
    qml/MonitorItem4x.qml
    qml/UploadOptions.qml
    DESTINATION lib/cura/plugins/OctoPrintPlugin/qml
)

install(FILES
    python-zeroconf/README.rst
    python-zeroconf/COPYING
    DESTINATION lib/cura/plugins/OctoPrintPlugin/python-zeroconf
)

install(FILES
    python-zeroconf/zeroconf/asyncio.py
    python-zeroconf/zeroconf/const.py
    python-zeroconf/zeroconf/_cache.py
    python-zeroconf/zeroconf/_core.py
    python-zeroconf/zeroconf/_dns.py
    python-zeroconf/zeroconf/_exceptions.py
    python-zeroconf/zeroconf/_handlers.py
    python-zeroconf/zeroconf/_history.py
    python-zeroconf/zeroconf/_logger.py
    python-zeroconf/zeroconf/_updates.py
    python-zeroconf/zeroconf/__init__.py
    DESTINATION lib/cura/plugins/OctoPrintPlugin/python-zeroconf/zeroconf
)

install(FILES
    python-zeroconf/zeroconf/_protocol/incoming.py
    python-zeroconf/zeroconf/_protocol/outgoing.py
    python-zeroconf/zeroconf/_protocol/__init__.py
    DESTINATION lib/cura/plugins/OctoPrintPlugin/python-zeroconf/zeroconf/_protocol
)

install(FILES
    python-zeroconf/zeroconf/_services/browser.py
    python-zeroconf/zeroconf/_services/info.py
    python-zeroconf/zeroconf/_services/registry.py
    python-zeroconf/zeroconf/_services/types.py
    python-zeroconf/zeroconf/_services/__init__.py
    DESTINATION lib/cura/plugins/OctoPrintPlugin/python-zeroconf/zeroconf/_services
)

install(FILES
    python-zeroconf/zeroconf/_utils/asyncio.py
    python-zeroconf/zeroconf/_utils/name.py
    python-zeroconf/zeroconf/_utils/net.py
    python-zeroconf/zeroconf/_utils/time.py
    python-zeroconf/zeroconf/_utils/__init__.py
    DESTINATION lib/cura/plugins/OctoPrintPlugin/python-zeroconf/zeroconf/_utils
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
