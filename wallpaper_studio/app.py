"""The Wallpaper Studio window: pick a wallpaper, see its colours, choose light or dark."""
import concurrent.futures
import logging
import os
import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Adw, Gdk, GdkPixbuf, Gio, GLib, Gtk  # noqa: E402

from . import core, styles  # noqa: E402

APP_ID = "io.github.WallpaperStudio"
THUMB_W, THUMB_H = 480, 270          # pixels on disk; shown at half size, sharp on HiDPI screens
ROTATIONS = [(0, "Never"), (1, "Every hour"), (3, "Every 3 hours"), (5, "Every 5 hours"),
             (12, "Every 12 hours"), (24, "Once a day")]
SWATCHES = ["paper", "sheet", "ink", "muted", "accent"]
AWAKE_CHOICES = [(None, "Off"), (30, "For 30 minutes"), (60, "For 1 hour"), (120, "For 2 hours"),
                 (core.FOREVER, "Until I turn it off")]

def cover(path, width, height):
    """The picture scaled to fill width × height, centre-cropped."""
    _fmt, w, h = GdkPixbuf.Pixbuf.get_file_info(path)
    if not w or not h:
        raise GLib.Error("unreadable")
    k = max(width / w, height / h)
    pb = GdkPixbuf.Pixbuf.new_from_file_at_scale(path, max(width, round(w * k)), max(height, round(h * k)), False)
    return pb.new_subpixbuf((pb.get_width() - width) // 2, (pb.get_height() - height) // 2, width, height)


def thumbnail(path):
    """A cached 16:9 thumbnail as a pixbuf, or None."""
    out = os.path.join(core.CACHE_DIR, "thumbs", core._cache_name(path, ".png"))
    if os.path.exists(out):
        return GdkPixbuf.Pixbuf.new_from_file(out)
    still = core.still_of(path)
    if still is None:
        return None
    pb = cover(still, THUMB_W, THUMB_H)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    pb.savev(out, "png", [], [])
    return pb


def swatch(colour):
    area = Gtk.DrawingArea(content_width=26, content_height=26, tooltip_text=colour)
    area.add_css_class("swatch")
    area.set_overflow(Gtk.Overflow.HIDDEN)
    rgba = Gdk.RGBA()
    rgba.parse(colour)

    def draw(_area, cr, w, h):
        cr.set_source_rgb(rgba.red, rgba.green, rgba.blue)
        cr.rectangle(0, 0, w, h)
        cr.fill()
        cr.set_source_rgba(0.5, 0.5, 0.5, 0.35)
        cr.set_line_width(2)
        cr.rectangle(0, 0, w, h)
        cr.stroke()
    area.set_draw_func(draw)
    return area


class Window(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app, title="Wallpaper Studio", default_width=900, default_height=780)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
        self.thumbs = {}            # path -> button in the grid
        self.busy = False
        self.showing_awake = False
        self.syncing_config = False
        self.mode_buttons = {}
        self.switches = {}
        self.config = core.load_config()

        self.toasts = Adw.ToastOverlay()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        box.append(self.build_header())
        scroller = Gtk.ScrolledWindow(vexpand=True, hscrollbar_policy=Gtk.PolicyType.NEVER)
        clamp = Adw.Clamp(maximum_size=860, tightening_threshold=600)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=28,
                       margin_top=24, margin_bottom=32, margin_start=16, margin_end=16)
        page.append(self.build_now())
        page.append(self.build_library())
        page.append(self.build_options())
        clamp.set_child(page)
        scroller.set_child(clamp)
        box.append(scroller)
        self.toasts.set_child(box)
        self.set_content(self.toasts)

        drop = Gtk.DropTarget.new(Gio.File, Gdk.DragAction.COPY)
        drop.connect("drop", lambda _t, file, *_: self.use(file.get_path()) or True)
        self.add_controller(drop)

        # the helper may change the wallpaper on its own (rotation); follow along
        os.makedirs(core.CONFIG_DIR, exist_ok=True)
        self.refresh_timer = 0
        self.monitor = Gio.File.new_for_path(core.CONFIG_DIR).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.monitor.connect("changed", self.on_file_change)
        self.show_current()
        self.load_library()
        self.set_focus(self.first_focus)     # otherwise focus lands in the grid and scrolls the top away

    # --- layout --------------------------------------------------------------------------

    def build_header(self):
        header = Adw.HeaderBar()
        self.spinner = Gtk.Spinner()
        header.pack_start(self.spinner)

        menu = Gio.Menu()
        menu.append("Restore original look", "win.restore")
        menu.append("About Wallpaper Studio", "win.about")
        header.pack_end(Gtk.MenuButton(icon_name="open-menu-symbolic", menu_model=menu, tooltip_text="Menu"))
        for name, handler in (("restore", self.ask_restore), ("about", self.about)):
            action = Gio.SimpleAction.new(name, None)
            action.connect("activate", handler)
            self.add_action(action)
        return header

    def build_now(self):
        row = Gtk.Box(spacing=24)
        self.hero = Gtk.Picture(can_shrink=True, keep_aspect_ratio=True, width_request=384, height_request=216)
        self.hero.add_css_class("hero")
        self.hero.add_css_class("card")
        self.hero.set_overflow(Gtk.Overflow.HIDDEN)
        row.append(self.hero)

        info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10, valign=Gtk.Align.CENTER, hexpand=True)
        self.title = Gtk.Label(xalign=0, wrap=True, css_classes=["title-2"])
        self.subtitle = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"])
        info.append(self.title)
        info.append(self.subtitle)
        self.palettes = Gtk.Grid(row_spacing=6, column_spacing=6, margin_top=6)
        info.append(self.palettes)

        buttons = Gtk.Box(spacing=8, margin_top=8)
        nxt = Gtk.Button(label="Next wallpaper", css_classes=["suggested-action", "pill"])
        nxt.connect("clicked", lambda _b: self.run(core.next_wallpaper, "Nothing else in this folder yet"))
        pick = Gtk.Button(label="Open a file…", css_classes=["pill"])
        pick.connect("clicked", self.choose_file)
        buttons.append(nxt)
        buttons.append(pick)
        info.append(buttons)
        row.append(info)
        self.first_focus = nxt
        return row

    def build_library(self):
        group = Adw.PreferencesGroup(title="Your wallpapers")
        change = Gtk.Button(label="Change folder…", css_classes=["flat"], valign=Gtk.Align.CENTER)
        change.connect("clicked", self.choose_folder)
        group.set_header_suffix(change)
        self.library_group = group

        self.grid = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE, homogeneous=True,
                                min_children_per_line=3, max_children_per_line=3,
                                row_spacing=12, column_spacing=12, margin_top=6)
        self.empty = Adw.StatusPage(icon_name="folder-pictures-symbolic", title="No wallpapers here yet",
                                    description="Put pictures or videos in this folder, choose another "
                                                "folder, or drop a file on this window.")
        self.empty.add_css_class("compact")
        group.add(self.grid)
        group.add(self.empty)
        return group

    def build_options(self):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)

        look = Adw.PreferencesGroup(title="Colours")
        mode_row = Adw.ActionRow(title="Light or dark",
                                 subtitle=f"Auto is light from {self.config['light_from']:02d}:00 "
                                          f"and dark from {self.config['dark_from']:02d}:00")
        self.mode_row = mode_row
        modes = Gtk.Box(css_classes=["linked"], valign=Gtk.Align.CENTER)
        first = None
        for mode, label in (("light", "Light"), ("dark", "Dark"), ("auto", "Auto")):
            button = Gtk.ToggleButton(label=label, group=first, active=self.config["mode"] == mode)
            button.connect("toggled", self.on_mode, mode)
            self.mode_buttons[mode] = button
            first = first or button
            modes.append(button)
        mode_row.add_suffix(modes)
        look.add(mode_row)
        look.add(self.switch_row("See-through windows", "Let the wallpaper show behind app windows", "glass"))
        look.add(self.switch_row("Recolour the Terminal", "Adds a “Wallpaper Studio” profile to GNOME Terminal",
                                 "terminal"))
        look.add(self.switch_row("Lock screen", "Show the wallpaper when the screen is locked", "lock_screen"))
        box.append(look)

        widgets = Adw.PreferencesGroup(title="Desktop widgets",
                                       description="Style the clock in ~/.config/wallpaper-studio/widgets.css")
        widgets.add(self.switch_row("Desktop clock", "Show time and date at the top centre of the desktop", "clock"))
        box.append(widgets)

        auto = Adw.PreferencesGroup(title="Change automatically",
                                    description="Picks a random wallpaper from your folder.")
        combo = Adw.ComboRow(title="New wallpaper")
        self.rotation_combo = combo
        self.update_rotation()
        combo.connect("notify::selected", self.on_rotation)
        auto.add(combo)
        box.append(auto)

        screen = Adw.PreferencesGroup(title="Screen")
        self.awake_row = Adw.ComboRow(title="Keep screen awake",
                                      model=Gtk.StringList.new([label for _m, label in AWAKE_CHOICES]))
        self.awake_row.connect("notify::selected", self.on_awake)
        screen.add(self.awake_row)
        method = Adw.ComboRow(title="Keep-awake method", model=Gtk.StringList.new(["GNOME + periodic F15 key", "GNOME inhibitor only"]),
                             subtitle="Key events run only while Keep screen awake is on")
        method.set_selected(0 if self.config["awake_method"] == "key" else 1)
        method.connect("notify::selected", lambda c, _p: self.save(awake_method="key" if c.get_selected() == 0 else "inhibit"))
        self.awake_method_combo = method
        screen.add(method)
        box.append(screen)
        self.show_awake()
        GLib.timeout_add_seconds(30, self.show_awake)     # count down, and notice when it runs out
        return box

    def on_awake(self, row, _param):
        if self.showing_awake:
            return
        core.keep_awake(AWAKE_CHOICES[row.get_selected()][0])
        self.show_awake()

    def update_rotation(self):
        choices = list(ROTATIONS)
        hours = self.config["rotate_hours"]
        if hours not in [h for h, _label in choices]:
            choices.append((hours, f"Every {hours:g} hours"))
        self.rotation_hours = [h for h, _label in choices]
        self.rotation_combo.set_model(Gtk.StringList.new([label for _h, label in choices]))
        self.rotation_combo.set_selected(self.rotation_hours.index(hours))

    def on_rotation(self, row, _param):
        if not self.syncing_config and row.get_selected() < len(self.rotation_hours):
            self.save(rotate_hours=self.rotation_hours[row.get_selected()])

    def show_awake(self):
        """Show whether "keep awake" is on and until when; it ends at logout either way."""
        until = core.awake_until()
        self.showing_awake = True
        if until is None:
            self.awake_row.set_selected(0)
            self.awake_row.set_subtitle("The screen locks after you've been away for a while, as usual")
        elif until == core.FOREVER:
            self.awake_row.set_selected(len(AWAKE_CHOICES) - 1)
            self.awake_row.set_subtitle("On until you turn it off or log out. Lock it yourself (Super+L) "
                                        "when you walk away")
        else:
            choices = [m for m, _l in AWAKE_CHOICES]
            minutes = core.awake_minutes()
            self.awake_row.set_selected(choices.index(minutes) if minutes in choices else 2)
            self.awake_row.set_subtitle(GLib.DateTime.new_from_unix_local(int(until)).format(
                "On until %H:%M. Lock it yourself (Super+L) when you walk away"))
        self.showing_awake = False
        return True

    def switch_row(self, title, subtitle, key):
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        switch = Gtk.Switch(active=self.config[key], valign=Gtk.Align.CENTER)
        switch.connect("notify::active", lambda s, _p: self.save(recolour=True, **{key: s.get_active()}))
        self.switches[key] = switch
        row.add_suffix(switch)
        row.set_activatable_widget(switch)
        return row

    # --- showing state -------------------------------------------------------------------

    def on_file_change(self, _monitor, file, _other, _event):
        if file.get_basename() not in ("state.json", "config.json"):
            return
        if self.refresh_timer:
            GLib.source_remove(self.refresh_timer)
        self.refresh_timer = GLib.timeout_add(300, self.sync_from_disk)

    def sync_from_disk(self):
        self.refresh_timer = 0
        previous = self.config
        self.config = core.load_config()
        self.syncing_config = True
        try:
            for mode, button in self.mode_buttons.items():
                button.set_active(self.config["mode"] == mode)
            for key, switch in self.switches.items():
                switch.set_active(self.config[key])
            self.update_rotation()
            self.awake_method_combo.set_selected(0 if self.config["awake_method"] == "key" else 1)
            self.mode_row.set_subtitle(f"Auto is light from {self.config['light_from']:02d}:00 "
                                       f"and dark from {self.config['dark_from']:02d}:00")
        finally:
            self.syncing_config = False
        if previous["folder"] != self.config["folder"]:
            self.load_library()
        self.show_current()
        return False

    def show_current(self):
        state = core.load_state()
        path, still = state.get("wallpaper"), state.get("still")
        if path:
            self.title.set_label(os.path.splitext(os.path.basename(path))[0])
            mode = state.get("mode", core.effective_mode())
            self.subtitle.set_label(f"{'Video' if core.is_video(path) else 'Picture'} · {mode} colours")
        else:
            self.title.set_label("Pick a wallpaper")
            self.subtitle.set_label("Your desktop will be recoloured to match it.")
        if still and os.path.exists(still):
            self.pool.submit(self.load_hero, still)
        else:
            self.hero.set_paintable(None)

        child = self.palettes.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self.palettes.remove(child)
            child = nxt
        for y, mode in enumerate(("light", "dark")):
            pal = state.get("palette", {}).get(mode)
            if not pal:
                continue
            self.palettes.attach(Gtk.Label(label=mode.title(), xalign=0, css_classes=["caption", "dim-label"],
                                           width_chars=5), 0, y, 1, 1)
            colours = [pal[k] for k in SWATCHES] + pal["ansi"][1:7]
            for x, colour in enumerate(colours):
                self.palettes.attach(swatch(colour), x + 1, y, 1, 1)

        current = os.path.realpath(path) if path else None
        for p, button in self.thumbs.items():
            (button.add_css_class if os.path.realpath(p) == current else button.remove_css_class)("current")
        return False

    def load_hero(self, still):
        try:
            pb = cover(still, 768, 432)
        except GLib.Error:
            return
        GLib.idle_add(lambda: self.hero.set_paintable(Gdk.Texture.new_for_pixbuf(pb)) and False)

    def load_library(self):
        self.config = core.load_config()
        folder = self.config["folder"]
        self.library_group.set_description("Built-in wallpapers" if folder == core.BUILT_IN
                                           else folder.replace(core.HOME, "~", 1))
        while child := self.grid.get_first_child():
            self.grid.remove(child)
        self.thumbs.clear()
        files = core.wallpapers(folder)
        self.empty.set_visible(not files)
        self.grid.set_visible(bool(files))
        for path in files:
            picture = Gtk.Picture(can_shrink=True, keep_aspect_ratio=True,
                                  width_request=THUMB_W // 2, height_request=THUMB_H // 2)
            overlay = Gtk.Overlay(child=picture)
            if core.is_video(path):
                overlay.add_overlay(Gtk.Label(label="VIDEO", css_classes=["badge"],
                                              halign=Gtk.Align.START, valign=Gtk.Align.END))
            button = Gtk.Button(child=overlay, tooltip_text=os.path.basename(path), css_classes=["thumb", "flat"],
                                halign=Gtk.Align.CENTER)
            button.set_overflow(Gtk.Overflow.HIDDEN)
            button.connect("clicked", lambda _b, p=path: self.use(p))
            self.grid.append(button)
            self.thumbs[path] = button
            self.pool.submit(self.load_thumb, path, picture)
        self.show_current()

    def load_thumb(self, path, picture):
        try:
            pb = thumbnail(path)
        except GLib.Error:
            pb = None
        if pb is not None:
            GLib.idle_add(lambda: picture.set_paintable(Gdk.Texture.new_for_pixbuf(pb)) and False)

    # --- actions -------------------------------------------------------------------------

    def run(self, job, nothing_message=None):
        """Run a change off the main thread so the window stays responsive."""
        if self.busy:
            return
        self.busy = True
        self.spinner.start()

        def work():
            try:
                result, error = job(), None
            except Exception as e:      # shown to the user, not swallowed
                result, error = None, str(e)
            GLib.idle_add(done, result, error)

        def done(result, error):
            self.busy = False
            self.spinner.stop()
            self.show_current()
            if error:
                self.toasts.add_toast(Adw.Toast(title=error))
            elif result is None and nothing_message:
                self.toasts.add_toast(Adw.Toast(title=nothing_message))
            return False

        threading.Thread(target=work, daemon=True).start()

    def use(self, path):
        if path:
            self.run(lambda: core.set_wallpaper(path) or True)

    def save(self, recolour=False, **changes):
        if self.syncing_config:
            return
        self.config = core.save_config(**changes)
        if recolour:
            self.run(lambda: core.apply_theme() or True)

    def on_mode(self, button, mode):
        if button.get_active() and self.config["mode"] != mode:
            self.save(recolour=True, mode=mode)

    def choose_file(self, _button):
        dialog = Gtk.FileChooserNative(title="Choose a wallpaper", transient_for=self, action=Gtk.FileChooserAction.OPEN)
        media = Gtk.FileFilter(name="Pictures and videos")
        for ext in core.IMAGE_EXT + core.VIDEO_EXT:
            media.add_suffix(ext.lstrip("."))
        dialog.add_filter(media)
        dialog.set_current_folder(Gio.File.new_for_path(self.config["folder"]))

        def response(d, r):
            if r == Gtk.ResponseType.ACCEPT:
                self.use(d.get_file().get_path())
            self.dialog = None
        dialog.connect("response", response)
        self.dialog = dialog          # native dialogs must be kept alive while open
        dialog.show()

    def choose_folder(self, _button):
        dialog = Gtk.FileChooserNative(title="Choose your wallpaper folder", transient_for=self,
                                       action=Gtk.FileChooserAction.SELECT_FOLDER)
        if os.path.isdir(self.config["folder"]):
            dialog.set_current_folder(Gio.File.new_for_path(self.config["folder"]))

        def response(d, r):
            if r == Gtk.ResponseType.ACCEPT:
                self.save(folder=d.get_file().get_path())
                self.load_library()
            self.dialog = None
        dialog.connect("response", response)
        self.dialog = dialog
        dialog.show()

    def ask_restore(self, *_):
        dialog = Gtk.MessageDialog(transient_for=self, modal=True, message_type=Gtk.MessageType.QUESTION,
                                   text="Restore your original look?",
                                   secondary_text="Your colours, theme, terminal and lock screen go back to "
                                                  "how they were, and the wallpaper is removed. Your pictures "
                                                  "stay where they are.")
        dialog.add_button("Cancel", Gtk.ResponseType.CANCEL)
        restore = dialog.add_button("Restore", Gtk.ResponseType.ACCEPT)
        restore.add_css_class("destructive-action")

        def response(d, r):
            d.destroy()
            if r == Gtk.ResponseType.ACCEPT:
                self.run(lambda: core.restore() or True)
                self.toasts.add_toast(Adw.Toast(title="Original look restored"))
        dialog.connect("response", response)
        dialog.present()

    def about(self, *_):
        Gtk.AboutDialog(transient_for=self, modal=True, program_name="Wallpaper Studio", logo_icon_name=APP_ID,
                        comments="Change your wallpaper and recolour your desktop to match it.",
                        version="1.0", license_type=Gtk.License.MIT_X11).present()


class App(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.DEFAULT_FLAGS
                         if hasattr(Gio.ApplicationFlags, "DEFAULT_FLAGS") else Gio.ApplicationFlags.FLAGS_NONE)

    def do_startup(self):
        Adw.Application.do_startup(self)
        styles.ensure_user_styles()
        provider = Gtk.CssProvider()
        provider.load_from_path(str(styles.DIRECTORY / "app.css"))
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), provider,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        # GTK reads gtk.css only at start-up; reload it (and the colours it imports) whenever they change,
        # just above GTK's own copy, so this window recolours with the desktop instead of on restart
        self.user_css = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(Gdk.Display.get_default(), self.user_css,
                                                  Gtk.STYLE_PROVIDER_PRIORITY_USER + 1)
        self.custom_css = None
        self.css_timer = 0
        self.css_monitor = Gio.File.new_for_path(core.CONFIG_DIR).monitor_directory(Gio.FileMonitorFlags.NONE, None)
        self.css_monitor.connect("changed", self.on_css_change)
        self.reload_user_css()
        core.start_helper()

    def reload_user_css(self):
        self.css_timer = 0
        gtk_css = os.path.join(core.HOME, ".config", "gtk-4.0", "gtk.css")
        try:
            self.user_css.load_from_data(b"")
            if os.path.exists(gtk_css):
                self.user_css.load_from_path(gtk_css)
            provider = Gtk.CssProvider()
            if os.path.exists(core.APP_CSS):
                provider.load_from_path(core.APP_CSS)
            display = Gdk.Display.get_default()
            Gtk.StyleContext.add_provider_for_display(display, provider, Gtk.STYLE_PROVIDER_PRIORITY_USER + 2)
            if self.custom_css:
                Gtk.StyleContext.remove_provider_for_display(display, self.custom_css)
            self.custom_css = provider
        except GLib.Error as error:
            logging.getLogger(__name__).warning("Cannot reload app CSS: %s", error)
        return False

    def on_css_change(self, _monitor, file, _other, _event):
        if file.get_basename() not in ("theme.css", "app.css"):
            return
        if self.css_timer:
            GLib.source_remove(self.css_timer)
        self.css_timer = GLib.timeout_add(150, self.reload_user_css)

    def do_activate(self):
        (self.get_active_window() or Window(self)).present()


def main():
    # so GNOME matches the window to its launcher (name and icon in the top bar), not "python3"
    GLib.set_prgname(APP_ID)
    GLib.set_application_name("Wallpaper Studio")
    return App().run(None)
