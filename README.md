# Jot-Omarchy
Sticky note style note taking plug-in built for Omarchy

I modeled the plug-in after the native sticky note app that comes with Windowdows. I added checklists and an optional title for the notes but other than that it's pretty bare bones and pretty close to how it is and windows.
<img width="1351" height="872" alt="image" src="https://github.com/user-attachments/assets/3210a1e8-ed0e-46ed-b7ab-72203de03e88" />

The plugin comes with a tray icon that sits next to the 5th workspace but it's currently bugged since there is a known Issue with Omarchy that stops trade icons from appearing consistently.

## Requirements

- Linux with GTK 3
- Python 3
- PyGObject GTK 3 bindings

On Debian, Ubuntu, or related distributions:

```bash
sudo apt install python3 python3-gi gir1.2-gtk-3.0
```

Arch
```bash
sudo pacman -S python python-gobject gtk3
```

## Install and run

Clone or download this repository, then make the launcher executable:

```bash
chmod +x launch-jot
./launch-jot
```

The launcher can also be added to the desktop environment's startup applications using the full path to `launch-jot`.

## Notes and settings

Jot stores notes and settings in the standard user data directory:

```text
~/.local/share/jot/
```

The notes are stored as JSON. The application also provides a settings control for choosing a different notes folder.

## Optional Omarchy integration

The `jot-bar` directory contains the optional Omarchy bar widget. Install it according to the Omarchy plugin documentation, then update the widget's launch command if your Jot executable is installed under a different command name or path.

The core Jot application does not require Omarchy and can run independently on other Linux desktop environments.

## Uninstall

Remove the downloaded Jot directory. To remove saved user data as well, delete the `~/.local/share/jot/` directory after making any backup you want to keep.
