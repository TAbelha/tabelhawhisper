import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import qs.Common
import qs.Services
import qs.Widgets
import qs.Modules.Plugins

PluginComponent {
    id: root
    pluginId: "whisperDictate"

    // --- State ---
    property bool isRecording: false
    property bool isPaused: false
    property bool isTranscribing: false
    property var levels: []
    property int startTime: 0
    property int elapsed: 0
    property var stateObj: ({})
    property var levelsObj: ({})
    property bool pillVisible: false

    // --- Drag state ---
    property bool pillDragging: false
    property real pillDragStartMouseX: 0
    property real pillDragStartMouseY: 0
    property bool pillDragStarted: false
    property string pillScreenName: Quickshell.screens.length > 0 ? Quickshell.screens[0].name : ""
    property int pillX: -1
    property int pillY: 12

    readonly property int pillWindowWidth: root.isRecording || root.isPaused ? 440 : 260
    readonly property int pillWindowHeight: 60

    function pillClamp(value, minVal, maxVal) {
        return Math.max(minVal, Math.min(maxVal, value));
    }

    function pillScreen() {
        for (var i = 0; i < Quickshell.screens.length; i++) {
            if (Quickshell.screens[i].name === root.pillScreenName)
                return Quickshell.screens[i];
        }
        return Quickshell.screens[0];
    }

    function pillLocalX(screen) {
        var defaultX = Math.max(4, screen.width - root.pillWindowWidth - 12);
        var x = root.pillX >= 0 ? root.pillX : defaultX;
        return pillClamp(x, 4, Math.max(4, screen.width - root.pillWindowWidth - 4));
    }

    function pillLocalY(screen) {
        return pillClamp(root.pillY, 4, Math.max(4, screen.height - root.pillWindowHeight - 4));
    }

    function beginPillDrag() {
        root.pillDragging = true;
        root.pillDragStarted = false;
    }

    function endPillDrag() {
        root.pillDragging = false;
        root.pillDragStarted = false;
        var screen = pillScreen();
        if (screen) {
            var snapThreshold = 30;
            var leftLimit = 4;
            var rightLimit = Math.max(4, screen.width - root.pillWindowWidth - 4);
            var isNearLeft = root.pillX < (leftLimit + snapThreshold);
            var isNearRight = root.pillX > (rightLimit - snapThreshold);
            if (isNearLeft || isNearRight) {
                if (isNearLeft) root.pillX = leftLimit;
                if (isNearRight) root.pillX = rightLimit;
            }
        }
        pluginService.savePluginData("whisperDictate", "pillX", root.pillX);
        pluginService.savePluginData("whisperDictate", "pillY", root.pillY);
        pluginService.savePluginData("whisperDictate", "pillScreenName", root.pillScreenName);
    }

    function updatePillDrag(globalMouseX, globalMouseY) {
        if (!root.pillDragging) return;
        root.pillDragStarted = true;
        var screen = pillScreen();
        if (!screen) return;
        var localX = globalMouseX - screen.x - root.pillDragStartMouseX;
        var localY = globalMouseY - screen.y - root.pillDragStartMouseY;
        root.pillX = pillClamp(localX, 4, Math.max(4, screen.width - root.pillWindowWidth - 4));
        root.pillY = pillClamp(localY, 4, Math.max(4, screen.height - root.pillWindowHeight - 4));
        root.pillScreenName = screen.name;
    }

    function fmt(sec) {
        sec = Math.max(0, sec | 0);
        var m = Math.floor(sec / 60);
        var s = sec % 60;
        return (m < 10 ? "0" : "") + m + ":" + (s < 10 ? "0" : "") + s;
    }

    // --- FileView: state ---
    FileView {
        id: stateFile
        path: "/tmp/whisper-dictate.json"
        onLoaded: {
            try { root.stateObj = JSON.parse(text()); }
            catch (e) { root.stateObj = {}; }
        }
        onLoadFailed: root.stateObj = {}
    }

    // --- FileView: levels ---
    FileView {
        id: levelsFile
        path: "/tmp/whisper-dictate-levels.json"
        onLoaded: {
            try { root.levelsObj = JSON.parse(text()); }
            catch (e) { root.levelsObj = {}; }
        }
        onLoadFailed: root.levelsObj = {}
    }

    // Poll both files every 250ms
    Timer {
        interval: 250
        running: true
        repeat: true
        onTriggered: {
            stateFile.reload();
            levelsFile.reload();
        }
    }

    // Elapsed timer
    Timer {
        interval: 1000
        running: root.isRecording
        repeat: true
        onTriggered: root.elapsed = Math.max(0, Math.floor(Date.now() / 1000 - root.startTime))
    }

    onStateObjChanged: {
        var st = (root.stateObj && root.stateObj.state) || "idle";
        root.isRecording = (st === "recording");
        root.isPaused = (st === "paused");
        root.isTranscribing = (st === "transcribing");
        root.startTime = (root.stateObj && root.stateObj.start) || 0;
        root.pillVisible = root.isRecording || root.isPaused || root.isTranscribing;
        if (root.isRecording)
            root.elapsed = Math.max(0, Math.floor(Date.now() / 1000 - root.startTime));
    }

    onLevelsObjChanged: {
        root.levels = (root.levelsObj && root.levelsObj.levels) || [];
    }

    // --- IPC ---
    IpcHandler {
        target: "whisperDictate"
        function ping(): string { return "pong"; }
        function status(): string { return JSON.stringify(root.stateObj); }
        function hide(): string { root.pillVisible = false; return "hidden"; }
        function show(): string { root.pillVisible = true; return "shown"; }
    }

    // --- Floating pill window ---
    PanelWindow {
        id: pillWindow
        visible: root.pillVisible
        screen: pillScreen()

        WlrLayershell.layer: WlrLayershell.Overlay
        WlrLayershell.exclusionMode: ExclusionMode.Ignore
        color: "transparent"

        x: root.pillLocalX(screen)
        y: root.pillLocalY(screen)
        width: root.pillWindowWidth + 12
        height: root.pillWindowHeight

        // Drag via right mouse button
        MouseArea {
            anchors.fill: parent
            acceptedButtons: Qt.RightButton
            onPressed: (mouse) => {
                root.beginPillDrag();
                root.pillDragStartMouseX = mouse.x;
                root.pillDragStartMouseY = mouse.y;
            }
            onPositionChanged: (mouse) => {
                if (root.pillDragging) {
                    var globalX = pillWindow.screen.x + mouse.x;
                    var globalY = pillWindow.screen.y + mouse.y;
                    root.updatePillDrag(globalX, globalY);
                }
            }
            onReleased: root.endPillDrag()
        }

        Rectangle {
            id: pillBg
            anchors.right: parent.right
            width: root.pillWindowWidth
            height: root.pillWindowHeight
            radius: height / 2
            color: Theme.withAlpha(Theme.surface || "#ffffff", 0.98)
            border.width: root.pillDragging ? 3 : 1
            border.color: root.pillDragging ? (Theme.primary || "#38bdf8") : Qt.rgba(0, 0, 0, 0.1)

            Behavior on width { NumberAnimation { duration: 450; easing.type: Easing.OutQuint } }

            // --- Recording/Paused state ---
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 12
                spacing: 8
                visible: root.isRecording || root.isPaused

                // Dot
                Rectangle {
                    width: 10; height: 10
                    radius: 5
                    color: root.isPaused ? "#f59e0b" : Theme.error
                    SequentialAnimation on opacity {
                        loops: Animation.Infinite
                        running: root.isRecording && !root.isPaused
                        NumberAnimation { to: 0.3; duration: 600 }
                        NumberAnimation { to: 1.0; duration: 600 }
                    }
                }

                // Timer
                Text {
                    text: root.fmt(root.elapsed)
                    font.family: "JetBrains Mono, monospace"
                    font.pixelSize: 14
                    color: Theme.surfaceText
                    Layout.preferredWidth: 70
                }

                // Wave bars
                Row {
                    spacing: 2
                    Layout.fillWidth: true
                    Repeater {
                        model: Math.min(root.levels.length, 16)
                        Rectangle {
                            width: 3
                            height: 2
                            color: Theme.primary
                            property real barLevel: root.levels[root.levels.length - 1 - index] || 0
                            implicitHeight: Math.max(2, barLevel * 30)
                            Behavior on height { NumberAnimation { duration: 80 } }
                        }
                    }
                }

                Item { Layout.fillWidth: true }

                // Pause/Resume button
                Rectangle {
                    width: 32; height: 32; radius: 8
                    color: pauseArea.containsMouse ? Theme.withAlpha(Theme.primary, 0.2) : "transparent"
                    visible: root.stateObj.mode === "wav"
                    Text {
                        anchors.centerIn: parent
                        text: root.isPaused ? "\u25b6" : "\u23f8"
                        font.pixelSize: 14
                        color: Theme.surfaceText
                    }
                    MouseArea {
                        id: pauseArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            var script = root.stateObj.script || "";
                            var python = root.stateObj.python || "python3";
                            if (root.isPaused)
                                Quickshell.execDetached([python, script, "resume"]);
                            else
                                Quickshell.execDetached([python, script, "pause"]);
                        }
                    }
                }

                // Stop (finish) button
                Rectangle {
                    width: 32; height: 32; radius: 8
                    color: stopArea.containsMouse ? Theme.withAlpha(Theme.primary, 0.2) : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "\u23f9"
                        font.pixelSize: 14
                        color: Theme.surfaceText
                    }
                    MouseArea {
                        id: stopArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            var script = root.stateObj.script || "";
                            var python = root.stateObj.python || "python3";
                            Quickshell.execDetached([python, script, "stop"]);
                        }
                    }
                }

                // Cancel button
                Rectangle {
                    width: 32; height: 32; radius: 8
                    color: cancelRecArea.containsMouse ? Theme.withAlpha(Theme.error, 0.2) : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "\u2715"
                        font.pixelSize: 14
                        color: Theme.error
                    }
                    MouseArea {
                        id: cancelRecArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            var script = root.stateObj.script || "";
                            var python = root.stateObj.python || "python3";
                            Quickshell.execDetached([python, script, "cancel"]);
                        }
                    }
                }
            }

            // --- Transcribing state ---
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 20
                anchors.rightMargin: 12
                spacing: 8
                visible: root.isTranscribing

                // Spinner
                Text {
                    text: "\u27f3"
                    font.pixelSize: 16
                    color: Theme.warning
                    SequentialAnimation on rotation {
                        loops: Animation.Infinite
                        running: root.isTranscribing
                        NumberAnimation { to: 360; duration: 1000 }
                    }
                }

                Text {
                    text: "Transcrevendo..."
                    font.pixelSize: 14
                    color: Theme.surfaceText
                }

                Item { Layout.fillWidth: true }

                // Cancel button
                Rectangle {
                    width: 32; height: 32; radius: 8
                    color: cancelTxArea.containsMouse ? Theme.withAlpha(Theme.error, 0.2) : "transparent"
                    Text {
                        anchors.centerIn: parent
                        text: "\u2715"
                        font.pixelSize: 14
                        color: Theme.error
                    }
                    MouseArea {
                        id: cancelTxArea
                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            var script = root.stateObj.script || "";
                            var python = root.stateObj.python || "python3";
                            Quickshell.execDetached([python, script, "cancel"]);
                        }
                    }
                }
            }
        }
    }
}
