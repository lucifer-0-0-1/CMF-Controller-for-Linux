import QtQuick

// Icon by name, pre-tinted in Python (orbit.tint) so no shader effect is involved;
// falls back to a text glyph when there's no SVG for the name.
Item {
    id: root
    property string name: ""
    property string glyph: ""
    property color color: "white"
    property real size: 20
    readonly property string url: name !== "" ? orbit.tint(name, color.toString()) : ""
    width: size; height: size

    Image {
        anchors.fill: parent
        visible: root.url !== ""
        source: root.url
        sourceSize: Qt.size(Math.ceil(root.size * 2), Math.ceil(root.size * 2))
        smooth: true
        mipmap: true
        asynchronous: false
    }
    Text {
        anchors.centerIn: parent
        visible: root.url === ""
        text: root.glyph
        color: root.color
        font.pixelSize: root.size * 0.9
        font.weight: Font.DemiBold
    }
}
