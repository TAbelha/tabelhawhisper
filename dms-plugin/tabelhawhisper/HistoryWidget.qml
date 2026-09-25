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
    pluginId: "tabelhawhisper"

    property var historyEntries: []
    property int expandedIndex: -1

    // --- FileView: history (polling — atomic writes break watchChanges/inotify) ---
    FileView {
        id: historyFile
        path: Qt.home() + "/.config/tabelha/tabelhawhisper/history.json"
        printErrors: false
        onLoaded: {
            try {
                var data = JSON.parse(text());
                root.historyEntries = (data.entries || []).slice().reverse();
            } catch (e) {
                root.historyEntries = [];
            }
        }
        onLoadFailed: root.historyEntries = []
    }

    Timer {
        interval: 1000
        repeat: true
        running: true
        onTriggered: historyFile.reload()
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
                size: iconSize
                color: root.historyEntries.length > 0 ? Theme.primary : Theme.widgetInactiveIconColor
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
                size: iconSize
                color: root.historyEntries.length > 0 ? Theme.primary : Theme.widgetInactiveIconColor
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

    // --- Popout (DMS-managed, opens on pill click) ---
    popoutContent: Component {
        Column {
            width: parent.width
            spacing: Theme.spacingS
            topPadding: Theme.spacingM
            bottomPadding: Theme.spacingM
            leftPadding: Theme.spacingM
            rightPadding: Theme.spacingM

            // Header
            Item {
                width: parent.width - Theme.spacingM * 2
                height: headerTitle.implicitHeight

                StyledText {
                    id: headerTitle
                    anchors.left: parent.left
                    anchors.verticalCenter: parent.verticalCenter
                    text: "TAbelhaWhisper" + (root.historyEntries.length > 0 ? " (" + root.historyEntries.length + ")" : "")
                    font.pixelSize: Theme.fontSizeMedium
                    font.weight: Font.Bold
                    color: Theme.surfaceText
                }

                DankIcon {
                    anchors.right: parent.right
                    anchors.verticalCenter: parent.verticalCenter
                    name: "delete_sweep"
                    size: 18
                    color: Theme.surfaceText
                    opacity: 0.6
                    visible: root.historyEntries.length > 0

                    MouseArea {
                        anchors.fill: parent
                        anchors.margins: -4
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            var path = Qt.home() + "/.config/tabelha/tabelhawhisper/history.json";
                            Quickshell.execDetached(["bash", "-c", "echo '{\"entries\":[]}' > '" + path + "'"]);
                            root.historyEntries = [];
                        }
                    }
                }
            }

            // Entries
            ListView {
                width: parent.width - Theme.spacingM * 2
                height: Math.min(root.historyEntries.length * 70, 380)
                clip: true
                visible: root.historyEntries.length > 0
                spacing: 4
                model: root.historyEntries

                delegate: Rectangle {
                    width: ListView.view.width
                    height: root.expandedIndex === index ? 130 : 52
                    radius: Theme.cornerRadius
                    color: entryArea.containsMouse ? Theme.withAlpha(Theme.primary, 0.08) : "transparent"

                    Behavior on height { NumberAnimation { duration: 200 } }

                    Column {
                        anchors.fill: parent
                        anchors.margins: 8
                        spacing: 2

                        // Header row
                        RowLayout {
                            width: parent.width
                            spacing: Theme.spacingXS

                            StyledText {
                                text: root.fmtTs(modelData.ts)
                                font.pixelSize: Theme.fontSizeSmall - 2
                                color: Theme.surfaceVariantText
                                Layout.preferredWidth: 70
                            }

                            Rectangle {
                                width: modeLabel.implicitWidth + 8; height: 16; radius: 4
                                color: Theme.withAlpha(Theme.primary, 0.15)
                                StyledText {
                                    id: modeLabel
                                    anchors.centerIn: parent
                                    text: modelData.mode || "wav"
                                    font.pixelSize: 9
                                    color: Theme.primary
                                }
                            }

                            Rectangle {
                                width: 14; height: 14; radius: 7
                                color: Theme.error
                                visible: modelData.state === "error"
                            }

                            Item { Layout.fillWidth: true }

                            StyledText {
                                text: root.expandedIndex === index ? "\u25b2" : "\u25bc"
                                font.pixelSize: 10
                                color: Theme.surfaceText
                                opacity: 0.4
                            }
                        }

                        // Preview / full text
                        StyledText {
                            width: parent.width
                            text: root.expandedIndex === index
                                ? (modelData.text || "(vazio)")
                                : root.truncate(modelData.text, 80)
                            font.pixelSize: root.expandedIndex === index ? Theme.fontSizeSmall : Theme.fontSizeSmall - 1
                            color: modelData.state === "error" ? Theme.error : Theme.surfaceText
                            wrapMode: Text.WordWrap
                            maximumLineCount: root.expandedIndex === index ? 5 : 2
                            elide: Text.ElideRight
                        }

                        // Copy button (expanded, no errors)
                        Rectangle {
                            width: 70; height: 24; radius: 6
                            color: copyBtnArea.containsMouse ? Theme.withAlpha(Theme.primary, 0.2) : Theme.withAlpha(Theme.primary, 0.1)
                            visible: root.expandedIndex === index && modelData.state !== "error"
                            StyledText {
                                anchors.centerIn: parent
                                text: "Copiar"
                                font.pixelSize: Theme.fontSizeSmall - 1
                                color: Theme.primary
                            }
                            MouseArea {
                                id: copyBtnArea
                                anchors.fill: parent
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
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
                            root.expandedIndex = (root.expandedIndex === index) ? -1 : index;
                        }
                        z: -1
                    }
                }
            }

            // Empty state
            StyledText {
                visible: root.historyEntries.length === 0
                text: "Nenhuma transcri\u00e7\u00e3o ainda\nMod+E para gravar"
                font.pixelSize: Theme.fontSizeSmall
                color: Theme.surfaceVariantText
                horizontalAlignment: Text.AlignHCenter
                width: parent.width - Theme.spacingM * 2
            }
        }
    }

    popoutWidth: 380
    popoutHeight: 0
}
