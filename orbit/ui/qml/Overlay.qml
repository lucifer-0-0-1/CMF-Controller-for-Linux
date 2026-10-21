import QtQuick
import QtQuick.Window
import QtQuick.Shapes
import QtQuick.Effects

// Orbit overlay: two small, frameless, click-through, never-focused windows
// (wheel, HUD). Small windows keep per-frame work tiny, which matters because on
// Windows the overlay is drawn with Qt Quick's software renderer (the only path
// that reliably updates layered/click-through windows after the first frame).
QtObject {
    id: ui
    readonly property real s: orbit.uiScale
    // One look: the highlighted item is a light source. Appearance: dark or light.
    readonly property bool dark: orbit.dark
    readonly property color accent: dark ? orbit.accent : Qt.darker(orbit.accent, 1.32)
    function accentA(a) { return Qt.rgba(accent.r, accent.g, accent.b, a) }
    function fg(a) { return dark ? Qt.rgba(1, 1, 1, a) : Qt.rgba(0.05, 0.06, 0.09, a) }
    readonly property color ink: dark ? "#F4F6FB" : "#12141A"
    readonly property color inkDim: fg(dark ? 0.50 : 0.48)
    readonly property color surface: dark ? Qt.rgba(0.04, 0.045, 0.06, 1.0) : Qt.rgba(0.985, 0.986, 0.995, 1.0)
    readonly property color edge: dark ? Qt.rgba(1, 1, 1, 0.07) : Qt.rgba(0, 0, 0, 0.08)
    readonly property real light: dark ? 1.0 : 0.8          // how strongly the selected item glows
    readonly property color shadowC: dark ? "#A0000000" : "#38000000"
    property rect screen: Qt.rect(0, 0, 1920, 1080)      // screen under the cursor

    property Connections bridge: Connections {
        target: orbit
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
        objectName: "orbitWheel"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
               | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
        color: "transparent"
        title: "Orbit"
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
        Timer { id: wheelHide; interval: 420; onTriggered: if (!wheel.shown) wheelWin.visible = false }

        Item {
            id: wheel
            property bool shown: false
            property var items: []
            property int index: 0
            property int n: Math.max(items.length, 1)
            readonly property real step: 360 / n
            property real selTarget: 0        // cumulative degrees, so wrap-around animates forward
            property real selAngle: selTarget
            property real openT: 0            // 0..1 drives the staggered entry

            readonly property real dia: 340 * ui.s
            readonly property real rad: 116 * ui.s
            width: dia; height: dia
            anchors.centerIn: parent
            opacity: 0
            scale: 0.86

            Behavior on selAngle { SpringAnimation { spring: 5.2; damping: 0.36; epsilon: 0.02 } }

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
                var d = ((idx - index) % n + n) % n           // forward distance
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
                NumberAnimation { target: wheel; property: "opacity"; from: 0; to: 1; duration: 140; easing.type: Easing.OutCubic }
                SpringAnimation { target: wheel; property: "scale"; from: 0.86; to: 1; spring: 6; damping: 0.42; epsilon: 0.002 }
                NumberAnimation { target: wheel; property: "rotation"; from: -12; to: 0; duration: 380; easing.type: Easing.OutBack; easing.overshoot: 1.2 }
                NumberAnimation { target: wheel; property: "openT"; from: 0; to: 1; duration: 420; easing.type: Easing.OutCubic }
            }
            SequentialAnimation {
                id: commitAnim
                NumberAnimation { target: puck; property: "pulse"; from: 1; to: 1.35; duration: 90; easing.type: Easing.OutQuad }
                ParallelAnimation {
                    NumberAnimation { target: puck; property: "pulse"; to: 1; duration: 160; easing.type: Easing.OutQuad }
                    NumberAnimation { target: wheel; property: "scale"; to: 1.08; duration: 220; easing.type: Easing.OutCubic }
                    NumberAnimation { target: wheel; property: "opacity"; to: 0; duration: 220; easing.type: Easing.OutCubic }
                }
            }
            ParallelAnimation {
                id: closeAnim
                NumberAnimation { target: wheel; property: "scale"; to: 0.9; duration: 170; easing.type: Easing.InCubic }
                NumberAnimation { target: wheel; property: "opacity"; to: 0; duration: 170; easing.type: Easing.InCubic }
            }

            function px(angleDeg, r) { return dia / 2 + r * Math.sin(angleDeg * Math.PI / 180) }
            function py(angleDeg, r) { return dia / 2 - r * Math.cos(angleDeg * Math.PI / 180) }

            // ---- disc with soft shadow (the shadow is its own item: if a graphics
            // backend can't run it, only the shadow is lost, never the disc)
            RectangularShadow {
                anchors.fill: disc
                offset.y: 10 * ui.s
                radius: disc.radius
                blur: 36 * ui.s
                spread: 0
                color: ui.shadowC
            }
            Rectangle {
                id: disc
                anchors.fill: parent
                radius: width / 2
                color: ui.surface
                border.color: ui.edge
                border.width: 1
            }

            // ---- the highlighted item is a light source. Its light falls across the
            // disc with a natural (soft, quickly fading) falloff, catches the rim nearest
            // to it and spills a little past the edge. Everything rides the selection
            // spring, so the light glides from item to item.
            Item {
                id: puck                     // keeps the commit pulse: the light flares
                property real pulse: 1
                readonly property real lx: wheel.px(wheel.selAngle, wheel.rad)
                readonly property real ly: wheel.py(wheel.selAngle, wheel.rad)
                readonly property real k: ui.light * (0.75 + 0.25 * pulse)
            }
            // light on the disc (the fill is the disc itself, so it never leaves it)
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "transparent"
                    fillGradient: RadialGradient {
                        centerX: puck.lx; centerY: puck.ly; focalX: centerX; focalY: centerY
                        centerRadius: wheel.dia * 0.62; focalRadius: 0
                        GradientStop { position: 0.00; color: ui.accentA(0.34 * puck.k) }
                        GradientStop { position: 0.08; color: ui.accentA(0.24 * puck.k) }
                        GradientStop { position: 0.20; color: ui.accentA(0.12 * puck.k) }
                        GradientStop { position: 0.38; color: ui.accentA(0.05 * puck.k) }
                        GradientStop { position: 0.60; color: ui.accentA(0.015 * puck.k) }
                        GradientStop { position: 1.00; color: "transparent" }
                    }
                    PathAngleArc { centerX: wheel.dia / 2; centerY: wheel.dia / 2; radiusX: wheel.dia / 2 - 1; radiusY: radiusX; startAngle: 0; sweepAngle: 360 }
                }
            }
            // light spilling past the rim: a band just outside the disc, lit from the item
            Shape {
                id: spill
                anchors.fill: parent
                anchors.margins: -46 * ui.s
                preferredRendererType: Shape.CurveRenderer
                readonly property real o: 46 * ui.s          // offset of this shape's origin
                ShapePath {
                    strokeColor: "transparent"
                    fillRule: ShapePath.OddEvenFill
                    fillGradient: RadialGradient {
                        centerX: puck.lx + spill.o; centerY: puck.ly + spill.o; focalX: centerX; focalY: centerY
                        centerRadius: wheel.dia * 0.42; focalRadius: 0
                        GradientStop { position: 0.00; color: ui.accentA(0.30 * puck.k) }
                        GradientStop { position: 0.18; color: ui.accentA(0.20 * puck.k) }
                        GradientStop { position: 0.40; color: ui.accentA(0.07 * puck.k) }
                        GradientStop { position: 0.70; color: ui.accentA(0.015 * puck.k) }
                        GradientStop { position: 1.00; color: "transparent" }
                    }
                    PathAngleArc { centerX: wheel.dia / 2 + spill.o; centerY: centerX; radiusX: wheel.dia / 2 + spill.o - 2; radiusY: radiusX; startAngle: 0; sweepAngle: 360 }
                    PathMove { x: spill.o + wheel.dia; y: wheel.dia / 2 + spill.o }
                    PathAngleArc { centerX: wheel.dia / 2 + spill.o; centerY: centerX; radiusX: wheel.dia / 2; radiusY: radiusX; startAngle: 0; sweepAngle: 360 }
                }
            }
            // the rim catching the light: brightest nearest the item, fading both ways
            Shape {
                id: rimLight
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                readonly property real rr: wheel.dia / 2 - 0.75 * ui.s
                readonly property real sweep: Math.min(wheel.step * 1.1, 96)
                ShapePath {
                    strokeColor: ui.accentA(0.10 * puck.k); strokeWidth: 1.5 * ui.s; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: wheel.dia / 2; centerY: wheel.dia / 2; radiusX: rimLight.rr; radiusY: radiusX
                                   startAngle: wheel.selAngle - 90 - rimLight.sweep; sweepAngle: rimLight.sweep * 2 }
                }
                ShapePath {
                    strokeColor: ui.accentA(0.25 * puck.k); strokeWidth: 1.5 * ui.s; fillColor: "transparent"; capStyle: ShapePath.FlatCap
                    PathAngleArc { centerX: wheel.dia / 2; centerY: wheel.dia / 2; radiusX: rimLight.rr; radiusY: radiusX
                                   startAngle: wheel.selAngle - 90 - rimLight.sweep * 0.55; sweepAngle: rimLight.sweep * 1.1 }
                }
                ShapePath {
                    strokeColor: ui.accentA(0.55 * puck.k); strokeWidth: 1.5 * ui.s; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                    PathAngleArc { centerX: wheel.dia / 2; centerY: wheel.dia / 2; radiusX: rimLight.rr; radiusY: radiusX
                                   startAngle: wheel.selAngle - 90 - rimLight.sweep * 0.25; sweepAngle: rimLight.sweep * 0.5 }
                }
            }

            // ---- faint track + tick marks
            Shape {
                anchors.fill: parent
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: ui.fg(0.06); strokeWidth: 1; fillColor: "transparent"
                    PathAngleArc { centerX: wheel.dia / 2; centerY: wheel.dia / 2; radiusX: wheel.dia / 2 - 14 * ui.s; radiusY: radiusX; startAngle: 0; sweepAngle: 360 }
                }
            }
            Repeater {
                model: wheel.n
                Rectangle {
                    readonly property real a: index * wheel.step
                    width: 2 * ui.s; height: 6 * ui.s; radius: 1
                    color: ui.fg(index === wheel.index ? 0 : 0.16)
                    x: wheel.px(a, wheel.dia / 2 - 14 * ui.s) - width / 2
                    y: wheel.py(a, wheel.dia / 2 - 14 * ui.s) - height / 2
                    rotation: a
                }
            }

            // ---- items
            Repeater {
                model: wheel.items
                Item {
                    id: it
                    readonly property bool sel: index === wheel.index
                    readonly property real a: index * wheel.step
                    // staggered entry: each item slides out from the centre a little after the previous
                    readonly property real t: Math.max(0, Math.min(1, wheel.openT * 1.6 - index * 0.06))
                    readonly property real r: wheel.rad * (0.72 + 0.28 * t)
                    width: 56 * ui.s; height: width
                    x: wheel.px(a, r) - width / 2
                    y: wheel.py(a, r) - height / 2
                    opacity: t * (sel ? 1 : 0.62)
                    scale: sel ? 1.16 : 1
                    Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutBack; easing.overshoot: 2 } }
                    Behavior on opacity { NumberAnimation { duration: 120 } }

                    Icon {
                        anchors.centerIn: parent
                        name: modelData.icon
                        glyph: modelData.glyph
                        size: 22 * ui.s
                        color: it.sel ? (ui.dark ? "#FFFFFF" : ui.accent) : ui.inkDim
                        Behavior on color { ColorAnimation { duration: 140 } }
                    }
                    Rectangle {   // one-shot marker
                        visible: !modelData.sticky
                        width: 4 * ui.s; height: width; radius: width / 2
                        color: ui.accent
                        anchors.horizontalCenter: parent.horizontalCenter
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 6 * ui.s
                    }
                }
            }

            // ---- centre: big glyph + label, slides in the turn direction
            Item {
                id: centre
                anchors.centerIn: parent
                width: wheel.rad * 1.3; height: width
                property real shift: 0
                property var cur: wheel.items.length ? wheel.items[wheel.index] : ({ icon: "", glyph: "", label: "", sticky: true })

                function swap(dir) {
                    swapAnim.stop()
                    shift = dir * 14 * ui.s
                    content.opacity = dir === 0 ? 1 : 0.25
                    swapAnim.start()
                }
                ParallelAnimation {
                    id: swapAnim
                    SpringAnimation { target: centre; property: "shift"; to: 0; spring: 7; damping: 0.5; epsilon: 0.05 }
                    NumberAnimation { target: content; property: "opacity"; to: 1; duration: 140; easing.type: Easing.OutCubic }
                }

                Column {
                    id: content
                    anchors.centerIn: parent
                    anchors.horizontalCenterOffset: centre.shift
                    spacing: 6 * ui.s
                    Icon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        name: centre.cur.icon
                        glyph: centre.cur.glyph
                        size: 36 * ui.s
                        color: ui.accent
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: centre.cur.label
                        font.pixelSize: 17 * ui.s
                        font.weight: Font.DemiBold
                        color: ui.ink
                    }
                    Text {
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: centre.cur.sticky ? "press to use" : "press to run"
                        font.pixelSize: 11 * ui.s
                        font.letterSpacing: 0.4
                        color: ui.fg(0.40)
                    }
                }
            }
        }
    }

    // ================================================================ HUD
    property Window hudWindow: Window {
        id: hudWin
        objectName: "orbitHud"
        flags: Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
               | Qt.WindowDoesNotAcceptFocus | Qt.WindowTransparentForInput
        color: "transparent"
        title: "Orbit HUD"
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
        Timer { id: hudHide; interval: 420; onTriggered: if (!hud.shown) hudWin.visible = false }

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
                if (dir !== 0) { nudgeAnim.stop(); nudge = dir * 16; nudgeAnim.start() }
                hudTimer.restart()
            }
            function dismiss() { if (shown) { shown = false; hudTimer.stop(); outAnim.restart() } }

            Timer { id: hudTimer; interval: orbit.hudMs; onTriggered: hud.dismiss() }
            ParallelAnimation {
                id: inAnim
                NumberAnimation { target: hud; property: "opacity"; from: 0; to: 1; duration: 150; easing.type: Easing.OutCubic }
                SpringAnimation { target: hud; property: "lift"; from: 18 * ui.s; to: 0; spring: 6; damping: 0.45; epsilon: 0.05 }
            }
            ParallelAnimation {
                id: outAnim
                NumberAnimation { target: hud; property: "opacity"; to: 0; duration: 260; easing.type: Easing.InCubic }
                NumberAnimation { target: hud; property: "lift"; to: 10 * ui.s; duration: 260; easing.type: Easing.InCubic }
            }
            SpringAnimation { id: nudgeAnim; target: hud; property: "nudge"; to: 0; spring: 9; damping: 0.32; epsilon: 0.1 }

            RectangularShadow {
                anchors.fill: pill
                offset.y: 6 * ui.s
                radius: pill.radius
                blur: 24 * ui.s
                color: ui.shadowC
            }
            Rectangle {
                id: pill
                width: row.implicitWidth + 30 * ui.s
                height: 58 * ui.s
                radius: height / 2
                color: ui.surface
                border.color: ui.edge

                Behavior on width { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }

                Row {
                    id: row
                    anchors.verticalCenter: parent.verticalCenter
                    x: 12 * ui.s
                    spacing: 12 * ui.s
                    Rectangle {
                        width: 36 * ui.s; height: width; radius: width / 2
                        anchors.verticalCenter: parent.verticalCenter
                        color: ui.accentA(ui.dark ? 0.24 : 0.14)
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
                        spacing: 5 * ui.s
                        Row {
                            spacing: 8 * ui.s
                            Text { text: hud.title; color: ui.ink; font.pixelSize: 15 * ui.s; font.weight: Font.DemiBold }
                            Text { text: hud.detail; color: ui.inkDim; font.pixelSize: 15 * ui.s; visible: hud.detail.length > 0 }
                        }
                        Rectangle {
                            visible: hud.progress >= 0
                            width: 150 * ui.s; height: 4 * ui.s; radius: height / 2
                            color: ui.fg(0.10)
                            Rectangle {
                                height: parent.height; radius: parent.radius
                                color: ui.accent
                                width: parent.width * Math.max(0, hud.progress)
                                Behavior on width { SpringAnimation { spring: 7; damping: 0.5; epsilon: 0.2 } }
                            }
                        }
                    }
                    Item { width: 4 * ui.s; height: 1 }
                }
            }
        }
    }
}
