# Copyright (c) 2022 Aldo Hoeben / fieldOfView
# NetworkMJPGImage is released under the terms of the LGPLv3 or higher.

try:
    from cura.ApplicationMetadata import CuraSDKVersion
except ImportError: # Cura <= 3.6
    CuraSDKVersion = "6.0.0"
if CuraSDKVersion >= "8.0.0":
    from PyQt6.QtCore import QUrl, pyqtProperty, pyqtSignal, pyqtSlot, QRect, QByteArray
    from PyQt6.QtGui import QImage, QPainter
    from PyQt6.QtQuick import QQuickPaintedItem
    from PyQt6.QtNetwork import (
        QNetworkRequest,
        QNetworkReply,
        QNetworkAccessManager,
        QSslConfiguration,
        QSslSocket,
    )
    QNetworkRequestAttributes = QNetworkRequest.Attribute
    QSslSocketPeerVerifyModes = QSslSocket.PeerVerifyMode
else:
    from PyQt5.QtCore import QUrl, pyqtProperty, pyqtSignal, pyqtSlot, QRect, QByteArray
    from PyQt5.QtGui import QImage, QPainter
    from PyQt5.QtQuick import QQuickPaintedItem
    from PyQt5.QtNetwork import (
        QNetworkRequest,
        QNetworkReply,
        QNetworkAccessManager,
        QSslConfiguration,
        QSslSocket,
    )
    QNetworkRequestAttributes = QNetworkRequest.Attribute
    QSslSocketPeerVerifyModes = QSslSocket

from UM.Logger import Logger

import base64

#
# A QQuickPaintedItem that progressively downloads a network mjpeg stream,
# picks it apart in individual jpeg frames, and paints it.
#
class NetworkMJPGImage(QQuickPaintedItem):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        self._stream_buffer = QByteArray()
        self._stream_buffer_start_index = -1
        self._network_manager = None  # type: QNetworkAccessManager
        self._image_request = None  # type: QNetworkRequest
        self._image_reply = None  # type: QNetworkReply
        self._image = QImage()
        self._image_rect = QRect()

        self._source_url = QUrl()
        self._started = False

        self._mirror = False

        self.setAntialiasing(True)

    ##  Ensure that close gets called when object is destroyed
    def __del__(self) -> None:
        self.stop()

    def paint(self, painter: "QPainter") -> None:
        if self._mirror:
            painter.drawImage(self.contentsBoundingRect(), self._image.mirrored())
            return

        painter.drawImage(self.contentsBoundingRect(), self._image)

    def setSourceURL(self, source_url: "QUrl") -> None:
        self._source_url = source_url
        self.sourceURLChanged.emit()
        if self._started:
            self.start()

    def getSourceURL(self) -> "QUrl":
        return self._source_url

    sourceURLChanged = pyqtSignal()
    source = pyqtProperty(
        QUrl, fget=getSourceURL, fset=setSourceURL, notify=sourceURLChanged
    )

    def setMirror(self, mirror: bool) -> None:
        if mirror == self._mirror:
            return
        self._mirror = mirror
        self.mirrorChanged.emit()
        self.update()

    def getMirror(self) -> bool:
        return self._mirror

    mirrorChanged = pyqtSignal()
    mirror = pyqtProperty(bool, fget=getMirror, fset=setMirror, notify=mirrorChanged)

    imageSizeChanged = pyqtSignal()

    @pyqtProperty(int, notify=imageSizeChanged)
    def imageWidth(self) -> int:
        return self._image.width()

    @pyqtProperty(int, notify=imageSizeChanged)
    def imageHeight(self) -> int:
        return self._image.height()

    @pyqtSlot()
    def start(self) -> None:
        self.stop()  # Ensure that previous requests (if any) are stopped.

        if not self._source_url:
            Logger.log("w", "Unable to start camera stream without target!")
            return

        auth_data = ""
        if self._source_url.userInfo():
            # move auth data to basic authorization header
            auth_data = base64.b64encode(self._source_url.userInfo().encode()).decode(
                "utf-8"
            )
            authority = self._source_url.authority()
            self._source_url.setAuthority(authority.rsplit("@", 1)[1])

        self._image_request = QNetworkRequest(self._source_url)
        try:
            self._image_request.setAttribute(QNetworkRequestAttributes.FollowRedirectsAttribute, True)
        except AttributeError:
            # in Qt6, this is no longer possible (or required), see https://doc.qt.io/qt-6/network-changes-qt6.html#redirect-policies
            pass

        if auth_data:
            self._image_request.setRawHeader(
                b"Authorization", ("basic %s" % auth_data).encode()
            )

        if self._source_url.scheme().lower() == "https":
            # ignore SSL errors (eg for self-signed certificates)
            ssl_configuration = QSslConfiguration.defaultConfiguration()
            ssl_configuration.setPeerVerifyMode(QSslSocketPeerVerifyModes.VerifyNone)
            self._image_request.setSslConfiguration(ssl_configuration)

        if self._network_manager is None:
            self._network_manager = QNetworkAccessManager()

        self._image_reply = self._network_manager.get(self._image_request)
        self._image_reply.downloadProgress.connect(self._onStreamDownloadProgress)

        self._started = True

    @pyqtSlot()
    def stop(self) -> None:
        self._stream_buffer = QByteArray()
        self._stream_buffer_start_index = -1

        if self._image_reply:
            try:
                try:
                    self._image_reply.downloadProgress.disconnect(
                        self._onStreamDownloadProgress
                    )
                except Exception:
                    pass

                if not self._image_reply.isFinished():
                    self._image_reply.close()
            except Exception as e:  # RuntimeError
                pass  # It can happen that the wrapped c++ object is already deleted.

            self._image_reply = None
            self._image_request = None

        self._network_manager = None

        self._started = False

    def _onStreamDownloadProgress(self, bytes_received: int, bytes_total: int) -> None:
        # An MJPG stream is (for our purpose) a stream of concatenated JPG images.
        # JPG images start with the marker 0xFFD8, and end with 0xFFD9
        if self._image_reply is None:
            return
        self._stream_buffer += self._image_reply.readAll()

        if (
            len(self._stream_buffer) > 5000000
        ):  # No single camera frame should be 5 MB or larger
            Logger.log(
                "w", "MJPEG buffer exceeds reasonable size. Restarting stream..."
            )
            self.stop()  # resets stream buffer and start index
            self.start()
            return

        if self._stream_buffer_start_index == -1:
            self._stream_buffer_start_index = self._stream_buffer.indexOf(b"\xff\xd8")
        stream_buffer_end_index = self._stream_buffer.lastIndexOf(b"\xff\xd9")
        # If this happens to be more than a single frame, then so be it; the JPG decoder will
        # ignore the extra data. We do it like this in order not to get a buildup of frames

        if self._stream_buffer_start_index != -1 and stream_buffer_end_index != -1:
            jpg_data = self._stream_buffer[
                self._stream_buffer_start_index : stream_buffer_end_index + 2
            ]
            self._stream_buffer = self._stream_buffer[stream_buffer_end_index + 2 :]
            self._stream_buffer_start_index = -1
            self._image.loadFromData(jpg_data)

            if self._image.rect() != self._image_rect:
                self.imageSizeChanged.emit()

            self.update()
