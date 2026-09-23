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
    layerNamespacePlugin: "whisperDictate"

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
    property real pillDragStartPillX: 0
    property real pillDragStartPillY: 0
    property bool pillDragStarted: false
    property string pillScreenName: ""
    property bool pillScreenPersisted: false
    property int pillX: -1
    property int pillY: 12

    readonly property int pillMaxWidth: 440
    readonly property int pillCollapsedWidth: 260
    readonly property int pillWindowHeight: 60
    readonly property int pillWindowWidth: root.isRecording || root.isPaused ? root.pillMaxWidth : root.pillCollapsedWidth

    // --- Helpers ---
    function pillClamp(value, minVal, maxVal) {
        return Math.max(minVal, Math.min(maxVal, value));
    }

    function pillScreen() {
        for (var i = 0; i < Quickshell.screens.length; i++) {
            if (Quickshell.screens[i].name === root.pillScreenName)
                return Quickshell.screens[i];
        }
        return Quickshell.screens.length > 0 ? Quickshell.screens[0] : null;
    }

    function pillLocalX(screen) {
        if (!screen) return 12;
        var defaultX = Math.max(4, screen.width - root.pillMaxWidth - 12);
        var x = root.pillX >= 0 ? root.pillX : defaultX;
        return pillClamp(x, 4, Math.max(4, screen.width - root.pillMaxWidth - 4));
    }

    function pillLocalY(screen) {
        if (!screen) return 12;
        return pillClamp(root.pillY, 4, Math.max(4, screen.height - root.pillWindowHeight - 4));
    }

    function screenByName(name) {
        for (var i = 0; i < Quickshell.screens.length; i++) {
            if (Quickshell.screens[i].name === name) return Quickshell.screens[i];
        }
        return Quickshell.screens.length > 0 ? Quickshell.screens[0] : null;
    }

    function screenForGlobalPoint(globalX, globalY) {
        for (var i = 0; i < Quickshell.screens.length; i++) {
            var candidate = Quickshell.screens[i];
            if (globalX >= candidate.x && globalX < candidate.x + candidate.width &&
                globalY >= candidate.y && globalY < candidate.y + candidate.height) {
                return candidate;
            }
        }
        return pillScreen();
    }

    function ensurePillScreen() {
        if (!screenByName(root.pillScreenName) && Quickshell.screens.length > 0) {
            root.pillScreenName = Quickshell.screens[0].name;
            root.pillX = -1;
            root.pillY = 12;
        }
    }

    function loadPosition() {
        if (!pluginService) return;
        var savedX = pluginService.loadPluginData("whisperDictate", "pillX", -1);
        var savedY = pluginService.loadPluginData("whisperDictate", "pillY", 12);
        var savedScreen = pluginService.loadPluginData("whisperDictate", "pillScreenName", "");
        if (typeof savedX === "number") root.pillX = savedX;
        if (typeof savedY === "number") root.pillY = savedY;
        if (typeof savedScreen === "string" && savedScreen.length > 0) {
            root.pillScreenName = savedScreen;
            root.pillScreenPersisted = true;
        } else {
            var focused = (typeof CompositorService !== "undefined" && CompositorService.getFocusedScreen)
                ? CompositorService.getFocusedScreen() : null;
            root.pillScreenName = focused ? focused.name
                : (Quickshell.screens.length > 0 ? Quickshell.screens[0].name : "");
            root.pillScreenPersisted = false;
        }
        ensurePillScreen();
    }

    // --- Drag ---
    function beginPillDrag() {
        root.pillDragging = true;
        root.pillDragStarted = false;
    }

    function endPillDrag() {
        root.pillDragging = false;
        root.pillDragStarted = false;
        var screen = pillScreen();
        if (screen) {
            var snapThreshold = 40;
            var leftLimit = 4;
            var rightLimit = Math.max(4, screen.width - root.pillMaxWidth - 4);
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
        root.pillScreenPersisted = true;
    }

    function updatePillDrag(targetScreen, localMouseX, localMouseY) {
        if (!targetScreen) return;

        var globalMouseX = targetScreen.x + localMouseX;
        var globalMouseY = targetScreen.y + localMouseY;

        if (!root.pillDragStarted) {
            var currentScreen = screenByName(root.pillScreenName) || targetScreen;
            root.pillDragStartMouseX = globalMouseX;
            root.pillDragStartMouseY = globalMouseY;
            root.pillDragStartPillX = currentScreen.x + root.pillLocalX(currentScreen);
            root.pillDragStartPillY = currentScreen.y + root.pillLocalY(currentScreen);
            root.pillDragStarted = true;
            return;
        }

        var desiredGlobalX = root.pillDragStartPillX + (globalMouseX - root.pillDragStartMouseX);
        var desiredGlobalY = root.pillDragStartPillY + (globalMouseY - root.pillDragStartMouseY);
        var newScreen = screenForGlobalPoint(globalMouseX, globalMouseY) || targetScreen;

        root.pillScreenName = newScreen.name;
        root.pillX = pillClamp(Math.round(desiredGlobalX - newScreen.x), 4, Math.max(4, newScreen.width - root.pillMaxWidth - 4));
        root.pillY = pillClamp(Math.round(desiredGlobalY - newScreen.y), 4, Math.max(4, newScreen.height - root.pillWindowHeight - 4));
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
        printErrors: false
        onLoaded: {
            try { root.stateObj = JSON.parse(text()); }
            catch (e) { root.stateObj = {}; }
        }
        onLoadFailed: root.stateObj = {}
    }

    Timer {
        interval: 250
        repeat: true
        running: true
        onTriggered: stateFile.reload()
    }

    // --- FileView: levels ---
    FileView {
        id: levelsFile
        path: "/tmp/whisper-dictate-levels.json"
        printErrors: false
        onLoaded: {
            try { root.levelsObj = JSON.parse(text()); }
            catch (e) { root.levelsObj = {}; }
        }
        onLoadFailed: root.levelsObj = {}
    }

    Timer {
        interval: 100
        repeat: true
        running: root.isRecording || root.isPaused
        onTriggered: levelsFile.reload()
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
        if (root.pillVisible && !root.pillScreenPersisted) {
            var focused = (typeof CompositorService !== "undefined" && CompositorService.getFocusedScreen)
                ? CompositorService.getFocusedScreen() : null;
            if (focused) root.pillScreenName = focused.name;
        }
        if (root.isRecording)
            root.elapsed = Math.max(0, Math.floor(Date.now() / 1000 - root.startTime));
    }

    onLevelsObjChanged: {
        root.levels = (root.levelsObj && root.levelsObj.levels) || [];
    }

    onPluginServiceChanged: Qt.callLater(loadPosition)

    Connections {
        target: Quickshell
        function onScreensChanged() { root.ensurePillScreen(); }
    }

    // --- IPC ---
    IpcHandler {
        target: "whisperDictate"
        function ping(): string { return "pong"; }
        function status(): string { return JSON.stringify(root.stateObj); }
        function hide(): string { root.pillVisible = false; return "hidden"; }
        function show(): string { root.pillVisible = true; return "shown"; }
    }

    // --- Drag overlays (one per screen, visible only while dragging) ---
    Variants {
        model: Quickshell.screens

        delegate: PanelWindow {
            id: dragOverlay
            required property var modelData
            property var targetScreen: modelData

            screen: targetScreen
            visible: root.pillDragging
            WlrLayershell.layer: WlrLayer.Overlay
            WlrLayershell.namespace: "dms-pill-drag-" + targetScreen.name
            color: "transparent"
            exclusionMode: ExclusionMode.Ignore

            anchors {
                top: true
                bottom: true
                left: true
                right: true
            }

            MouseArea {
                anchors.fill: parent
                z: 3
                hoverEnabled: true
                acceptedButtons: Qt.LeftButton | Qt.RightButton
                cursorShape: Qt.ClosedHandCursor

                onPositionChanged: function(mouse) {
                    if (root.pillDragging) {
                        root.updatePillDrag(dragOverlay.targetScreen, mouse.x, mouse.y);
                    }
                }
                onClicked: root.endPillDrag()
            }
        }
    }

    // --- Floating pill window ---
    PanelWindow {
        id: pillWindow
        visible: root.pillVisible
        screen: pillScreen()

        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "dms-pill-whisperDictate"
        exclusionMode: ExclusionMode.Ignore
        color: "transparent"

        anchors {
            top: true
            left: true
        }
        margins {
            left: root.pillLocalX(pillWindow.screen)
            top: root.pillLocalY(pillWindow.screen)
        }

        width: root.pillMaxWidth
        height: root.pillWindowHeight

        // Background MouseArea for dragging (RightButton)
        MouseArea {
            anchors.fill: parent
            z: -1
            cursorShape: Qt.PointingHandCursor
            acceptedButtons: Qt.RightButton

            onClicked: function(mouse) {
                root.pillDragging ? root.endPillDrag() : root.beginPillDrag();
            }
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
                    id: waveRow
                    spacing: 2
                    Layout.fillWidth: true
                    Layout.preferredHeight: 30
                    Layout.alignment: Qt.AlignVCenter

                    readonly property int barCount: Math.max(1, Math.floor((width + spacing) / (3 + spacing)))

                    Repeater {
                        model: waveRow.barCount
                        Item {
                            width: 3
                            height: waveRow.height
                            Rectangle {
                                width: parent.width
                                anchors.bottom: parent.bottom
                                color: Theme.primary
                                property real barLevel: {
                                    var n = root.levels.length;
                                    var idx = n - 1 - index;
                                    return (idx >= 0 && idx < n) ? (root.levels[idx] || 0) : 0;
                                }
                                height: Math.max(2, barLevel * parent.height)
                                Behavior on height { NumberAnimation { duration: 80 } }
                            }
                        }
                    }
                }

                Item { Layout.fillWidth: false; width: 8 }

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
                    RotationAnimation on rotation {
                        from: 0; to: 360; duration: 1000
                        loops: Animation.Infinite
                        running: root.isTranscribing
                        onRunningChanged: { if (!running) rotation = 0; }
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
