# Copyright (c) 2020 Aldo Hoeben / fieldOfView
# NetworkReplyTimeout is released under the terms of the AGPLv3 or higher.

from PyQt5.QtCore import QObject, QTimer
from PyQt5.QtNetwork import QNetworkReply

from UM.Signal import Signal

from typing import Optional, Callable

#
# A timer that is started when a QNetworkRequest returns a QNetworkReply, which closes the
# QNetworkReply does not reply in a timely manner
#
class NetworkReplyTimeout(QObject):
    timeout = Signal()

    def __init__(self, reply: QNetworkReply, timeout: int,
                 callback: Optional[Callable[[QNetworkReply], None]] = None) -> None:
        super().__init__()

        self._reply = reply
        self._callback = callback

        self._timer = QTimer()
        self._timer.setInterval(timeout)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._onTimeout)

        self._timer.start()

    def _onTimeout(self):
        if self._reply.isRunning():
            self._reply.abort()
            if self._callback:
                self._callback(self._reply)
            self.timeout.emit(self._reply)
