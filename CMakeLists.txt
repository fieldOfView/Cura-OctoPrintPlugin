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

install(DIRECTORY qml
    DESTINATION lib/cura/plugins/OctoPrintPlugin/qml
)

install(DIRECTORY qml_qt5
    DESTINATION lib/cura/plugins/OctoPrintPlugin/qml_qt5
)

install(DIRECTORY python-zeroconf
    DESTINATION lib/cura/plugins/OctoPrintPlugin/python-zeroconf
)

install(DIRECTORY ifaddr
    DESTINATION lib/cura/plugins/OctoPrintPlugin/ifaddr
)

install(DIRECTORY async-timeout
    DESTINATION lib/cura/plugins/OctoPrintPlugin/async-timeout
)

install(DIRECTORY i18n
    DESTINATION lib/cura/plugins/OctoPrintPlugin/i18n
)
