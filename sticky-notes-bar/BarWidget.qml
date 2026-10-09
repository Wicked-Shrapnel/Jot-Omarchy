import QtQuick
import qs.Ui

Item {
  id: root
  property var bar
  property string moduleName: ""
  property var settings: ({})

  implicitWidth: 30
  implicitHeight: bar ? bar.barSize : 26

  Rectangle {
    anchors.fill: parent
    color: "transparent"
    Image {
      anchors.centerIn: parent
      width: 20
      height: 20
      source: Qt.resolvedUrl("../sticky-notes.svg")
      sourceSize.width: 20
      sourceSize.height: 20
      smooth: true
    }
  }
  MouseArea {
    anchors.fill: parent
      onClicked: if (root.bar) root.bar.run("uwsm-app -- sticky-notes --toggle-dock")
  }
}
