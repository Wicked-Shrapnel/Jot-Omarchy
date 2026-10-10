#!/usr/bin/env python3
import json
import os
import signal
import sys
import time
from pathlib import Path

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gtk, Gdk, GLib, Pango

APP_ID = "com.jot.Notes"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "jot"
DATA_FILE = DATA_DIR / "notes.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
PID_FILE = DATA_DIR / "jot.pid"
ERROR_LOG = DATA_DIR / "startup.log"
COLORS = {
    "yellow": ("#f4d35e", "#3b3000"),
    "purple": ("#e7c6ff", "#32104d"),
    "green": ("#c7f9cc", "#12351a"),
    "blue": ("#c9e8ff", "#102a43"),
}

CHECK_EMPTY = "[ ]"
# U+FE0E explicitly requests text presentation, preventing emoji rendering.
CHECK_DONE = "[✓︎]"
CHECK_FAILED = "[X]"

CONTROL_CSS = b"button.note-control { background-image: none; background-color: #303030; color: #f5f5f5; border: 1px solid #777; border-radius: 4px; padding: 3px 7px; } button.note-control:hover { background-color: #505050; color: white; }"
SUBTLE_CONTROL_CSS = b"button.note-subtle-control { background-image: none; background-color: transparent; color: inherit; border: none; box-shadow: none; padding: 3px 6px; } button.note-subtle-control:hover { background-color: rgba(0, 0, 0, 0.14); border-radius: 4px; }"


def style_control(widget):
    widget.get_style_context().add_class("note-control")
    provider = Gtk.CssProvider()
    provider.load_from_data(CONTROL_CSS)
    widget.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)


def style_subtle_control(widget):
    widget.get_style_context().add_class("note-subtle-control")
    provider = Gtk.CssProvider()
    provider.load_from_data(SUBTLE_CONTROL_CSS)
    widget.get_style_context().add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_USER)


def draw_color_swatch(_area, cr, color):
    rgba = Gdk.RGBA()
    rgba.parse(color)
    width = max(4, _area.get_allocated_width())
    height = max(4, _area.get_allocated_height())
    cr.set_source_rgba(rgba.red, rgba.green, rgba.blue, 1.0)
    cr.rectangle(1, 1, width - 2, height - 2)
    cr.fill()
    cr.set_source_rgba(0.15, 0.12, 0.05, 0.55)
    cr.set_line_width(1.5)
    cr.rectangle(1, 1, width - 2, height - 2)
    cr.stroke()


def send_toggle():
    try:
        os.kill(int(PID_FILE.read_text().strip()), signal.SIGUSR1)
    except (OSError, ValueError, FileNotFoundError):
        pass


def display_date(timestamp=None):
    value = timestamp or time.time()
    return time.strftime("%b %-d, %Y", time.localtime(value))


class NoteWindow(Gtk.Window):
    def __init__(self, app, note):
        super().__init__(title="Sticky Note")
        self.app = app
        app.add_window(self)
        self.note = note
        self.set_decorated(False)
        self.set_keep_above(bool(app.settings.get("always_on_top", True)))
        last_width = int(app.settings.get("last_note_width", 300))
        last_height = int(app.settings.get("last_note_height", 260))
        self.set_default_size(max(240, last_width), max(180, last_height))
        self.resize(max(240, last_width), max(180, last_height))
        if note.get("x") is not None and note.get("y") is not None:
            self.move(note["x"], note["y"])
        self.connect("delete-event", self.hide_to_dock)
        self.connect("configure-event", self.on_move)
        self.connect("focus-out-event", lambda *_: self.remember_size())

        overlay = Gtk.Overlay()
        self.overlay = overlay
        self.add(overlay)
        self.box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        overlay.add(self.box)
        fold = Gtk.DrawingArea()
        fold.set_size_request(34, 34)
        fold.set_halign(Gtk.Align.END)
        fold.set_valign(Gtk.Align.END)
        fold.connect("draw", self.draw_fold)
        fold.get_style_context().add_class("note-fold")
        overlay.add_overlay(fold)
        self.header = Gtk.Box(spacing=4)
        self.header.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.header.connect("button-press-event", self.on_header_button_press)
        self.header.set_margin_start(10)
        self.header.set_margin_end(8)
        self.header.set_margin_top(7)
        self.header.set_margin_bottom(5)
        self.box.pack_start(self.header, False, False, 0)

        self.title = Gtk.Entry()
        self.title.set_text(note.get("title", ""))
        self.title.set_placeholder_text("Name this note (optional)")
        self.title.set_has_frame(False)
        self.title.set_name("note-title")
        self.title.connect("changed", lambda _: self.changed())
        self.title.connect("focus-in-event", lambda *_: self.close_palette())
        self.new_button = Gtk.Button(label="+")
        self.new_button.set_relief(Gtk.ReliefStyle.NONE)
        style_subtle_control(self.new_button)
        self.new_button.set_tooltip_text("New note")
        self.new_button.connect("clicked", lambda *_: self.app.new_note(source=self.note))
        self.header.pack_start(self.new_button, False, False, 0)
        self.header.pack_start(self.title, True, True, 0)
        self.name_area = Gtk.EventBox()
        self.name_area.set_visible_window(False)
        self.name_area.set_hexpand(True)
        self.name_area.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
        self.name_area.connect("button-press-event", self.on_header_button_press)
        self.name_editor = Gtk.Entry()
        self.name_editor.set_text(self.note.get("title", ""))
        self.name_editor.set_placeholder_text("Name note")
        self.name_editor.set_has_frame(False)
        self.name_editor.set_name("note-title")
        self.name_editor.set_hexpand(True)
        self.name_editor.connect("changed", self.on_name_changed)
        self.name_editor.connect("key-press-event", self.on_name_key_press)
        self.name_editor.connect("focus-out-event", lambda *_: self.finish_inline_rename())
        self.name_editor.connect("button-press-event", self.on_header_button_press)
        self.name_area.add(self.name_editor)
        self.header.pack_start(self.name_area, True, True, 0)
        self.name_editor.set_visible(bool(self.note.get("title", "").strip()))
        self.set_title_visible(self.app.settings.get("show_title", False))

        self.header_right = Gtk.Box(spacing=4)
        self.color_button = Gtk.ToggleButton(label="☰")
        self.color_button.set_relief(Gtk.ReliefStyle.NONE)
        style_subtle_control(self.color_button)
        self.color_button.set_tooltip_text("Show note colors")
        self.header_right.pack_start(self.color_button, False, False, 0)

        self.palette_revealer = Gtk.Revealer()
        self.palette_revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self.color_button.connect("toggled", lambda button: self.palette_revealer.set_reveal_child(button.get_active()))
        self.menu_panel = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.palette = Gtk.Box(spacing=5)
        self.palette.set_margin_start(10)
        self.palette.set_margin_bottom(5)
        for name in COLORS:
            b = Gtk.Button()
            b.set_size_request(38, 28)
            style_subtle_control(b)
            b.set_tooltip_text(name.capitalize())
            swatch = Gtk.DrawingArea()
            swatch.set_size_request(28, 18)
            swatch.connect("draw", lambda area, cr, color=COLORS[name][0]: draw_color_swatch(area, cr, color))
            b.add(swatch)
            b.connect("clicked", self.choose_color, name)
            self.palette.pack_start(b, False, False, 0)
        self.menu_panel.pack_start(self.palette, False, False, 0)
        menu_actions = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        notes_list = Gtk.Button(label="☰   Notes list")
        notes_list.set_halign(Gtk.Align.START)
        notes_list.connect("clicked", lambda *_: self.app.show_dock())
        menu_actions.pack_start(notes_list, False, False, 0)
        delete_note = Gtk.Button(label="▣   Delete note")
        delete_note.set_halign(Gtk.Align.START)
        delete_note.connect("clicked", lambda *_: self.app.confirm_delete(self.note, self))
        menu_actions.pack_start(delete_note, False, False, 0)
        self.menu_panel.pack_start(menu_actions, False, False, 0)
        self.palette_revealer.add(self.menu_panel)
        self.palette_revealer.set_halign(Gtk.Align.END)
        self.palette_revealer.set_valign(Gtk.Align.START)
        self.palette_revealer.set_margin_top(42)
        self.palette_revealer.set_margin_end(8)
        overlay.add_overlay(self.palette_revealer)

        hide = Gtk.Button(label="—")
        hide.set_relief(Gtk.ReliefStyle.NONE)
        style_subtle_control(hide)
        hide.set_tooltip_text("Put note in dock")
        hide.connect("clicked", lambda *_: self.hide_to_dock())
        self.header_right.pack_start(hide, False, False, 0)
        close = Gtk.Button(label="×")
        close.set_relief(Gtk.ReliefStyle.NONE)
        style_subtle_control(close)
        close.set_tooltip_text("Put note in dock")
        close.connect("clicked", lambda *_: self.hide_to_dock())
        self.header_right.pack_start(close, False, False, 0)
        self.header.pack_end(self.header_right, False, False, 0)

        self.text = Gtk.TextView()
        self.saved_selection = None
        self.text.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        self.text.set_left_margin(12); self.text.set_right_margin(12)
        self.text.set_top_margin(8); self.text.set_bottom_margin(12)
        note_text = note.get("text", "").replace("[✓]", CHECK_DONE)
        self.text.get_buffer().set_text(note_text)
        self.text.get_buffer().connect("changed", lambda *_: self.changed())
        self.text.connect("focus-in-event", lambda *_: self.close_palette())
        self.text.connect("focus-out-event", self.remember_selection)
        self.text.connect("key-press-event", self.on_text_key_press)
        self.text.connect("button-release-event", self.on_text_button_press)
        self.text.add_events(Gdk.EventMask.POINTER_MOTION_MASK | Gdk.EventMask.LEAVE_NOTIFY_MASK)
        self.text.connect("motion-notify-event", self.on_text_motion)
        self.text.connect("leave-notify-event", self.on_text_leave)
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scroll.add(self.text)
        self.box.pack_start(scroll, True, True, 0)
        buffer = self.text.get_buffer()
        buffer.create_tag("bold", weight=Pango.Weight.BOLD)
        buffer.create_tag("italic", style=Pango.Style.ITALIC)
        buffer.create_tag("underline", underline=Pango.Underline.SINGLE)
        buffer.create_tag("check-empty", foreground="#555555")
        buffer.create_tag("check-red", foreground="#d7263d")
        buffer.create_tag("check-green", foreground="#159447")
        # Keep the marker in a normal text font so it cannot fall back to an emoji font.
        buffer.create_tag("check-marker", font="Adwaita Mono Bold 18")
        self.style_checklist_markers()
        toolbar = Gtk.Box(spacing=3)
        toolbar.get_style_context().add_class("note-toolbar")
        toolbar_css = Gtk.CssProvider()
        toolbar_css.load_from_data(b".note-toolbar, .note-toolbar * { background-color: #303030; color: #e7e7e7; } .note-toolbar button { background-image: none; border: none; box-shadow: none; } .note-toolbar button:hover { background-color: #4a4a4a; }")
        toolbar.get_style_context().add_provider(toolbar_css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION + 1)
        toolbar.set_margin_start(8); toolbar.set_margin_end(8); toolbar.set_margin_bottom(6)
        for icon, tag in (("format-text-bold-symbolic", "bold"), ("format-text-italic-symbolic", "italic"), ("format-text-underline-symbolic", "underline")):
            button = Gtk.Button()
            button.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON))
            button.set_relief(Gtk.ReliefStyle.NONE)
            button.connect("clicked", self.format_selection, tag)
            toolbar.pack_start(button, False, False, 0)
        bullet = Gtk.Button()
        bullet.add(Gtk.Image.new_from_icon_name("view-list-symbolic", Gtk.IconSize.BUTTON))
        bullet.set_relief(Gtk.ReliefStyle.NONE)
        bullet.set_tooltip_text("Insert bullet")
        bullet.connect("clicked", lambda *_: buffer.insert_at_cursor("• "))
        toolbar.pack_start(bullet, False, False, 0)
        checklist = Gtk.Button()
        checklist.add(Gtk.Image.new_from_icon_name("checkbox-checked-symbolic", Gtk.IconSize.BUTTON))
        checklist.set_relief(Gtk.ReliefStyle.NONE)
        checklist.set_tooltip_text("Insert checklist item")
        checklist.connect("clicked", lambda *_: self.insert_checklist_item())
        toolbar.pack_start(checklist, False, False, 0)
        image = Gtk.Button(label="▧")
        image.set_relief(Gtk.ReliefStyle.NONE)
        image.set_tooltip_text("Image placeholder")
        image.connect("clicked", lambda *_: buffer.insert_at_cursor("🖼 "))
        toolbar.pack_start(image, False, False, 0)
        self.box.pack_start(toolbar, False, False, 0)
        self.apply_color()

    def draw_fold(self, _area, cr):
        # A small dog-ear triangle makes each note read as folded paper.
        cr.set_source_rgba(0.28, 0.22, 0.05, 0.20)
        cr.move_to(0, 34); cr.line_to(34, 34); cr.line_to(34, 0); cr.close_path(); cr.fill()
        cr.set_source_rgba(1.0, 1.0, 1.0, 0.45)
        cr.move_to(2, 32); cr.line_to(32, 32); cr.line_to(32, 2); cr.close_path(); cr.fill()
        cr.set_source_rgba(0.28, 0.22, 0.05, 0.35)
        cr.set_line_width(1.0)
        cr.move_to(2, 32); cr.line_to(32, 2); cr.stroke()
        return False

    def choose_color(self, _button, name):
        self.note["color"] = name
        self.app.settings["last_color"] = name
        SETTINGS_FILE.write_text(json.dumps(self.app.settings, indent=2))
        self.apply_color()
        self.color_button.set_active(False)
        self.changed()

    def close_palette(self):
        if self.color_button.get_active():
            self.color_button.set_active(False)

    def set_title_visible(self, visible):
        # Names are edited and displayed inline in the colored header.
        self.title.set_visible(False)

    def on_header_button_press(self, _header, event):
        if event.button == 1 and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self.begin_inline_rename()
            return True
        if event.button != 3:
            return False
        menu = Gtk.Menu()
        rename = Gtk.MenuItem(label="Name note…")
        rename.connect("activate", lambda *_: self.rename_note())
        menu.append(rename)
        menu.show_all()
        menu.popup_at_pointer(event)
        return True

    def begin_inline_rename(self):
        self.name_editor.set_visible(True)
        self.name_editor.grab_focus()
        self.name_editor.select_region(0, -1)

    def on_name_changed(self, entry):
        self.note["title"] = entry.get_text().strip()
        self.app.save()
        self.app.refresh_dock()

    def on_name_key_press(self, _entry, event):
        if event.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.finish_inline_rename()
            return True
        if event.keyval == Gdk.KEY_Escape:
            self.name_editor.set_text(self.note.get("title", ""))
            self.finish_inline_rename()
            return True
        return False

    def finish_inline_rename(self):
        name = self.name_editor.get_text().strip()
        self.note["title"] = name
        self.name_editor.set_text(name)
        self.name_editor.set_visible(bool(name))
        self.text.grab_focus()
        self.changed()

    def rename_note(self):
        dialog = Gtk.Dialog(title="Name note", transient_for=self, flags=0)
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dialog.add_button("Save", Gtk.ResponseType.OK)
        entry = Gtk.Entry()
        entry.set_text(self.note.get("title", ""))
        entry.set_placeholder_text("Optional note name")
        entry.set_margin_start(14); entry.set_margin_end(14)
        entry.set_margin_top(12); entry.set_margin_bottom(8)
        dialog.get_content_area().pack_start(entry, False, False, 0)
        dialog.show_all()
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            self.note["title"] = entry.get_text().strip()
            self.title.set_text(self.note["title"])
            self.name_editor.set_text(self.note["title"])
            self.name_editor.set_visible(bool(self.note["title"]))
            self.changed()
        dialog.destroy()

    def format_selection(self, _button, tag_name):
        buffer = self.text.get_buffer()
        bounds = buffer.get_selection_bounds()
        if len(bounds) == 2:
            buffer.apply_tag_by_name(tag_name, bounds[0], bounds[1])

    def remember_selection(self, *_args):
        buffer = self.text.get_buffer()
        bounds = buffer.get_selection_bounds()
        if len(bounds) == 2 and bounds[0].get_offset() != bounds[1].get_offset():
            self.saved_selection = (bounds[0].get_offset(), bounds[1].get_offset())
        return False

    def insert_checklist_item(self):
        buffer = self.text.get_buffer()
        selection = buffer.get_selection_bounds()
        if len(selection) != 2 and self.saved_selection:
            start_offset, end_offset = self.saved_selection
            selection = (
                buffer.get_iter_at_offset(start_offset),
                buffer.get_iter_at_offset(end_offset),
            )
        if len(selection) == 2:
            selected = buffer.get_text(selection[0], selection[1], True)
            lines = selected.splitlines(True)
            if lines and all((not line.strip()) or line.lstrip().startswith("• ") for line in lines):
                converted = "".join(
                    line.replace("• ", CHECK_EMPTY + " ", 1) if line.lstrip().startswith("• ") else line
                    for line in lines
                )
                insert_offset = selection[0].get_offset()
                buffer.delete(selection[0], selection[1])
                buffer.insert(buffer.get_iter_at_offset(insert_offset), converted)
                self.style_checklist_markers()
                self.saved_selection = None
                self.changed()
                return
        start, end = buffer.get_bounds()
        existing = buffer.get_text(start, end, True).strip()
        cursor = buffer.get_iter_at_mark(buffer.get_insert())
        prefix = CHECK_EMPTY + " " if cursor.starts_line() or cursor.equal(start) else "\n" + CHECK_EMPTY + " "
        if existing and cursor.equal(end):
            prefix = "\n" + CHECK_EMPTY + " "
        buffer.insert_at_cursor(prefix)
        marker_end = buffer.get_iter_at_mark(buffer.get_insert())
        marker_start = marker_end.copy()
        marker_start.backward_chars(4)
        marker_end = marker_start.copy()
        marker_end.forward_chars(3)
        buffer.apply_tag_by_name("check-marker", marker_start, marker_end)
        buffer.apply_tag_by_name("check-empty", marker_start, marker_end)
        self.saved_selection = None
        self.changed()

    def style_checklist_markers(self):
        buffer = self.text.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), True)
        offset = 0
        for line in text.splitlines(True):
            marker = next((item for item in (CHECK_EMPTY, CHECK_DONE, CHECK_FAILED)
                           if line.startswith(item + " ")), None)
            if marker:
                start = buffer.get_iter_at_offset(offset)
                end = buffer.get_iter_at_offset(offset + len(marker))
                buffer.apply_tag_by_name("check-marker", start, end)
                if marker == CHECK_DONE:
                    buffer.apply_tag_by_name("check-green", start, end)
                elif marker == CHECK_FAILED:
                    buffer.apply_tag_by_name("check-red", start, end)
                else:
                    buffer.apply_tag_by_name("check-empty", start, end)
            offset += len(line)

    def on_text_key_press(self, _view, event):
        self.close_palette()
        if event.keyval in (Gdk.KEY_BackSpace, Gdk.KEY_Delete):
            if self.delete_checklist_marker(event.keyval == Gdk.KEY_BackSpace):
                return True
        if event.keyval not in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return False
        buffer = self.text.get_buffer()
        cursor = buffer.get_iter_at_mark(buffer.get_insert())
        line_start = cursor.copy()
        line_start.set_line_offset(0)
        line_text = buffer.get_text(line_start, cursor, False)
        prefix = None
        checklist_marker = None
        if line_text.startswith("• "):
            prefix = "• "
        else:
            checklist_marker = next(
                (item for item in (CHECK_EMPTY, CHECK_DONE, CHECK_FAILED)
                 if line_text.startswith(item + " ")),
                None,
            )
        if checklist_marker:
            prefix = CHECK_EMPTY + " "
        if not prefix:
            return False
        content_offset = len(checklist_marker) + 1 if checklist_marker else len(prefix)
        if not line_text[content_offset:].strip():
            buffer.delete(line_start, cursor)
            return False
        buffer.insert_at_cursor("\n" + prefix)
        if checklist_marker:
            marker_end = buffer.get_iter_at_mark(buffer.get_insert())
            marker_start = marker_end.copy()
            marker_start.backward_chars(len(CHECK_EMPTY) + 1)
            styled_end = marker_start.copy()
            styled_end.forward_chars(len(CHECK_EMPTY))
            buffer.apply_tag_by_name("check-marker", marker_start, styled_end)
            buffer.apply_tag_by_name("check-empty", marker_start, styled_end)
        return True

    def delete_checklist_marker(self, backspace):
        buffer = self.text.get_buffer()
        cursor = buffer.get_iter_at_mark(buffer.get_insert())
        line_start = cursor.copy()
        line_start.set_line_offset(0)
        line_end = line_start.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        line = buffer.get_text(line_start, line_end, False)
        marker = next((item for item in (CHECK_EMPTY, CHECK_DONE, CHECK_FAILED)
                       if line.startswith(item + " ")), None)
        if marker is None:
            return False
        marker_start_offset = line_start.get_offset()
        marker_end_offset = marker_start_offset + len(marker) + 1
        cursor_offset = cursor.get_offset()
        if backspace:
            if not (marker_start_offset < cursor_offset <= marker_end_offset):
                return False
        elif not (marker_start_offset <= cursor_offset < marker_end_offset):
            return False
        start = buffer.get_iter_at_offset(marker_start_offset)
        end = buffer.get_iter_at_offset(marker_end_offset)
        buffer.delete(start, end)
        self.changed()
        return True

    def on_text_button_press(self, _view, event):
        if event.button != 1:
            return False
        buffer = self.text.get_buffer()
        buffer_x, buffer_y = self.text.window_to_buffer_coords(
            Gtk.TextWindowType.TEXT, int(event.x), int(event.y)
        )
        hit_result = self.text.get_iter_at_location(buffer_x, buffer_y)
        hit = hit_result[1] if isinstance(hit_result, tuple) else hit_result
        line_start = hit.copy()
        line_start.set_line_offset(0)
        line_end = line_start.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        line = buffer.get_text(line_start, line_end, False)
        current = next((item for item in (CHECK_EMPTY, CHECK_DONE, CHECK_FAILED)
                        if line.startswith(item + " ")), None)
        if current is None:
            return False
        hit_offset = hit.get_offset() - line_start.get_offset()
        if hit_offset < 0 or hit_offset >= len(current):
            return False
        start_offset = line_start.get_offset()
        marker_end = line_start.copy()
        marker_end.forward_chars(len(current))
        replacement = {
            CHECK_EMPTY: CHECK_DONE,
            CHECK_DONE: CHECK_FAILED,
            CHECK_FAILED: CHECK_EMPTY,
        }[current]
        buffer.delete(line_start, marker_end)
        insert_at = buffer.get_iter_at_offset(start_offset)
        buffer.insert(insert_at, replacement)
        styled_start = buffer.get_iter_at_offset(start_offset)
        styled_end = buffer.get_iter_at_offset(start_offset + len(replacement))
        buffer.apply_tag_by_name("check-marker", styled_start, styled_end)
        if replacement == CHECK_DONE:
            buffer.apply_tag_by_name("check-green", styled_start, styled_end)
        elif replacement == CHECK_FAILED:
            buffer.apply_tag_by_name("check-red", styled_start, styled_end)
        else:
            buffer.apply_tag_by_name("check-empty", styled_start, styled_end)
        self.changed()
        return True

    def on_text_motion(self, _view, event):
        buffer_x, buffer_y = self.text.window_to_buffer_coords(
            Gtk.TextWindowType.TEXT, int(event.x), int(event.y)
        )
        hit_result = self.text.get_iter_at_location(buffer_x, buffer_y)
        hit = hit_result[1] if isinstance(hit_result, tuple) else hit_result
        line_start = hit.copy()
        line_start.set_line_offset(0)
        line_end = line_start.copy()
        if not line_end.ends_line():
            line_end.forward_to_line_end()
        line = self.text.get_buffer().get_text(line_start, line_end, False)
        marker = next((item for item in (CHECK_EMPTY, CHECK_DONE, CHECK_FAILED)
                       if line.startswith(item + " ")), None)
        over_marker = marker is not None and 0 <= hit.get_offset() - line_start.get_offset() < len(marker)
        display = self.text.get_display()
        cursor_name = "pointer" if over_marker else "text"
        self.text.get_window(Gtk.TextWindowType.TEXT).set_cursor(
            Gdk.Cursor.new_from_name(display, cursor_name)
        )
        return False

    def on_text_leave(self, *_args):
        display = self.text.get_display()
        self.text.get_window(Gtk.TextWindowType.TEXT).set_cursor(
            Gdk.Cursor.new_from_name(display, "text")
        )
        return False

    def apply_color(self):
        bg, fg = COLORS.get(self.note.get("color", "yellow"), COLORS["yellow"])
        css = Gtk.CssProvider()
        css.load_from_data(f"* {{ background-color: {bg}; color: {fg}; }} entry, textview {{ color: {fg}; }} #note-title, #note-title:focus {{ color: #000000; background-color: transparent; font-weight: 900; font-size: 15px; padding: 2px 6px; }} button {{ color: {fg}; }} drawingarea.note-fold {{ background-color: transparent; }}".encode())
        self.get_style_context().add_provider(css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        if hasattr(self, "name_editor"):
            black = Gdk.RGBA(); black.parse("#000000")
            for state in (Gtk.StateFlags.NORMAL, Gtk.StateFlags.FOCUSED, Gtk.StateFlags.PRELIGHT):
                self.name_editor.override_color(state, black)
        self.color_button.set_label("☰")

    def changed(self):
        buf = self.text.get_buffer()
        if hasattr(self, "name_editor"):
            self.note["title"] = self.name_editor.get_text().strip()
        else:
            self.note["title"] = self.title.get_text().strip()
        self.note["text"] = buf.get_text(buf.get_start_iter(), buf.get_end_iter(), True)
        self.note["updated"] = display_date(self.note["updated_at"])
        self.note["updated_at"] = time.time()
        self.app.save()
        self.app.refresh_dock()

    def on_move(self, _widget, _event):
        self.note["x"], self.note["y"] = self.get_position()
        if self.is_visible() and self.is_active():
            self.remember_size()
        self.app.save()
        return False

    def remember_size(self):
        width, height = self.get_size()
        if width < 240 or height < 180:
            return False
        self.app.settings["last_note_width"] = width
        self.app.settings["last_note_height"] = height
        SETTINGS_FILE.write_text(json.dumps(self.app.settings, indent=2))
        return False

    def hide_to_dock(self, *_args):
        self.remember_size()
        if not self.note.get("title", "").strip() and not self.note.get("text", "").strip():
            self.app.delete_note(self.note)
            return True
        self.note["open"] = False
        self.note["updated"] = display_date()
        self.note["updated_at"] = time.time()
        self.hide()
        if self.app.dock:
            self.app.dock.set_keep_above(True)
        self.app.save()
        self.app.refresh_dock()
        return True

    def show_note(self):
        self.note["open"] = True
        self.note["updated"] = display_date()
        self.note["updated_at"] = time.time()
        width = max(240, int(self.app.settings.get("last_note_width", 300)))
        height = max(180, int(self.app.settings.get("last_note_height", 260)))
        self.resize(width, height)
        if self.app.dock:
            self.app.dock.set_keep_above(False)
        self.show_all()
        self.move(int(self.note.get("x", 160)), int(self.note.get("y", 110)))
        self.set_title_visible(self.app.settings.get("show_title", False))
        self.present()
        self.app.relocate_if_overlapping(self)
        self.app.save()
        self.app.refresh_dock()


class Jot(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID)
        self.notes = []
        self.windows = {}
        self.settings = {"show_title": False, "last_color": "yellow", "always_on_top": True}
        self.notes_dir = DATA_DIR
        self.notes_file = DATA_FILE
        self.dock = None
        self.dock_list = None
        self.connect("activate", self.activate)

    def activate(self, _app):
        if self.windows:
            self.dock.show_all()
            self.dock.present()
            return
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PID_FILE.write_text(str(os.getpid()))
        try:
            self.settings.update(json.loads(SETTINGS_FILE.read_text()))
        except (OSError, ValueError):
            pass
        configured_dir = self.settings.get("notes_location", "")
        if configured_dir:
            self.notes_dir = Path(configured_dir).expanduser()
            self.notes_file = self.notes_dir / "notes.json"
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.notes = json.loads(self.notes_file.read_text())
        except (OSError, ValueError):
            self.notes = []
        self.notes = [note for note in self.notes if note.get("title", "").strip() or note.get("text", "").strip()]
        for note in self.notes:
            if note.get("title", "").strip() in ("Note", "New note"):
                note["title"] = ""
        if not self.notes:
            self.notes = [{"id": "note-1", "title": "Welcome", "text": "Your sticky notes live here.", "color": "yellow", "open": True, "updated": display_date(), "updated_at": time.time(), "x": 120, "y": 90}]
        for note in self.notes:
            note.setdefault("updated_at", 0)
            note["updated"] = display_date(note.get("updated_at") or time.time())
        for note in self.notes:
            self.windows[note["id"]] = NoteWindow(self, note)
            if note.get("open", True):
                self.windows[note["id"]].show_all()
                self.windows[note["id"]].set_title_visible(self.settings.get("show_title", False))
        self.make_dock()
        self.refresh_dock()
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signal.SIGUSR1, self.toggle_dock)

    def save(self):
        self.notes_dir.mkdir(parents=True, exist_ok=True)
        saved_notes = [note for note in self.notes if note.get("title", "").strip() or note.get("text", "").strip()]
        self.notes_file.write_text(json.dumps(saved_notes, indent=2))

    def make_dock(self):
        self.dock = Gtk.Window(title="Jot")
        self.add_window(self.dock)
        self.dock.set_default_size(320, 620)
        self.dock.set_decorated(False)
        self.dock.set_keep_above(True)
        self.dock.connect("delete-event", lambda *_: self.dock.hide() or True)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.set_margin_top(10); outer.set_margin_bottom(10); outer.set_margin_start(12); outer.set_margin_end(12)
        self.dock.add(outer)
        header = Gtk.Box(spacing=6)
        new = Gtk.Button(label="+")
        style_subtle_control(new)
        new.set_tooltip_text("New note")
        new.connect("clicked", lambda *_: self.new_note())
        header.pack_start(new, False, False, 0)
        label = Gtk.Label(label="Jot")
        label.set_xalign(0)
        header.pack_start(label, True, True, 0)
        settings = Gtk.Button()
        settings.add(Gtk.Image.new_from_icon_name("emblem-system-symbolic", Gtk.IconSize.BUTTON))
        settings.set_relief(Gtk.ReliefStyle.NONE)
        style_subtle_control(settings)
        settings.set_opacity(0.72)
        settings.set_tooltip_text("Jot settings")
        settings_popover = Gtk.Popover()
        settings_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        settings_box.get_style_context().add_class("settings-panel")
        settings_css = Gtk.CssProvider()
        settings_css.load_from_data(b".settings-panel, .settings-panel * { background-color: #303030; color: #f5f5f5; } .settings-panel checkbutton { padding: 8px; }")
        settings_box.get_style_context().add_provider(settings_css, Gtk.STYLE_PROVIDER_PRIORITY_USER)
        settings_box.set_margin_top(10); settings_box.set_margin_bottom(10)
        settings_box.set_margin_start(10); settings_box.set_margin_end(10)
        title_setting = Gtk.CheckButton(label="Show note name field")
        title_setting.set_active(self.settings.get("show_title", False))
        title_setting.connect("toggled", lambda button: self.set_show_title(button.get_active()))
        settings_box.pack_start(title_setting, False, False, 0)
        top_setting = Gtk.CheckButton(label="Keep notes above other windows")
        top_setting.set_active(self.settings.get("always_on_top", True))
        top_setting.connect("toggled", lambda button: self.set_always_on_top(button.get_active()))
        settings_box.pack_start(top_setting, False, False, 0)
        pending_note = Gtk.Label(label="Startup and bar options below are placeholders and are not ready yet.")
        pending_note.set_xalign(0)
        pending_note.set_line_wrap(True)
        pending_note.set_opacity(0.75)
        settings_box.pack_start(pending_note, False, False, 0)
        start_setting = Gtk.CheckButton(label="Start Jot on login (not ready)")
        start_setting.set_active(False)
        start_setting.set_sensitive(False)
        settings_box.pack_start(start_setting, False, False, 0)
        bar_setting = Gtk.CheckButton(label="Keep Jot in the bar (not ready)")
        bar_setting.set_active(False)
        bar_setting.set_sensitive(False)
        settings_box.pack_start(bar_setting, False, False, 0)
        location_title = Gtk.Label(label="Notes location")
        location_title.set_xalign(0)
        settings_box.pack_start(location_title, False, False, 0)
        self.location_label = Gtk.Label(label=str(self.notes_dir))
        self.location_label.set_xalign(0)
        self.location_label.set_line_wrap(True)
        self.location_label.set_selectable(True)
        settings_box.pack_start(self.location_label, False, False, 0)
        location_picker = Gtk.FileChooserButton(title="Choose notes folder", action=Gtk.FileChooserAction.SELECT_FOLDER)
        location_picker.set_tooltip_text("Choose where notes.json is stored")
        location_picker.set_filename(str(self.notes_dir))
        location_picker.connect("file-set", lambda picker: self.set_notes_location(picker.get_filename()))
        settings_box.pack_start(location_picker, False, False, 0)
        settings_popover.add(settings_box)
        settings_popover.set_relative_to(settings)
        settings.connect("clicked", lambda *_: self.toggle_settings(settings_popover))
        header.pack_start(settings, False, False, 0)
        close = Gtk.Button(label="×")
        close.set_relief(Gtk.ReliefStyle.NONE)
        style_subtle_control(close)
        close.set_tooltip_text("Close notes list")
        close.connect("clicked", lambda *_: self.dock.hide())
        header.pack_start(close, False, False, 0)
        outer.pack_start(header, False, False, 0)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search notes…")
        self.search.connect("search-changed", lambda *_: self.refresh_dock())
        outer.pack_start(self.search, False, False, 0)
        self.dock_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=5)
        self.dock_scroll = Gtk.ScrolledWindow()
        self.dock_scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.dock_scroll.add(self.dock_list)
        outer.pack_start(self.dock_scroll, True, True, 0)

    def refresh_dock(self):
        if not self.dock_list:
            return
        for child in self.dock_list.get_children():
            self.dock_list.remove(child)
        query = self.search.get_text().strip().lower() if getattr(self, "search", None) else ""
        notes = sorted(
            self.notes,
            key=lambda note: note.get("updated_at", 0),
            reverse=True,
        )
        if query:
            notes = [n for n in notes if query in n.get("title", "").lower() or query in n.get("text", "").lower()]
        if not notes:
            self.dock_list.pack_start(Gtk.Label(label="No matching notes" if query else "No notes yet"), False, False, 8)
        for note in notes:
            color = note.get("color", "yellow")
            bg, _fg = COLORS.get(color, COLORS["yellow"])
            summary = " ".join(note.get("text", "").split()) or "Empty note"
            if self.settings.get("show_title", False):
                if len(summary) > 110:
                    summary = summary[:107] + "…"
            elif len(summary) > 220:
                summary = summary[:217] + "…"
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
            stripe = Gtk.DrawingArea()
            stripe.set_size_request(-1, 5)
            stripe.connect("draw", lambda area, cr, color=bg: draw_color_swatch(area, cr, color))
            card.pack_start(stripe, False, False, 0)
            row = Gtk.Box(spacing=8)
            row.set_margin_top(8); row.set_margin_bottom(8); row.set_margin_start(10); row.set_margin_end(10)
            details = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            title = Gtk.Label(label=note.get("title", ""))
            title.set_xalign(0)
            title.set_line_wrap(True)
            title.set_max_width_chars(28)
            title.set_opacity(0.95)
            title.set_name("note-card-title")
            snippet = Gtk.Label(label=summary)
            snippet.set_xalign(0)
            snippet.set_line_wrap(True)
            snippet.set_max_width_chars(28)
            timestamp = Gtk.Label(label=note.get("updated", ""))
            timestamp.set_xalign(0)
            timestamp.set_opacity(0.65)
            if note.get("title", "").strip():
                details.pack_start(title, False, False, 0)
            details.pack_start(snippet, False, False, 0)
            details.pack_start(timestamp, False, False, 0)
            row.pack_start(details, True, True, 0)
            card.pack_start(row, False, False, 0)
            b = Gtk.Button()
            b.add(card)
            style_control(b)
            b.connect("clicked", lambda _b, n=note: self.windows[n["id"]].show_note())
            b.add_events(Gdk.EventMask.BUTTON_PRESS_MASK)
            b.connect("button-press-event", self.on_note_card_press, note)
            self.dock_list.pack_start(b, False, False, 0)
        self.dock_list.show_all()

    def on_note_card_press(self, _button, event, note):
        if event.button == 1 and event.type == Gdk.EventType.DOUBLE_BUTTON_PRESS:
            self.windows[note["id"]].rename_note()
            return True
        return False

    def show_dock(self):
        self.refresh_dock()
        self.dock.show_all()
        self.dock.present()

    def toggle_settings(self, popover):
        if popover.get_visible():
            popover.popdown()
        else:
            popover.show_all()
            popover.popup()

    def set_show_title(self, enabled):
        self.settings["show_title"] = bool(enabled)
        SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2))
        for window in self.windows.values():
            window.set_title_visible(enabled)
        self.refresh_dock()

    def set_always_on_top(self, enabled):
        self.settings["always_on_top"] = bool(enabled)
        SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2))
        for window in self.windows.values():
            window.set_keep_above(bool(enabled))

    def set_notes_location(self, folder):
        if not folder:
            return
        new_dir = Path(folder).expanduser()
        if new_dir == self.notes_dir:
            return
        new_dir.mkdir(parents=True, exist_ok=True)
        new_file = new_dir / "notes.json"
        existing = []
        if new_file.exists():
            try:
                existing = json.loads(new_file.read_text())
            except (OSError, ValueError):
                existing = []
        merged = {note.get("id"): note for note in existing if note.get("id")}
        merged.update({note.get("id"): note for note in self.notes if note.get("id")})
        new_file.write_text(json.dumps(list(merged.values()), indent=2))
        self.notes_dir = new_dir
        self.notes_file = new_file
        self.settings["notes_location"] = str(new_dir)
        SETTINGS_FILE.write_text(json.dumps(self.settings, indent=2))
        self.location_label.set_text(str(new_dir))

    def confirm_delete(self, note, window):
        dialog = Gtk.MessageDialog(transient_for=window, flags=0, message_type=Gtk.MessageType.QUESTION, buttons=Gtk.ButtonsType.OK_CANCEL, text="Delete this note?")
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.OK:
            self.delete_note(note)

    def delete_note(self, note):
        window = self.windows.pop(note["id"], None)
        if window:
            self.remove_window(window)
            window.destroy()
        self.notes = [item for item in self.notes if item["id"] != note["id"]]
        self.save()
        self.refresh_dock()

    def new_note(self, source=None):
        i = 1
        ids = {n["id"] for n in self.notes}
        while f"note-{i}" in ids: i += 1
        color = source.get("color") if source else self.settings.get("last_color", "yellow")
        source_x = source.get("x", 160) if source else 160
        source_y = source.get("y", 110) if source else 110
        note_x, note_y = self.find_clear_note_position(source_x, source_y)
        note = {"id": f"note-{i}", "title": "", "text": "", "color": color, "open": True, "updated": display_date(), "updated_at": time.time(), "x": note_x, "y": note_y}
        self.notes.append(note)
        self.windows[note["id"]] = NoteWindow(self, note)
        window = self.windows[note["id"]]
        if source:
            window.set_opacity(0.0)
        window.show_note()
        if source:
            self.animate_new_note(window)

    def find_clear_note_position(self, origin_x, origin_y, exclude=None):
        width = max(240, int(self.settings.get("last_note_width", 300)))
        height = max(180, int(self.settings.get("last_note_height", 260)))
        occupied = []
        excluded_id = exclude.note.get("id") if exclude else None
        for other_note in self.notes:
            if other_note.get("id") == excluded_id or not other_note.get("open", True):
                continue
            occupied.append((
                int(other_note.get("x", 160)),
                int(other_note.get("y", 110)),
                width,
                height,
            ))
        for other in self.windows.values():
            if other is exclude:
                continue
            if not other.get_visible():
                continue
            x, y = other.get_position()
            w, h = other.get_size()
            occupied.append((x, y, max(width, w), max(height, h)))

        # Search the desktop grid, rather than cascading from saved note coordinates.
        # This prevents stale positions from causing later notes to stack.
        for row in range(20):
            for column in range(20):
                x = 80 + column * (width + 18)
                y = 80 + row * (height + 18)
                candidate = (x, y, width, height)
                if not any(
                    x < ox + ow and x + width > ox and
                    y < oy + oh and y + height > oy
                    for ox, oy, ow, oh in occupied
                ):
                    return x, y
        return origin_x + width + 18, origin_y + height + 18

    def relocate_if_overlapping(self, window):
        if not window.get_visible():
            return
        x, y = window.get_position()
        width, height = window.get_size()
        for other in self.windows.values():
            if other is window or not other.get_visible():
                continue
            ox, oy = other.get_position()
            ow, oh = other.get_size()
            if x < ox + ow and x + width > ox and y < oy + oh and y + height > oy:
                new_x, new_y = self.find_clear_note_position(x, y, exclude=window)
                window.move(new_x, new_y)
                window.note["x"], window.note["y"] = new_x, new_y
                return

    def animate_new_note(self, window):
        step = {"value": 0}

        def advance():
            step["value"] += 1
            window.set_opacity(min(1.0, step["value"] / 6.0))
            if step["value"] < 6:
                return True
            window.set_opacity(1.0)
            return False

        GLib.timeout_add(25, advance)

    def toggle_dock(self):
        if self.dock.get_visible(): self.dock.hide()
        else: self.dock.show_all(); self.dock.present()
        return True

    def do_shutdown(self):
        try: PID_FILE.unlink()
        except OSError: pass
        Gtk.Application.do_shutdown(self)


if __name__ == "__main__":
    if "--toggle-dock" in sys.argv:
        send_toggle(); sys.exit(0)
    try:
        app = Jot()
        raise SystemExit(app.run(sys.argv))
    except Exception as exc:
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            ERROR_LOG.write_text(f"{type(exc).__name__}: {exc}\n", encoding="utf-8")
        finally:
            raise
