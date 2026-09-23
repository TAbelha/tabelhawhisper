import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import qs.Common
import qs.Services
import qs.Widgets
import qs.Modules.Plugins

PluginComponent {
    id: root
    pluginId: "whisperDictate"

    property var historyEntries: []
    property int expandedIndex: -1

    // --- FileView: history ---
    FileView {
        id: historyFile
        path: Qt.home() + "/.config/tabelha/whisper-dictate/history.json"
        onLoaded: {
            try {
                var data = JSON.parse(text());
                root.historyEntries = (data.entries || []).slice().reverse(); // newest first
            } catch (e) {
                root.historyEntries = [];
            }
        }
        onLoadFailed: root.historyEntries = []
    }

    function loadHistory() {
        historyFile.reload();
    }

    function fmtTs(ts) {
        var d = new Date(ts * 1000);
        var day = ("0" + d.getDate()).slice(-2);
        var month = ("0" + (d.getMonth() + 1)).slice(-2);
        var hour = ("0" + d.getHours()).slice(-2);
        var min = ("0" + d.getMinutes()).slice(-2);
        return day + "/" + month + " " + hour + ":" + min;
    }

    function truncate(text, maxLen) {
        if (!text) return "";
        return text.length > maxLen ? text.substring(0, maxLen) + "..." : text;
    }

    // --- Bar pill ---
    horizontalBarPill: Component {
        Row {
            spacing: 4

            DankIcon {
                name: "history"
                size: Theme.fontSizeSmall
                color: Theme.widgetIconColor
                anchors.verticalCenter: parent.verticalCenter
            }

            StyledText {
                text: root.historyEntries.length > 0 ? root.historyEntries.length.toString() : ""
                font.pixelSize: Theme.fontSizeSmall - 2
                color: Theme.surfaceText
                visible: root.historyEntries.length > 0
                anchors.verticalCenter: parent.verticalCenter
            }
        }
    }

    verticalBarPill: Component {
        Column {
            spacing: 2

            DankIcon {
                name: "history"
                size: Theme.fontSizeSmall
                color: Theme.widgetIconColor
                anchors.horizontalCenter: parent.horizontalCenter
            }

            StyledText {
                text: root.historyEntries.length > 0 ? root.historyEntries.length.toString() : ""
                font.pixelSize: Theme.fontSizeSmall - 2
                color: Theme.surfaceText
                visible: root.historyEntries.length > 0
                anchors.horizontalCenter: parent.horizontalCenter
            }
        }
    }

    // --- Popout window ---
    PanelWindow {
        id: historyPopout
        visible: false

        WlrLayershell.layer: WlrLayershell.Overlay
        WlrLayershell.exclusionMode: ExclusionMode.Ignore
        color: "transparent"

        width: 380
        height: Math.min(500, 60 + root.historyEntries.length * 70)
        anchors.top: true

        Rectangle {
            anchors.fill: parent
            anchors.margins: 8
            radius: 12
            color: Theme.withAlpha(Theme.surface || "#ffffff", 0.98)
            border.width: 1
            border.color: Qt.rgba(0, 0, 0, 0.1)

            Column {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 8

                // Header
                RowLayout {
                    width: parent.width
                    Text {
                        text: "TAbelha Whisper"
                        font.pixelSize: 14
                        font.bold: true
                        color: Theme.surfaceText
                        Layout.fillWidth: true
                    }
                    Rectangle {
                        width: 28; height: 28; radius: 6
                        color: clearArea.containsMouse ? Theme.withAlpha(Theme.error, 0.2) : "transparent"
                        visible: root.historyEntries.length > 0
                        Text {
                            anchors.centerIn: parent
                            text: "\ud83d\uddd1"
                            font.pixelSize: 12
                        }
                        MouseArea {
                            id: clearArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                var path = Qt.home() + "/.config/tabelha/whisper-dictate/history.json";
                                Quickshell.execDetached(["bash", "-c", "echo '{\"entries\":[]}' > '" + path + "'"]);
                                root.historyEntries = [];
                            }
                        }
                    }
                }

                // Entries list
                ListView {
                    width: parent.width
                    height: parent.height - 44
                    clip: true
                    model: root.historyEntries

                    delegate: Rectangle {
                        width: ListView.view.width
                        height: root.expandedIndex === index ? 140 : 56
                        radius: 8
                        color: entryArea.containsMouse ? Theme.withAlpha(Theme.primary, 0.08) : "transparent"

                        Behavior on height { NumberAnimation { duration: 200 } }

                        Column {
                            anchors.fill: parent
                            anchors.margins: 8
                            spacing: 4

                            // Header row
                            RowLayout {
                                width: parent.width

                                // Timestamp
                                Text {
                                    text: root.fmtTs(modelData.ts)
                                    font.pixelSize: 11
                                    color: Theme.surfaceText
                                    opacity: 0.6
                                }

                                // Mode badge
                                Rectangle {
                                    width: modeText.width + 8; height: 16; radius: 4
                                    color: Theme.withAlpha(Theme.primary, 0.15)
                                    Text {
                                        id: modeText
                                        anchors.centerIn: parent
                                        text: modelData.mode || "wav"
                                        font.pixelSize: 9
                                        color: Theme.primary
                                    }
                                }

                                // Error badge
                                Rectangle {
                                    width: 14; height: 14; radius: 7
                                    color: Theme.error
                                    visible: modelData.state === "error"
                                }

                                Item { Layout.fillWidth: true }

                                // Expand indicator
                                Text {
                                    text: root.expandedIndex === index ? "\u25b2" : "\u25bc"
                                    font.pixelSize: 10
                                    color: Theme.surfaceText
                                    opacity: 0.4
                                }
                            }

                            // Preview (collapsed) or full text (expanded)
                            Text {
                                width: parent.width
                                text: root.expandedIndex === index
                                    ? (modelData.text || "(vazio)")
                                    : root.truncate(modelData.text, 60)
                                font.pixelSize: root.expandedIndex === index ? 12 : 11
                                color: modelData.state === "error" ? Theme.error : Theme.surfaceText
                                wrapMode: Text.WordWrap
                                maximumLineCount: root.expandedIndex === index ? 6 : 2
                                elide: Text.ElideRight
                            }

                            // Copy button (expanded only, no errors)
                            Rectangle {
                                width: 70; height: 24; radius: 6
                                color: copyArea.containsMouse ? Theme.withAlpha(Theme.primary, 0.2) : Theme.withAlpha(Theme.primary, 0.1)
                                visible: root.expandedIndex === index && modelData.state !== "error"
                                Text {
                                    anchors.centerIn: parent
                                    text: "Copiar"
                                    font.pixelSize: 11
                                    color: Theme.primary
                                }
                                MouseArea {
                                    id: copyArea
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    onClicked: {
                                        DMSService.sendRequest("clipboard.store", {
                                            data: modelData.text,
                                            mimeType: "text/plain;charset=utf-8"
                                        }, function(response) {
                                            if (!response.error) {
                                                ToastService.showToast("Copiado!");
                                            }
                                        });
                                    }
                                }
                            }
                        }

                        MouseArea {
                            id: entryArea
                            anchors.fill: parent
                            hoverEnabled: true
                            onClicked: {
                                if (root.expandedIndex === index)
                                    root.expandedIndex = -1;
                                else
                                    root.expandedIndex = index;
                            }
                            z: -1
                        }
                    }
                }

                // Empty state
                Text {
                    width: parent.width
                    text: "Nenhuma transcri\u00e7\u00e3o ainda\nMod+E para gravar"
                    font.pixelSize: 12
                    color: Theme.surfaceText
                    opacity: 0.5
                    horizontalAlignment: Text.AlignHCenter
                    visible: root.historyEntries.length === 0
                }
            }
        }
    }

    // Open popout on click
    function openPopout() {
        loadHistory();
        historyPopout.visible = !historyPopout.visible;
    }

    Component.onCompleted: {
        root.clicked.connect(openPopout);
    }
}
