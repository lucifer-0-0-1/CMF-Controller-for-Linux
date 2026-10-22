import QtQuick
import QtQuick.Window
import QtQuick.Shapes
import QtQuick.Effects

QtObject {
    id: ui
    readonly property real s: cmfBridge.uiScale
    readonly property color accent: "#D71921"
    function accentA(a) { return Qt.rgba(accent.r, accent.g, accent.b, a) }
    function fg(a) { return Qt.rgba(1, 1, 1, a) }
    readonly property color ink: "#F4F6FB"
    readonly property color inkDim: fg(0.50)
    readonly property color surface: "#0E0F14"
    readonly property color edge: Qt.rgba(1, 1, 1, 0.08)
    property rect screen: Qt.rect(0, 0, 1920, 1080)

    property Connections bridge: Connections {
        target: cmfBridge
        function onPlaced(x, y, w, h) { ui.screen = Qt.rect(x, y, w, h) }
        function onWheelOpened(items, index) { hud.dismiss(); wheel.open(items, index) }
        function onWheelMoved(index, dir) { wheel.move(index, dir) }
        function onWheelCommitted(index) { wheel.commit(index) }
        function onWheelCancelled() { wheel.cancel() }
        function onHudShown(icon, glyph, title, detail, progress, dir) {
            if (!wheel.shown) hud.show(icon, glyph, title, detail, progress, dir)
        }
    }

    // ================================================================ WHEEL
    property Window wheelWindow: Window {
        id: wheelWin
        objectName: "cmfWheel"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
        color: "transparent"
        title: "CMF Controller"
        visible: false
        width: Math.ceil(460 * ui.s); height: width
        x: ui.screen.x + (ui.screen.width - width) / 2
        y: ui.screen.y + (ui.screen.height - height) / 2

        Connections {
            target: wheel
            function onShownChanged() {
                if (wheel.shown) { wheelHide.stop(); wheelWin.visible = true }
                else wheelHide.restart()
            }
        }
        Timer { id: wheelHide; interval: 400; onTriggered: if (!wheel.shown) wheelWin.visible = false }

        Item {
            id: wheel
            property bool shown: false
            property var items: []
            property int index: 0
            property int n: Math.max(items.length, 1)
            readonly property real step: 360 / n
            property real selTarget: 0
            property real selAngle: selTarget
            property real openT: 0

            readonly property real dia: 340 * ui.s
            readonly property real rad: 116 * ui.s
            width: dia; height: dia
            anchors.centerIn: parent
            opacity: 0
            scale: 0.88

            Behavior on selAngle { SpringAnimation { spring: 5.5; damping: 0.38; epsilon: 0.02 } }

            function open(list, idx) {
                closeAnim.stop(); commitAnim.stop()
                items = list
                index = idx
                selTarget = idx * step
                shown = true
                openAnim.restart()
                centre.swap(0)
            }

            function move(idx, dir) {
                var d = ((idx - index) % n + n) % n
                if (dir < 0 && d !== 0) d = d - n
                index = idx
                selTarget += d * step
                centre.swap(dir)
            }

            function commit(idx) {
                if (!shown) return
                index = idx
                shown = false
                openAnim.stop()
                commitAnim.restart()
            }

            function cancel() {
                if (!shown) return
                shown = false
                openAnim.stop()
                closeAnim.restart()
            }

            ParallelAnimation {
                id: openAnim
                NumberAnimation { target: wheel; property: "opacity"; from: 0; to: 1; duration: 130; easing.type: Easing.OutCubic }
                SpringAnimation { target: wheel; property: "scale"; from: 0.88; to: 1; spring: 6; damping: 0.42; epsilon: 0.002 }
                NumberAnimation { target: wheel; property: "openT"; from: 0; to: 1; duration: 380; easing.type: Easing.OutCubic }
            }
            SequentialAnimation {
                id: commitAnim
                ParallelAnimation {
                    NumberAnimation { target: wheel; property: "scale"; to: 1.06; duration: 200; easing.type: Easing.OutCubic }
                    NumberAnimation { target: wheel; property: "opacity"; to: 0; duration: 200; easing.type: Easing.OutCubic }
                }
            }
            ParallelAnimation {
                id: closeAnim
                NumberAnimation { target: wheel; property: "scale"; to: 0.9; duration: 160; easing.type: Easing.InCubic }
                NumberAnimation { target: wheel; property: "opacity"; to: 0; duration: 160; easing.type: Easing.InCubic }
            }

            function px(angleDeg, r) { return dia / 2 + r * Math.sin(angleDeg * Math.PI / 180) }
            function py(angleDeg, r) { return dia / 2 - r * Math.cos(angleDeg * Math.PI / 180) }

            RectangularShadow {
                anchors.fill: disc
                offset.y: 8 * ui.s
                radius: disc.radius
                blur: 32 * ui.s
                color: "#90000000"
            }
            Rectangle {
                id: disc
                anchors.fill: parent
                radius: width / 2
                color: ui.surface
                border.color: ui.edge
                border.width: 1
            }

            // ---- Tactile Nothing dot-matrix perimeter track (CMF knurled dial look)
            Repeater {
                model: 48
                Rectangle {
                    readonly property real a: index * (360 / 48)
                    width: (index % 4 === 0) ? 2.5 * ui.s : 1.8 * ui.s
                    height: width; radius: width / 2
                    color: (index % 4 === 0) ? ui.fg(0.24) : ui.fg(0.08)
                    x: wheel.px(a, wheel.dia / 2 - 6 * ui.s) - width / 2
                    y: wheel.py(a, wheel.dia / 2 - 6 * ui.s) - height / 2
                }
            }

            // ---- Glowing selection puck
            Item {
                id: puck
                readonly property real lx: wheel.px(wheel.selAngle, wheel.rad)
                readonly property real ly: wheel.py(wheel.selAngle, wheel.rad)
            }
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "transparent"
                    fillGradient: RadialGradient {
                        centerX: puck.lx; centerY: puck.ly; focalX: centerX; focalY: centerY
                        centerRadius: wheel.dia * 0.55; focalRadius: 0
                        GradientStop { position: 0.00; color: ui.accentA(0.32) }
                        GradientStop { position: 0.20; color: ui.accentA(0.12) }
                        GradientStop { position: 0.50; color: ui.accentA(0.02) }
                        GradientStop { position: 1.00; color: "transparent" }
                    }
                    PathAngleArc { centerX: wheel.dia / 2; centerY: wheel.dia / 2; radiusX: wheel.dia / 2 - 1; radiusY: radiusX; startAngle: 0; sweepAngle: 360 }
                }
            }

            // ---- Items around the ring
            Repeater {
                model: wheel.items
                Item {
                    id: it
                    readonly property bool sel: index === wheel.index
                    readonly property real a: index * wheel.step
                    readonly property real t: Math.max(0, Math.min(1, wheel.openT * 1.5 - index * 0.05))
                    readonly property real r: wheel.rad * (0.75 + 0.25 * t)
                    width: 54 * ui.s; height: width
                    x: wheel.px(a, r) - width / 2
                    y: wheel.py(a, r) - height / 2
                    opacity: t * (sel ? 1 : 0.6)
                    scale: sel ? 1.15 : 1
                    Behavior on scale { NumberAnimation { duration: 150; easing.type: Easing.OutBack; easing.overshoot: 2 } }

                    Icon {
                        anchors.centerIn: parent
                        name: modelData.icon
                        glyph: modelData.glyph
                        size: 24 * ui.s
                        color: it.sel ? "#FFFFFF" : ui.inkDim
                    }
                }
            }

            // ---- Central dial cap
            Item {
                id: centre
                anchors.centerIn: parent
                width: wheel.rad * 1.35; height: width
                property real shift: 0
                property var cur: wheel.items.length ? wheel.items[wheel.index] : ({ icon: "", glyph: "", label: "", sticky: true })

                Rectangle {
                    anchors.centerIn: parent
                    width: parent.width * 0.95; height: width; radius: width / 2
                    color: "#13141B"
                    border.color: Qt.rgba(1, 1, 1, 0.07)
                    border.width: 1

                    Rectangle {
                        anchors.top: parent.top
                        anchors.topMargin: 5 * ui.s
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: 3 * ui.s; height: 3 * ui.s; radius: width / 2
                        color: ui.accent
                    }
                }

                function swap(dir) {
                    swapAnim.stop()
                    shift = dir * 14 * ui.s
                    content.opacity = dir === 0 ? 1 : 0.25
                    swapAnim.start()
                }
                ParallelAnimation {
                    id: swapAnim
                    SpringAnimation { target: centre; property: "shift"; to: 0; spring: 7; damping: 0.5; epsilon: 0.05 }
                    NumberAnimation { target: content; property: "opacity"; to: 1; duration: 130; easing.type: Easing.OutCubic }
                }

                Column {
                    id: content
                    anchors.centerIn: parent
                    anchors.horizontalCenterOffset: centre.shift
                    spacing: 5 * ui.s
                    Icon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        name: centre.cur.icon
                        glyph: centre.cur.glyph
                        size: 38 * ui.s
                        color: ui.accent
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: centre.cur.label
                        font.pixelSize: 16 * ui.s
                        font.weight: Font.DemiBold
                        color: ui.ink
                        elide: Text.ElideRight
                        maximumLineCount: 1
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: (centre.cur.id && String(centre.cur.id).indexOf("app:") === 0) ? "PRESS TO LAUNCH" :
                              (centre.cur.id === "next_page") ? "NEXT PAGE »" :
                              (centre.cur.id === "back") ? "RETURN TO WHEEL" :
                              centre.cur.sticky ? "PRESS TO USE" : "PRESS TO RUN"
                        font.pixelSize: 10 * ui.s
                        font.letterSpacing: 0.8
                        color: ui.fg(0.42)
                    }
                }
            }
        }
    }

    // ================================================================ HUD
    property Window hudWindow: Window {
        id: hudWin
        objectName: "cmfHud"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
        color: "transparent"
        title: "CMF HUD"
        visible: false
        width: Math.ceil(720 * ui.s); height: Math.ceil(130 * ui.s)
        x: ui.screen.x + (ui.screen.width - width) / 2
        y: ui.screen.y + ui.screen.height - 150 * ui.s - 30 * ui.s

        Connections {
            target: hud
            function onShownChanged() {
                if (hud.shown) { hudHide.stop(); hudWin.visible = true }
                else hudHide.restart()
            }
        }
        Timer { id: hudHide; interval: 400; onTriggered: if (!hud.shown) hudWin.visible = false }

        Item {
            id: hud
            property bool shown: false
            property string icon: ""
            property string glyph: ""
            property string title: ""
            property string detail: ""
            property real progress: -1
            property real nudge: 0
            property real lift: 18 * ui.s

            anchors.horizontalCenter: parent.horizontalCenter
            y: 30 * ui.s + lift
            width: pill.width; height: pill.height
            opacity: 0

            function show(ic, g, t, d, p, dir) {
                var wasShown = shown
                icon = ic; glyph = g; title = t; detail = d; progress = p
                shown = true
                outAnim.stop()
                if (!wasShown) inAnim.restart()
                else { opacity = 1; lift = 0 }
                if (dir !== 0) { nudgeAnim.stop(); nudge = dir * 14; nudgeAnim.start() }
                hudTimer.restart()
            }
            function dismiss() { if (shown) { shown = false; hudTimer.stop(); outAnim.restart() } }

            Timer { id: hudTimer; interval: 1400; onTriggered: hud.dismiss() }
            ParallelAnimation {
                id: inAnim
                NumberAnimation { target: hud; property: "opacity"; from: 0; to: 1; duration: 140; easing.type: Easing.OutCubic }
                SpringAnimation { target: hud; property: "lift"; from: 18 * ui.s; to: 0; spring: 6; damping: 0.45; epsilon: 0.05 }
            }
            ParallelAnimation {
                id: outAnim
                NumberAnimation { target: hud; property: "opacity"; to: 0; duration: 240; easing.type: Easing.InCubic }
                NumberAnimation { target: hud; property: "lift"; to: 10 * ui.s; duration: 240; easing.type: Easing.InCubic }
            }
            SpringAnimation { id: nudgeAnim; target: hud; property: "nudge"; to: 0; spring: 9; damping: 0.32; epsilon: 0.1 }

            RectangularShadow {
                anchors.fill: pill
                offset.y: 6 * ui.s
                radius: pill.radius
                blur: 24 * ui.s
                color: "#80000000"
            }
            Rectangle {
                id: pill
                width: row.implicitWidth + 30 * ui.s
                height: 56 * ui.s
                radius: height / 2
                color: "#101116"
                border.color: ui.edge
                border.width: 1

                Row {
                    id: row
                    anchors.verticalCenter: parent.verticalCenter
                    x: 12 * ui.s
                    spacing: 12 * ui.s
                    Rectangle {
                        width: 36 * ui.s; height: width; radius: width / 2
                        anchors.verticalCenter: parent.verticalCenter
                        color: ui.accentA(0.22)
                        Icon {
                            anchors.centerIn: parent
                            name: hud.icon
                            glyph: hud.glyph
                            size: 18 * ui.s
                            color: ui.accent
                            rotation: hud.nudge
                        }
                    }
                    Column {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 4 * ui.s
                        Row {
                            spacing: 8 * ui.s
                            Text { text: hud.title; color: ui.ink; font.pixelSize: 15 * ui.s; font.weight: Font.DemiBold }
                            Text { text: hud.detail; color: ui.inkDim; font.pixelSize: 15 * ui.s; visible: hud.detail.length > 0 }
                        }
                        Rectangle {
                            visible: hud.progress >= 0
                            width: 150 * ui.s; height: 4 * ui.s; radius: height / 2
                            color: ui.fg(0.12)
                            Rectangle {
                                height: parent.height; radius: parent.radius
                                color: ui.accent
                                width: parent.width * Math.max(0, hud.progress)
                            }
                        }
                    }
                    Item { width: 4 * ui.s; height: 1 }
                }
            }
        }
    }
}
