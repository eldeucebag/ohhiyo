#!/usr/bin/env python3
"""
RetiBrowser - A Kivy-based Reticulum NomadNet Micron Browser
Connects via Yggdrasil to community hub and renders Micron markup pages.

Requirements:
    pip install kivy rns

Usage:
    python retibrowser.py
"""

import os
import sys
import time
import threading
import traceback

# ─── Kivy config BEFORE import ───────────────────────────────────────────────
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")

# Enable Android logging
try:
    # On Android, stdout/stderr are automatically redirected to logcat by p4a.
    # We can also use the 'android' module for specific features if needed.
    import android
    from android.runnable import run_on_ui_thread
    def log(msg):
        print(f"[RetiBrowser] {msg}")
        # If we really want to use the native Android log, the correct way in newer p4a
        # is often just print(), but some older versions used android.log().
        # However, print() is the most reliable and standard way.
except ImportError:
    def log(msg):
        print(f"[RetiBrowser] {msg}")

from kivy.app import App
from kivy.clock import Clock, mainthread
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.widget import Widget
from kivy.graphics import Color, Rectangle, RoundedRectangle
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.utils import get_color_from_hex
from kivy.uix.anchorlayout import AnchorLayout

import RNS

# ─── Constants ────────────────────────────────────────────────────────────────
YGGDRASIL_PEER   = "99b91c274bd7c2b926426618a3c2dbbd480cae10eadf9d53aabb873d2bbbbb71"
DEFAULT_NODE     = "f97f412b9ef6d1c2330ca5ee28ee9e31"
DEFAULT_PAGE     = "/page/index.mu"
PAGE_TIMEOUT     = 30          # seconds to wait for a page response
LINK_TIMEOUT     = 15          # seconds to establish a link

# Micron colour palette (3-hex → kivy rgba)
MICRON_COLORS = {
    "f00": (1, 0, 0, 1),      "0f0": (0, 1, 0, 1),
    "00f": (0, 0, 1, 1),      "ff0": (1, 1, 0, 1),
    "0ff": (0, 1, 1, 1),      "f0f": (1, 0, 1, 1),
    "fff": (1, 1, 1, 1),      "000": (0, 0, 0, 1),
    "888": (.53, .53, .53, 1),"aaa": (.67, .67, .67, 1),
    "0a0": (0, .63, 0, 1),    "a00": (.63, 0, 0, 1),
    "00a": (0, 0, .63, 1),    "fa0": (1, .63, 0, 1),
    "0fa": (0, 1, .63, 1),    "f80": (1, .5, 0, 1),
    "5f5": (.33, 1, .33, 1),  "55f": (.33, .33, 1, 1),
    "f55": (1, .33, .33, 1),  "5ff": (.33, 1, 1, 1),
}

BG_COLOR  = (0.05, 0.05, 0.08, 1)
FG_COLOR  = (0.85, 0.90, 0.85, 1)
NAV_COLOR = (0.10, 0.12, 0.16, 1)
BTN_COLOR = (0.15, 0.20, 0.28, 1)
BTN_PRESS = (0.25, 0.35, 0.50, 1)
LNK_COLOR = (0.40, 0.80, 1.00, 1)


# ─── Micron Parser ────────────────────────────────────────────────────────────

def hex3_to_rgba(h):
    """Convert a 3-char hex string to an RGBA 4-tuple (0-1 range)."""
    if h in MICRON_COLORS:
        return MICRON_COLORS[h]
    try:
        r = int(h[0]*2, 16) / 255
        g = int(h[1]*2, 16) / 255
        b = int(h[2]*2, 16) / 255
        return (r, g, b, 1)
    except Exception:
        return FG_COLOR


def parse_micron(text):
    """
    Parse Micron markup and return a list of render elements.

    Each element is a dict with keys:
      type: "text" | "link" | "divider" | "blank"
      For "text":
        segments: list of {"text":str, "bold":bool, "italic":bool,
                           "underline":bool, "fg":rgba, "bg":rgba}
        align: "left"|"center"|"right"
        heading: 0|1|2|3
      For "link":
        label: str, path: str, node: str (may be "")
        fg: rgba
      For "divider": (horizontal rule)
      For "blank": empty line
    """
    elements = []

    # Strip cache-control header (#!c=X on first line)
    lines = text.split("\n")
    if lines and lines[0].strip().startswith("#!"):
        lines = lines[1:]

    cur_fg    = FG_COLOR
    cur_bg    = BG_COLOR
    cur_bold  = False
    cur_ital  = False
    cur_uline = False
    cur_align = "left"

    def reset_fmt():
        nonlocal cur_fg, cur_bg, cur_bold, cur_ital, cur_uline, cur_align
        cur_fg    = FG_COLOR
        cur_bg    = BG_COLOR
        cur_bold  = False
        cur_ital  = False
        cur_uline = False
        cur_align = "left"

    for raw_line in lines:
        line = raw_line.rstrip("\r")

        # ── Section headers ──────────────────────────────────────────────
        if line.startswith(">>>"):
            elements.append({"type":"text","heading":3,"align":"left",
                "segments":[{"text":line[3:].strip(),"bold":True,"italic":False,
                              "underline":False,"fg":(0.7,0.9,1,1),"bg":BG_COLOR}]})
            continue
        if line.startswith(">>"):
            elements.append({"type":"text","heading":2,"align":"left",
                "segments":[{"text":line[2:].strip(),"bold":True,"italic":False,
                              "underline":False,"fg":(0.6,1,0.7,1),"bg":BG_COLOR}]})
            continue
        if line.startswith(">"):
            elements.append({"type":"text","heading":1,"align":"left",
                "segments":[{"text":line[1:].strip(),"bold":True,"italic":False,
                              "underline":False,"fg":(1,0.85,0.3,1),"bg":BG_COLOR}]})
            continue

        # ── Section depth reset ──────────────────────────────────────────
        if line.strip() == "<":
            continue

        # ── Horizontal divider ───────────────────────────────────────────
        if line.strip().startswith("---"):
            elements.append({"type":"divider"})
            continue

        # ── Empty line ───────────────────────────────────────────────────
        if line.strip() == "":
            elements.append({"type":"blank"})
            continue

        # ── Inline markup tokeniser ──────────────────────────────────────
        # We scan character by character for backtick sequences.
        segments = []
        links    = []          # collected link objects from this line
        i = 0
        seg_fg    = cur_fg
        seg_bg    = cur_bg
        seg_bold  = cur_bold
        seg_ital  = cur_ital
        seg_uline = cur_uline
        seg_align = cur_align
        buf = ""

        def flush(b, _bold=False, _ital=False, _uline=False, _fg=FG_COLOR, _bg=BG_COLOR):
            # Values are snapshotted at each call via default-arg trick to avoid
            # the classic Python closure late-binding bug.
            if b:
                segments.append({"text":b,
                                  "bold":   _bold,
                                  "italic": _ital,
                                  "underline": _uline,
                                  "fg":     _fg,
                                  "bg":     _bg})

        while i < len(line):
            ch = line[i]

            if ch != "`":
                buf += ch
                i += 1
                continue

            # Backtick – look ahead for escape type
            nxt = line[i+1] if i+1 < len(line) else ""

            # `` → reset all formatting
            if nxt == "`":
                flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg); buf = ""
                seg_fg = FG_COLOR; seg_bg = BG_COLOR
                seg_bold = seg_ital = seg_uline = False
                i += 2
                continue

            # `! … `! bold
            if nxt == "!":
                flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg); buf = ""
                seg_bold = not seg_bold
                i += 2
                continue

            # `* … `* italic
            if nxt == "*":
                flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg); buf = ""
                seg_ital = not seg_ital
                i += 2
                continue

            # `_ … `_ underline
            if nxt == "_":
                flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg); buf = ""
                seg_uline = not seg_uline
                i += 2
                continue

            # alignment: `c `l `r  followed by text then `a
            if nxt in ("c","l","r") and i+2 < len(line) and line[i+2] != "`":
                flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg); buf = ""
                seg_align = {"c":"center","l":"left","r":"right"}[nxt]
                i += 2
                continue
            if nxt == "a":
                seg_align = "left"
                i += 2
                continue

            # Foreground colour: `Fxxx…`f
            if nxt == "F" and i+4 < len(line):
                flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg); buf = ""
                seg_fg = hex3_to_rgba(line[i+2:i+5])
                i += 5
                continue
            if nxt == "f":
                flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg); buf = ""
                seg_fg = FG_COLOR
                i += 2
                continue

            # Background colour: `Bxxx…`b
            if nxt == "B" and i+4 < len(line):
                flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg); buf = ""
                seg_bg = hex3_to_rgba(line[i+2:i+5])
                i += 5
                continue
            if nxt == "b":
                flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg); buf = ""
                seg_bg = BG_COLOR
                i += 2
                continue

            # Link: `[label`path] OR `[`path]
            if nxt == "[":
                flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg); buf = ""
                # find closing `
                j = line.find("`", i+2)
                if j == -1:
                    buf += ch; i += 1; continue
                label_text = line[i+2:j]
                # find closing ]
                k = line.find("]", j+1)
                if k == -1:
                    buf += ch; i += 1; continue
                path = line[j+1:k]
                # resolve node: path may be nodeaddr:path/to/page
                node_addr = ""
                page_path = path
                if ":" in path and not path.startswith("/"):
                    parts = path.split(":", 1)
                    node_addr = parts[0]
                    page_path = parts[1]
                if not label_text:
                    label_text = page_path
                links.append({
                    "type":"link",
                    "label": label_text,
                    "path":  page_path,
                    "node":  node_addr,
                    "fg":    LNK_COLOR,
                })
                i = k+1
                # skip trailing ` after ]
                if i < len(line) and line[i] == "`":
                    i += 1
                continue

            # Unrecognised escape – emit literally
            buf += ch
            i += 1

        flush(buf, seg_bold, seg_ital, seg_uline, seg_fg, seg_bg)

        if links:
            # Emit any text segments before the first link, then the links
            if segments:
                elements.append({"type":"text","heading":0,
                                  "align":seg_align,"segments":segments})
            for lnk in links:
                elements.append(lnk)
        else:
            if segments:
                elements.append({"type":"text","heading":0,
                                  "align":seg_align,"segments":segments})
            else:
                elements.append({"type":"blank"})

    return elements


# ─── Reticulum Network Layer ──────────────────────────────────────────────────

class ReticulumClient:
    """Manages the RNS instance and page fetching."""

    def __init__(self):
        self.rns       = None
        self.identity  = None
        self._active_link = None
        self._lock     = threading.Lock()

    def start(self, yggdrasil_peer=YGGDRASIL_PEER):
        """Initialise Reticulum with a Yggdrasil interface to the community hub."""
        config = self._build_config(yggdrasil_peer)
        
        # Determine a writable path for configuration.
        # On Android, home (~) might be /data or / which is read-only for apps.
        # Kivy's App.user_data_dir is the standard way to get a writable path.
        try:
            from kivy.app import App as KivyApp
            app_inst = KivyApp.get_running_app()
            if app_inst and app_inst.user_data_dir:
                config_root = app_inst.user_data_dir
            else:
                config_root = os.path.expanduser("~")
        except Exception:
            config_root = os.path.expanduser("~")

        config_path = os.path.join(config_root, ".reticulum_retibrowser")
        os.makedirs(config_path, exist_ok=True)
        with open(os.path.join(config_path, "config"), "w") as f:
            f.write(config)

        self.rns = RNS.Reticulum(configdir=config_path, loglevel=RNS.LOG_WARNING)
        self.identity = RNS.Identity()
        RNS.log("RetiBrowser: Reticulum started", RNS.LOG_NOTICE)

    def _build_config(self, ygg_peer):
        return f"""[reticulum]
  enable_transport = No
  share_instance   = No
  rpc_listener     = No

[interfaces]

  [[RetiBrowser Yggdrasil Hub]]
    type        = TCPClientInterface
    enabled     = yes
    target_host = {ygg_peer}
    target_port = 4965
"""

    def fetch_page(self, node_hex, page_path, on_done, on_error, on_progress=None):
        """
        Fetch a NomadNet page from node_hex at page_path in a background thread.
        on_done(content_str) called on success.
        on_error(msg)        called on failure.
        on_progress(pct)     optional progress 0-100.
        """
        t = threading.Thread(
            target=self._fetch_thread,
            args=(node_hex, page_path, on_done, on_error, on_progress),
            daemon=True
        )
        t.start()

    def _fetch_thread(self, node_hex, page_path, on_done, on_error, on_progress):
        try:
            dest_hash = bytes.fromhex(node_hex)

            # Request a path from the destination - NomadNet uses
            # "nomadnetwork.node" as the app/aspect.
            if not RNS.Transport.has_path(dest_hash):
                RNS.Transport.request_path(dest_hash)
                deadline = time.time() + LINK_TIMEOUT
                while not RNS.Transport.has_path(dest_hash):
                    if time.time() > deadline:
                        on_error("Path not found – node may be offline or unreachable")
                        return
                    time.sleep(0.25)

            identity = RNS.Identity.recall(dest_hash)
            if not identity:
                on_error("Could not recall identity for this node")
                return

            destination = RNS.Destination(
                identity,
                RNS.Destination.OUT,
                RNS.Destination.SINGLE,
                "nomadnetwork",
                "node"
            )

            link_ready = threading.Event()
            link_error = threading.Event()
            self._active_link = RNS.Link(destination)

            def link_established(link):
                link_ready.set()

            def link_closed(link):
                # Only treat as an error if the link never became ready
                if not link_ready.is_set():
                    link_error.set()

            self._active_link.set_link_established_callback(link_established)
            self._active_link.set_link_closed_callback(link_closed)

            if not link_ready.wait(timeout=LINK_TIMEOUT):
                on_error("Link establishment timed out")
                return

            # Send a page request via RNS link.request()
            # NomadNet expects the path as bytes in the request data.
            request_done  = threading.Event()
            request_error = threading.Event()
            result_holder = [None]

            def response_received(receipt):
                if receipt.status == RNS.RequestReceipt.FAILED:
                    request_error.set()
                    return
                result_holder[0] = receipt.response
                request_done.set()

            def progress_updated(receipt):
                if on_progress:
                    pct = int(receipt.progress * 100)
                    on_progress(pct)

            self._active_link.request(
                page_path,
                data            = None,
                response_callback    = response_received,
                failed_callback      = lambda r: request_error.set(),
                progress_callback    = progress_updated,
                timeout         = PAGE_TIMEOUT
            )

            deadline = time.time() + PAGE_TIMEOUT
            while not request_done.is_set() and not request_error.is_set():
                if time.time() > deadline:
                    on_error("Page request timed out")
                    return
                time.sleep(0.1)

            if request_error.is_set():
                on_error("Page request failed")
                return

            raw = result_holder[0]
            if raw is None:
                on_error("Empty response from node")
                return

            if isinstance(raw, bytes):
                content = raw.decode("utf-8", errors="replace")
            else:
                content = str(raw)

            on_done(content)

        except Exception as e:
            on_error(f"Error: {e}")
        finally:
            try:
                if self._active_link:
                    self._active_link.teardown()
            except Exception:
                pass


# ─── UI Widgets ───────────────────────────────────────────────────────────────

class IconButton(Button):
    """A flat icon-style button."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal  = ""
        self.background_down    = ""
        self.background_color   = BTN_COLOR
        self.color              = FG_COLOR
        self.font_size          = sp(16)
        self.size_hint_x        = None
        self.width              = dp(48)
        self.bold               = True


class AddressBar(BoxLayout):
    def __init__(self, on_navigate, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=dp(48), spacing=dp(4), padding=[dp(4),dp(4)], **kwargs)
        self.on_navigate = on_navigate

        with self.canvas.before:
            Color(*NAV_COLOR)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._update_bg, size=self._update_bg)

        self.back_btn    = IconButton(text="◀", width=dp(44))
        self.fwd_btn     = IconButton(text="▶", width=dp(44))
        self.refresh_btn = IconButton(text="↻", width=dp(44))
        self.go_btn      = IconButton(text="→", width=dp(44))
        self.address     = TextInput(
            text="", multiline=False, font_size=sp(14),
            background_color=(0.12,0.15,0.20,1),
            foreground_color=FG_COLOR,
            cursor_color=LNK_COLOR,
            padding=[dp(8), dp(10)],
        )

        for w in (self.back_btn, self.fwd_btn, self.refresh_btn, self.address, self.go_btn):
            self.add_widget(w)

        self.address.bind(on_text_validate=self._go)
        self.go_btn.bind(on_press=self._go)

    def _update_bg(self, *_):
        self._bg.pos  = self.pos
        self._bg.size = self.size

    def _go(self, instance):
        self.on_navigate(self.address.text.strip())

    def set_url(self, url):
        self.address.text = url


class StatusBar(Label):
    def __init__(self, **kwargs):
        super().__init__(size_hint_y=None, height=dp(24),
                         font_size=sp(11), halign="left",
                         color=(0.6, 0.6, 0.6, 1),
                         text_size=(Window.width, None),
                         **kwargs)
        with self.canvas.before:
            Color(0.08, 0.08, 0.10, 1)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)
        self.bind(size=lambda *_: setattr(self, 'text_size', (self.width, None)))

    def _upd(self, *_):
        self._bg.pos  = self.pos
        self._bg.size = self.size


class MicronLabel(Label):
    """A single line of Micron-rendered text."""
    pass


class LinkButton(Button):
    """A tappable link within a Micron page."""
    def __init__(self, label, path, node, on_tap, **kwargs):
        super().__init__(
            text=f"  ▸ {label}",
            background_normal="", background_down="",
            background_color=(0,0,0,0),
            color=LNK_COLOR,
            halign="left", valign="middle",
            size_hint_y=None, height=dp(34),
            font_size=sp(14),
            **kwargs
        )
        self.path     = path
        self.node     = node
        self.on_tap   = on_tap
        self.text_size = (None, None)
        self.bind(size=lambda *_: setattr(self, 'text_size', (self.width, None)))
        self.bind(on_press=self._pressed)

    def _pressed(self, *_):
        self.background_color = BTN_PRESS
        Clock.schedule_once(lambda *_: setattr(self, 'background_color', (0,0,0,0)), 0.15)
        self.on_tap(self.node, self.path)


class PageView(ScrollView):
    """Scrollable page content area rendering parsed Micron elements."""

    def __init__(self, on_link_tap, **kwargs):
        super().__init__(
            do_scroll_x=False,
            bar_width=dp(4),
            bar_color=LNK_COLOR,
            bar_inactive_color=(0.3,0.3,0.3,0.5),
            **kwargs
        )
        self.on_link_tap = on_link_tap
        self.container   = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(2),
            padding=[dp(12), dp(8)],
        )
        self.container.bind(minimum_height=self.container.setter("height"))
        self.add_widget(self.container)
        self._set_bg()

    def _set_bg(self):
        with self.canvas.before:
            Color(*BG_COLOR)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._bg.pos  = self.pos
        self._bg.size = self.size

    @mainthread
    def show_elements(self, elements):
        self.container.clear_widgets()
        self.scroll_y = 1

        for el in elements:
            etype = el.get("type")

            if etype == "blank":
                self.container.add_widget(Widget(size_hint_y=None, height=dp(6)))

            elif etype == "divider":
                w = Widget(size_hint_y=None, height=dp(1))
                with w.canvas.before:
                    _clr  = Color(0.3, 0.4, 0.5, 1)
                    _rect = Rectangle(pos=w.pos, size=w.size)
                def _upd_divider(inst, _r=_rect):
                    _r.pos  = inst.pos
                    _r.size = inst.size
                w.bind(pos=_upd_divider, size=_upd_divider)
                self.container.add_widget(w)

            elif etype == "link":
                btn = LinkButton(
                    label=el["label"],
                    path=el["path"],
                    node=el.get("node",""),
                    on_tap=self.on_link_tap,
                )
                self.container.add_widget(btn)

            elif etype == "text":
                heading  = el.get("heading", 0)
                align    = el.get("align", "left")
                segments = el.get("segments", [])

                # Build markup string for Kivy
                markup_parts = []
                for seg in segments:
                    txt = seg["text"].replace("&","&amp;").replace("[","[[").replace("]","]]")
                    r,g,b,a = seg["fg"]
                    hex_color = "#{:02x}{:02x}{:02x}".format(
                        int(r*255), int(g*255), int(b*255))
                    part = f"[color={hex_color}]"
                    if seg.get("bold"):
                        part += "[b]"
                    if seg.get("italic"):
                        part += "[i]"
                    if seg.get("underline"):
                        part += "[u]"
                    part += txt
                    if seg.get("underline"):
                        part += "[/u]"
                    if seg.get("italic"):
                        part += "[/i]"
                    if seg.get("bold"):
                        part += "[/b]"
                    part += "[/color]"
                    markup_parts.append(part)

                markup = "".join(markup_parts)

                fs = {0: sp(14), 1: sp(20), 2: sp(17), 3: sp(15)}[heading]
                lbl = Label(
                    text=markup,
                    markup=True,
                    font_size=fs,
                    halign=align,
                    valign="top",
                    size_hint_y=None,
                    color=FG_COLOR,
                )
                # Allow text to wrap
                lbl.bind(
                    width=lambda inst, w: setattr(inst, 'text_size', (w, None)),
                    texture_size=lambda inst, ts: setattr(inst, 'height', ts[1] + dp(2))
                )
                lbl.text_size = (self.width - dp(24), None)
                self.container.add_widget(lbl)

    @mainthread
    def show_status(self, msg, color=FG_COLOR):
        self.container.clear_widgets()
        lbl = Label(
            text=msg,
            markup=True,
            color=color,
            halign="center",
            valign="middle",
            size_hint=(1, 1),
        )
        lbl.bind(size=lambda inst,_: setattr(inst,'text_size',inst.size))
        self.container.add_widget(lbl)


# ─── Main App ─────────────────────────────────────────────────────────────────

class RetiBrowserApp(App):
    title = "RetiBrowser – Reticulum Micron Browser"

    def build(self):
        log("App build() starting...")
        try:
            Window.clearcolor = BG_COLOR

            # History
            self._history     = []
            self._hist_pos    = -1
            self._current_node = DEFAULT_NODE

            # Reticulum client
            log("Creating ReticulumClient...")
            self._rns = ReticulumClient()

            # Root layout
            log("Creating root layout...")
            root = BoxLayout(orientation="vertical")

            # Address / nav bar
            log("Creating address bar...")
            self._addrbar = AddressBar(on_navigate=self._navigate_url)
            self._addrbar.back_btn.bind(on_press=self._go_back)
            self._addrbar.fwd_btn.bind(on_press=self._go_forward)
            self._addrbar.refresh_btn.bind(on_press=self._refresh)

            # Page view
            log("Creating page view...")
            self._pageview = PageView(on_link_tap=self._on_link_tap)

            # Status bar
            log("Creating status bar...")
            self._statusbar = StatusBar(text="  Initialising Reticulum…")

            log("Adding widgets to root...")
            root.add_widget(self._addrbar)
            root.add_widget(self._pageview)
            root.add_widget(self._statusbar)

            # Start Reticulum in background, then load default page
            log("Starting Reticulum init thread...")
            threading.Thread(target=self._init_rns, daemon=True).start()

            log("App build() complete, returning root")
            return root
        except Exception as e:
            log(f"Build error: {e}")
            log(traceback.format_exc())
            raise

    # ── Reticulum init ────────────────────────────────────────────────────────

    def _init_rns(self):
        try:
            log("Starting Reticulum initialization...")
            self._set_status("Connecting to Reticulum via Yggdrasil…")
            self._rns.start(YGGDRASIL_PEER)
            log("Reticulum started successfully")
            self._set_status("Connected – requesting default page…")
            time.sleep(2)   # allow interface to settle
            log("Loading default page...")
            self._load_page(DEFAULT_NODE, DEFAULT_PAGE, push_history=True)
        except Exception as e:
            log(f"Init error: {e}")
            log(traceback.format_exc())
            self._set_status(f"Init error: {e}")
            self._pageview.show_status(
                f"[color=#ff5555]Failed to start Reticulum:\n{e}[/color]\n\n"
                f"[color=#888888]{traceback.format_exc()}[/color]",
                color=(1,0.33,0.33,1)
            )

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate_url(self, url):
        """Parse a URL typed in the address bar. Formats:
           nodeaddr:/page/path.mu
           /page/path.mu            (uses current node)
           nodeaddr                 (loads index page)
        """
        url = url.strip()
        if ":" in url and not url.startswith("/"):
            parts = url.split(":", 1)
            node  = parts[0].strip()
            path  = parts[1].strip()
        elif url.startswith("/"):
            node = self._current_node
            path = url
        else:
            node = url
            path = DEFAULT_PAGE
        self._load_page(node, path, push_history=True)

    def _on_link_tap(self, node_hex, page_path):
        if not node_hex:
            node_hex = self._current_node
        self._load_page(node_hex, page_path, push_history=True)

    def _go_back(self, *_):
        if self._hist_pos > 0:
            self._hist_pos -= 1
            node, path = self._history[self._hist_pos]
            self._load_page(node, path, push_history=False)

    def _go_forward(self, *_):
        if self._hist_pos < len(self._history) - 1:
            self._hist_pos += 1
            node, path = self._history[self._hist_pos]
            self._load_page(node, path, push_history=False)

    def _refresh(self, *_):
        if self._history:
            node, path = self._history[self._hist_pos]
            self._load_page(node, path, push_history=False)

    # ── Page loading ──────────────────────────────────────────────────────────

    def _load_page(self, node_hex, page_path, push_history=True):
        # Normalise
        node_hex  = node_hex.strip().lower()
        page_path = page_path.strip()
        if not page_path.startswith("/"):
            page_path = "/page/" + page_path

        self._current_node = node_hex

        # Update address bar
        url = f"{node_hex}:{page_path}"
        Clock.schedule_once(lambda *_: self._addrbar.set_url(url), 0)

        # Update history
        if push_history:
            # Trim forward history
            self._history = self._history[:self._hist_pos+1]
            self._history.append((node_hex, page_path))
            self._hist_pos = len(self._history) - 1

        self._update_nav_buttons()
        self._set_status(f"Fetching {page_path} from {node_hex[:8]}…")
        self._pageview.show_status("[color=#aaaaaa]Loading page…[/color]")

        self._rns.fetch_page(
            node_hex, page_path,
            on_done     = self._on_page_done,
            on_error    = self._on_page_error,
            on_progress = self._on_progress,
        )

    @mainthread
    def _update_nav_buttons(self):
        self._addrbar.back_btn.background_color = \
            BTN_COLOR if self._hist_pos > 0 else (0.08,0.10,0.14,1)
        self._addrbar.fwd_btn.background_color = \
            BTN_COLOR if self._hist_pos < len(self._history)-1 else (0.08,0.10,0.14,1)

    def _on_progress(self, pct):
        self._set_status(f"Downloading… {pct}%")

    def _on_page_done(self, content):
        self._set_status("Page loaded")
        elements = parse_micron(content)
        self._pageview.show_elements(elements)

    def _on_page_error(self, msg):
        self._set_status(f"Error: {msg}")
        self._pageview.show_status(
            f"[color=#ff5555]{msg}[/color]\n\n"
            "[color=#888888]Check your network connection and node address.[/color]",
            color=(1,0.33,0.33,1)
        )

    # ── Helpers ───────────────────────────────────────────────────────────────

    @mainthread
    def _set_status(self, msg):
        self._statusbar.text = f"  {msg}"

    def on_stop(self):
        """Clean up Reticulum on app exit to avoid socket leaks."""
        try:
            if self._rns._active_link:
                self._rns._active_link.teardown()
        except Exception:
            pass


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    RetiBrowserApp().run()
