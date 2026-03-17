#!/usr/bin/env python3
"""
RetiBrowser - A Kivy-based Reticulum NomadNet Micron Browser
Connects via Yggdrasil to community hub and renders Micron markup pages.


Requirements:
    pip install kivy rns

Usage:
    python main.py
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
    import android
    from android.runnable import run_on_ui_thread
    def log(msg):
        print(f"[RetiBrowser] {msg}")
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
from kivy.uix.gridlayout import GridLayout
from kivy.properties import NumericProperty, ObjectProperty
from kivy.animation import Animation

import RNS
import RNS.vendor.umsgpack as umsgpack

# ─── Constants ────────────────────────────────────────────────────────────────
# Noderage Community Hub - public Reticulum transport relay
# Both server and clients connect here, avoiding NAT/firewall issues
NODERAGE_HOST    = "rns.noderage.org"
NODERAGE_PORT    = 4242
# Default node - your page node server's destination hash
DEFAULT_NODE     = "f97f412b9ef6d1c2330ca5ee28ee9e31"
DEFAULT_PAGE     = "/page/index.mu"
PAGE_TIMEOUT     = 30                # seconds to wait for a page response
LINK_TIMEOUT     = 15                # seconds to establish a link

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


def hex2_to_rgba(h):
    """Convert a 2-char hex string (grayscale) to an RGBA 4-tuple (0-1 range)."""
    try:
        v = int(h, 16) / 255
        return (v, v, v, 1)
    except Exception:
        return FG_COLOR


def parse_micron(text):
    """
    Parse Micron markup and return a list of render elements.

    Full Micron specification support:
    - Headings: >H1, >>H2, >>>H3, < (reset section depth)
    - Bold: `!text`!
    - Italic: `*text`*
    - Underline: `_text`_
    - Colors: `Fxxx...`f (foreground), `Bxxx...`b (background), `gXX (grayscale)
    - Alignment: `c (center), `l (left), `r (right), `a (reset alignment)
    - Links: `[label`path] or `[`path]
    - Dividers: --- or `-`
    - Comments: # (except #! which is for cache headers)
    - Literal mode: `=...`= (displays text without formatting)
    - Escape: \\` for literal backtick
    - Reset: `` (reset all formatting)

    Each element is a dict with keys:
      type: "text" | "link" | "divider" | "blank" | "literal"
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
      For "literal": raw text content
    """
    elements = []

    # State variables
    cur_fg    = FG_COLOR
    cur_bg    = BG_COLOR
    cur_bold  = False
    cur_ital  = False
    cur_uline = False
    cur_align = "left"
    in_literal = False
    literal_buffer = []

    def reset_fmt():
        nonlocal cur_fg, cur_bg, cur_bold, cur_ital, cur_uline, cur_align
        cur_fg    = FG_COLOR
        cur_bg    = BG_COLOR
        cur_bold  = False
        cur_ital  = False
        cur_uline  = False
        cur_align = "left"

    def process_inline_line(line):
        """Process a single line for inline formatting and return elements."""
        nonlocal cur_fg, cur_bg, cur_bold, cur_ital, cur_uline, cur_align
        
        # Section headers - also handle trailing < for section reset
        if line.startswith(">>>"):
            text = line[3:].rstrip().rstrip("<").strip()
            return [{"type":"text","heading":3,"align":"left",
                "segments":[{"text":text,"bold":True,"italic":False,
                              "underline":False,"fg":(0.7,0.9,1,1),"bg":BG_COLOR}]}]
        if line.startswith(">>"):
            text = line[2:].rstrip().rstrip("<").strip()
            return [{"type":"text","heading":2,"align":"left",
                "segments":[{"text":text,"bold":True,"italic":False,
                              "underline":False,"fg":(0.6,1,0.7,1),"bg":BG_COLOR}]}]
        if line.startswith(">"):
            text = line[1:].rstrip().rstrip("<").strip()
            return [{"type":"text","heading":1,"align":"left",
                "segments":[{"text":text,"bold":True,"italic":False,
                              "underline":False,"fg":(1,0.85,0.3,1),"bg":BG_COLOR}]}]
        
        # Section depth reset
        if line.strip() == "<":
            return []
        
        # Horizontal divider
        stripped = line.strip()
        if stripped.startswith("---") or stripped == "`-`":
            return [{"type":"divider"}]
        
        # Empty line
        if stripped == "":
            return [{"type":"blank"}]
        
        # Comment lines
        if line.startswith("#") and not line.startswith("#!"):
            return []
        
        # Inline markup processing
        segments = []
        links = []
        i = 0
        seg_fg = cur_fg
        seg_bg = cur_bg
        seg_bold = cur_bold
        seg_ital = cur_ital
        seg_uline = cur_uline
        seg_align = cur_align
        buf = ""

        def flush(b, _bold=None, _ital=None, _uline=None, _fg=None, _bg=None):
            if _bold is None: _bold = seg_bold
            if _ital is None: _ital = seg_ital
            if _uline is None: _uline = seg_uline
            if _fg is None: _fg = seg_fg
            if _bg is None: _bg = seg_bg
            if b:
                segments.append({"text":b, "bold":_bold, "italic":_ital,
                                  "underline":_uline, "fg":_fg, "bg":_bg})

        while i < len(line):
            ch = line[i]

            # Escape character
            if ch == '\\' and i + 1 < len(line):
                buf += line[i + 1]
                i += 2
                continue

            if ch != "`":
                buf += ch
                i += 1
                continue

            nxt = line[i+1] if i+1 < len(line) else ""

            # `` → reset all formatting
            if nxt == "`":
                flush(buf); buf = ""
                reset_fmt()
                seg_fg, seg_bg = cur_fg, cur_bg
                seg_bold, seg_ital, seg_uline = cur_bold, cur_ital, cur_uline
                i += 2
                continue

            # `! … `! bold toggle
            if nxt == "!":
                flush(buf); buf = ""
                seg_bold = not seg_bold
                i += 2
                continue

            # `* … `* italic toggle
            if nxt == "*":
                flush(buf); buf = ""
                seg_ital = not seg_ital
                i += 2
                continue

            # `_ … `_ underline toggle
            if nxt == "_":
                flush(buf); buf = ""
                seg_uline = not seg_uline
                i += 2
                continue

            # Alignment
            if nxt in ("c","l","r") and i+2 < len(line) and line[i+2] != "`":
                flush(buf); buf = ""
                seg_align = {"c":"center","l":"left","r":"right"}[nxt]
                i += 2
                continue
            if nxt == "a":
                seg_align = "left"
                i += 2
                continue

            # Foreground colour
            if nxt == "F" and i+4 < len(line):
                flush(buf); buf = ""
                seg_fg = hex3_to_rgba(line[i+2:i+5])
                i += 5
                continue
            if nxt == "f":
                flush(buf); buf = ""
                seg_fg = FG_COLOR
                i += 2
                continue

            # Background colour
            if nxt == "B" and i+4 < len(line):
                flush(buf); buf = ""
                seg_bg = hex3_to_rgba(line[i+2:i+5])
                i += 5
                continue
            if nxt == "b":
                flush(buf); buf = ""
                seg_bg = BG_COLOR
                i += 2
                continue

            # Grayscale
            if nxt == "g" and i+3 < len(line):
                flush(buf); buf = ""
                seg_fg = hex2_to_rgba(line[i+2:i+4])
                i += 4
                continue

            # Link
            if nxt == "[":
                flush(buf); buf = ""
                j = line.find("`", i+2)
                if j == -1:
                    buf += ch; i += 1; continue
                label_text = line[i+2:j]
                k = line.find("]", j+1)
                if k == -1:
                    buf += ch; i += 1; continue
                path = line[j+1:k]
                node_addr = ""
                page_path = path
                if ":" in path and not path.startswith("/"):
                    parts = path.split(":", 1)
                    node_addr = parts[0]
                    page_path = parts[1]
                if not label_text:
                    label_text = page_path
                links.append({
                    "type":"link", "label": label_text, "path": page_path,
                    "node": node_addr, "fg": LNK_COLOR,
                })
                i = k+1
                if i < len(line) and line[i] == "`":
                    i += 1
                continue

            buf += ch
            i += 1

        flush(buf)

        if links:
            result = []
            if segments:
                result.append({"type":"text","heading":0,"align":seg_align,"segments":segments})
            result.extend(links)
            return result
        elif segments:
            return [{"type":"text","heading":0,"align":seg_align,"segments":segments}]
        else:
            return [{"type":"blank"}]

    # Strip cache-control header
    lines = text.split("\n")
    if lines and lines[0].strip().startswith("#!"):
        lines = lines[1:]

    for raw_line in lines:
        line = raw_line.rstrip("\r")

        # Literal mode handling
        if in_literal:
            if "`=" in line:
                idx = line.index("`=")
                literal_buffer.append(line[:idx])
                elements.append({
                    "type": "literal",
                    "content": "\n".join(literal_buffer)
                })
                literal_buffer = []
                in_literal = False
                # Process rest of line after literal end
                remainder = line[idx+2:]
                if remainder:
                    elements.extend(process_inline_line(remainder))
            else:
                literal_buffer.append(line)
                continue
        elif "`=" in line:
            idx = line.index("`=")
            before = line[:idx]
            after = line[idx+2:]

            if "`=" in after:
                # Literal starts and ends on same line
                end_idx = after.index("`=")
                literal_content = after[:end_idx]
                remainder = after[end_idx+2:]

                if before:
                    elements.extend(process_inline_line(before))
                elements.append({"type": "literal", "content": literal_content})
                if remainder:
                    elements.extend(process_inline_line(remainder))
                continue
            else:
                # Start multiline literal
                if before:
                    elements.extend(process_inline_line(before))
                in_literal = True
                literal_buffer = [after]
                continue
        else:
            elements.extend(process_inline_line(line))

    # Handle unclosed literal mode
    if in_literal and literal_buffer:
        elements.append({
            "type": "literal",
            "content": "\n".join(literal_buffer)
        })

    return elements


# ─── Reticulum Network Layer ──────────────────────────────────────────────────

class AnnounceHandler:
    """Handler for RNS announce messages."""
    
    def __init__(self, on_announce_callback=None):
        self.on_announce_callback = on_announce_callback
        self._announced_nodes = {}
        # None = accept all — "nomadnetwork" does NOT match "nomadnetwork.page"
        self.aspect_filter = None
    
    def received_announce(self, destination_hash, announced_identity, app_data, announce_packet_hash=None, is_path_response=False):
        """Called when an announce is received."""
        try:
            if announced_identity:
                # destination_hash matches DEFAULT_NODE; announced_identity.hash does not
                node_hash = RNS.hexrep(destination_hash, delimit=False)
                try:
                    info = umsgpack.unpackb(app_data) if app_data else {}
                    self._announced_nodes[node_hash] = {
                        "hash": node_hash,
                        "name": info.get("name", "Unknown Node"),
                        "timestamp": info.get("timestamp", time.time()),
                        "capabilities": info.get("capabilities", []),
                        "type": info.get("type", "unknown"),
                    }
                    RNS.log(f"RetiBrowser: Received announce from {node_hash[:8]}...", RNS.LOG_NOTICE)
                    
                    # Callback to update UI
                    if self.on_announce_callback:
                        Clock.schedule_once(
                            lambda dt, nh=node_hash: self.on_announce_callback(self._announced_nodes[nh]),
                            0
                        )
                except Exception as e:
                    RNS.log(f"RetiBrowser: Error parsing announce: {e}", RNS.LOG_ERROR)
        except Exception as e:
            RNS.log(f"RetiBrowser: Error in announce handler: {e}", RNS.LOG_ERROR)
    
    def get_announced_nodes(self):
        """Return list of nodes we've heard announces from."""
        return list(self._announced_nodes.values())


class ReticulumClient:
    """Manages the RNS instance and page fetching."""

    def __init__(self, on_announce_callback=None):
        self.rns          = None
        self.identity     = None
        self._active_link = None
        self._lock        = threading.Lock()
        self.on_announce_callback = on_announce_callback
        self.announce_handler = AnnounceHandler(on_announce_callback)

    def start(self, hub_host=NODERAGE_HOST, hub_port=NODERAGE_PORT):
        """Initialise Reticulum with a TCPClientInterface to Noderage hub."""
        config = self._build_config(hub_host, hub_port)

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

        self.rns = RNS.Reticulum(configdir=config_path, loglevel=RNS.LOG_DEBUG)
        self.identity = RNS.Identity()

        # Register announce handler immediately so no announces are missed
        RNS.Transport.register_announce_handler(self.announce_handler)

        RNS.log("RetiBrowser: Reticulum started", RNS.LOG_NOTICE)

    def _send_announce(self):
        """Browsers do not announce — only servers do. No-op."""
        pass

    def get_announced_nodes(self):
        """Return list of nodes we've heard announces from."""
        return self.announce_handler.get_announced_nodes()

    def _build_config(self, hub_host, hub_port):
        return f"""[reticulum]
  enable_transport = Yes
  share_instance   = No
  rpc_listener     = No

[interfaces]

  [[Noderage Community Hub]]
    type        = TCPClientInterface
    enabled     = yes
    target_host = {hub_host}
    target_port = {hub_port}
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
        """
        Fetch a page using a pure callback chain — no sleep(), no Event.wait(),
        no polling loops.  Every step hands off to the next via RNS callbacks
        so the thread exits immediately after scheduling work and never blocks.

        Flow:
          _fetch_thread → _step_path → _step_identity → _step_open_link
              → _step_send_request → (response_received | request_failed)
        Each step is a nested function that closes over the shared state and
        calls the next step or on_error/on_done as appropriate.
        """
        def status(msg):
            log(f"[fetch] {msg}")
            if on_progress:
                on_progress(msg)

        def teardown():
            try:
                with self._lock:
                    if self._active_link:
                        self._active_link.teardown()
                        self._active_link = None
            except Exception:
                pass

        def fail(msg):
            teardown()
            on_error(msg)

        try:
            dest_hash = bytes.fromhex(node_hex)
            status(f"dest_hash={node_hex[:8]}… path={page_path}")

            # ── Step 1: log interface state (instant, no blocking) ────────────
            interfaces = RNS.Transport.interfaces if hasattr(RNS.Transport, "interfaces") else []
            status(f"RNS interfaces: {len(interfaces)} active")
            for iface in interfaces:
                status(f"  iface: {iface.name} online={getattr(iface, 'online', '?')}")

            # ── Step 2→3: path + identity ─────────────────────────────────────
            # path and identity arrive together in the announce packet so we
            # only need to check once.  If already known, proceed immediately.
            # If not, register a path response callback and return — RNS will
            # call us back when the path arrives (no polling or sleep needed).

            def _step_identity(dest_hash):
                """Called once path is confirmed to exist."""
                identity = RNS.Identity.recall(dest_hash)
                if not identity:
                    fail(
                        f"[FAIL] Identity not in announce table after path resolved.\n"
                        f"  Node: {node_hex}\n"
                        f"  Is pagenode announcing? Check server log for "
                        f"'Sent announce' lines."
                    )
                    return
                status(f"Identity recalled: {RNS.hexrep(identity.hash, delimit=False)[:8]}…")
                _step_open_link(identity)

            def _step_open_link(identity):
                """Open an encrypted RNS Link to the destination."""
                destination = RNS.Destination(
                    identity,
                    RNS.Destination.OUT,
                    RNS.Destination.SINGLE,
                    "nomadnetwork",
                    "page",
                )
                status(f"Opening link to {RNS.hexrep(destination.hash, delimit=False)[:8]}…")

                # Timeout: schedule a Clock callback that fires if link never opens
                timeout_trigger = [None]

                def _on_link_established(link):
                    if timeout_trigger[0]:
                        timeout_trigger[0].cancel()
                        timeout_trigger[0] = None
                    status("Link established!")
                    _step_send_request(link)

                def _on_link_closed(link):
                    if timeout_trigger[0]:
                        timeout_trigger[0].cancel()
                        timeout_trigger[0] = None
                    # Only an error if we never got to send a request
                    status("Link closed")

                def _on_link_timeout(dt):
                    timeout_trigger[0] = None
                    fail(
                        f"[FAIL] Link timed out after {LINK_TIMEOUT}s\n"
                        f"  Identity recalled but encrypted link could not open.\n"
                        f"  Is the pagenode destination still running?"
                    )

                with self._lock:
                    self._active_link = RNS.Link(destination)

                self._active_link.set_link_established_callback(_on_link_established)
                self._active_link.set_link_closed_callback(_on_link_closed)

                # Schedule timeout via Kivy Clock — fires on main thread, no blocking
                timeout_trigger[0] = Clock.schedule_once(_on_link_timeout, LINK_TIMEOUT)
                status(f"Waiting for link…")

            def _step_send_request(link):
                """Send the page request over the established link."""
                status(f"Sending request: {page_path}")

                def response_received(receipt):
                    status(f"Response received: status={receipt.status}")
                    if receipt.status == RNS.RequestReceipt.FAILED:
                        fail(
                            f"[FAIL] Request failed\n"
                            f"  Path: {page_path}\n"
                            f"  Server returned an error response."
                        )
                        return
                    if receipt.response is not None:
                        raw = receipt.response
                        status(f"Response size: {len(raw) if isinstance(raw, (bytes,str)) else '?'} bytes")
                        if isinstance(raw, bytes):
                            page_content = raw.decode("utf-8", errors="replace")
                        else:
                            page_content = str(raw)
                        status("Page decoded OK — rendering…")
                        teardown()
                        on_done(page_content)

                def progress_updated(receipt):
                    pct = int(receipt.progress * 100)
                    status(f"Downloading… {pct}%")

                def request_failed(receipt):
                    status(f"Request failed callback: status={receipt.status}")
                    fail(
                        f"[FAIL] Request failed\n"
                        f"  Path: {page_path}\n"
                        f"  The server returned an error."
                    )

                link.request(
                    page_path,
                    data              = None,
                    response_callback = response_received,
                    failed_callback   = request_failed,
                    progress_callback = progress_updated,
                    timeout           = PAGE_TIMEOUT,
                )
                # link.request() registers callbacks and returns immediately.
                # RNS fires response_received or request_failed when done.

            # ── Kick off the chain ────────────────────────────────────────────
            if RNS.Transport.has_path(dest_hash):
                status("Path already in table")
                _step_identity(dest_hash)
            else:
                status("No path cached — requesting…")
                RNS.Transport.request_path(dest_hash)

                # Register a path response callback so RNS wakes us when
                # the path arrives — no polling loop, no sleep.
                def _on_path_response(path_hash):
                    if path_hash == dest_hash:
                        status("Path resolved via callback")
                        _step_identity(dest_hash)

                # Schedule a timeout that fires if path never arrives
                path_timeout_event = [None]

                def _on_path_timeout(dt):
                    path_timeout_event[0] = None
                    fail(
                        f"[FAIL] Path not found after {LINK_TIMEOUT}s\n"
                        f"  Node: {node_hex}\n"
                        f"  Hub: {NODERAGE_HOST}:{NODERAGE_PORT}\n"
                        f"  Interfaces up: {len(interfaces)}\n"
                        f"  Is your server connected to Noderage? "
                        f"Is your device connected to the internet?"
                    )

                path_timeout_event[0] = Clock.schedule_once(_on_path_timeout, LINK_TIMEOUT)

                # RNS calls registered announce handlers when an announce
                # (which carries path + identity) is received.  Use a one-shot
                # announce handler that cancels the timeout and continues.
                class _PathWatcher:
                    aspect_filter = None
                    def received_announce(self, destination_hash, announced_identity,
                                          app_data, **kwargs):
                        if destination_hash == dest_hash:
                            if path_timeout_event[0]:
                                path_timeout_event[0].cancel()
                                path_timeout_event[0] = None
                            RNS.Transport.deregister_announce_handler(self)
                            status("Path resolved via announce")
                            _step_identity(dest_hash)

                RNS.Transport.register_announce_handler(_PathWatcher())

        except Exception as e:
            on_error(f"[EXCEPTION] {e}\n{traceback.format_exc()}")


# ─── UI Widgets ───────────────────────────────────────────────────────────────

class NodeDrawer(BoxLayout):
    """Slide-out drawer showing announced nodes (overlay)."""
    
    def __init__(self, on_node_select, **kwargs):
        super().__init__(orientation="vertical", **kwargs)
        self.on_node_select = on_node_select
        self.size_hint = (None, None)
        self.width = dp(280)
        self.height = Window.height
        
        # Header
        header = BoxLayout(size_hint_y=None, height=dp(56))
        with header.canvas.before:
            Color(*NAV_COLOR)
            header._bg = Rectangle(pos=header.pos, size=header.size)
        header.bind(pos=lambda i, v: setattr(i._bg, 'pos', v),
                    size=lambda i, v: setattr(i._bg, 'size', v))
        
        title = Label(
            text="Discovered Nodes",
            halign="left",
            valign="middle",
            font_size=sp(18),
            bold=True,
        )
        title.bind(size=lambda i, v: setattr(i, 'text_size', i.size))
        header.add_widget(title)
        
        # Close button
        close_btn = Button(
            text="✕",
            size_hint_x=None,
            width=dp(44),
            background_normal="",
            background_down="",
            background_color=(0, 0, 0, 0),
            color=FG_COLOR,
            font_size=sp(24),
        )
        close_btn.bind(on_press=self._close)
        header.add_widget(close_btn)
        
        self.add_widget(header)
        
        # Scrollable node list
        self._scroll = ScrollView(do_scroll_x=False)
        self._node_list = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            spacing=dp(2),
            padding=dp(4),
        )
        self._node_list.bind(minimum_height=self._node_list.setter('height'))
        self._scroll.add_widget(self._node_list)
        self.add_widget(self._scroll)
        
        # Track displayed nodes
        self._displayed_hashes = set()
        
        # Semi-transparent background overlay
        self._overlay_color = Color(0, 0, 0, 0)
        self._overlay_rect = None
        
        with self.canvas.before:
            Color(*BG_COLOR)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd_bg, size=self._upd_bg)
        
        # Bind to window height changes
        Window.bind(size=self._on_window_resize)
    
    def _on_window_resize(self, window, size):
        """Update drawer height when window resizes."""
        self.height = size[1]
    
    def _upd_bg(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
    
    def _close(self, *_):
        """Request drawer close via parent."""
        if hasattr(self, 'parent') and hasattr(self.parent, 'toggle_drawer'):
            self.parent.toggle_drawer()
    
    def add_node(self, node_info):
        """Add a node to the list if not already displayed."""
        node_hash = node_info.get("hash", "")
        if node_hash in self._displayed_hashes:
            return
        
        self._displayed_hashes.add(node_hash)
        
        # Create node card
        card = BoxLayout(
            orientation="vertical",
            size_hint_y=None,
            height=dp(72),
            padding=dp(8),
        )
        with card.canvas.before:
            Color(0.12, 0.15, 0.20, 1)
            card._bg = Rectangle(pos=card.pos, size=card.size)
        card.bind(pos=lambda i, v: setattr(i._bg, 'pos', v),
                  size=lambda i, v: setattr(i._bg, 'size', v))
        
        # Node name
        name = node_info.get("name", "Unknown Node")
        name_lbl = Label(
            text=name,
            halign="left",
            valign="middle",
            font_size=sp(14),
            bold=True,
            color=FG_COLOR,
        )
        name_lbl.bind(size=lambda i, v: setattr(i, 'text_size', i.size))
        
        # Node hash (shortened)
        hash_lbl = Label(
            text=f"{node_hash[:16]}...",
            halign="left",
            valign="top",
            font_size=sp(10),
            color=(0.6, 0.6, 0.6, 1),
        )
        hash_lbl.bind(size=lambda i, v: setattr(i, 'text_size', i.size))
        
        info_layout = BoxLayout(orientation="vertical")
        info_layout.add_widget(name_lbl)
        info_layout.add_widget(hash_lbl)
        
        # Navigate button
        nav_btn = Button(
            text="Navigate →",
            size_hint_x=None,
            width=dp(100),
            background_normal="",
            background_down="",
            background_color=BTN_COLOR,
            color=LNK_COLOR,
            font_size=sp(12),
        )
        nav_btn.bind(on_press=lambda i, h=node_hash: self._on_navigate(h))
        
        card.add_widget(info_layout)
        card.add_widget(nav_btn)
        
        self._node_list.add_widget(card)
    
    def _on_navigate(self, node_hash):
        """Navigate to selected node."""
        if self.on_node_select:
            self.on_node_select(node_hash)
            self._close()
    
    def clear_nodes(self):
        """Clear all displayed nodes."""
        self._node_list.clear_widgets()
        self._displayed_hashes.clear()


class NavigationDrawer(FloatLayout):
    """FloatLayout container that manages the slide-out drawer as an overlay."""
    
    def __init__(self, content, drawer, **kwargs):
        super().__init__(**kwargs)
        self.content_widget = content
        self.drawer = drawer
        self.drawer_open = False
        self._touch_start_x = None
        
        # Add content first (background)
        self.add_widget(self.content_widget)
        # Add drawer on top (will be positioned off-screen)
        self.add_widget(self.drawer)
        
        # Initial drawer position (off-screen left)
        Clock.schedule_once(self._init_positions, 0.1)
    
    def _init_positions(self, dt=None):
        """Initialize drawer position after layout is ready."""
        self.drawer.pos = (-self.drawer.width, 0)
        self.drawer.size_hint = (None, None)
        self.drawer.height = self.height
    
    def toggle_drawer(self):
        """Open or close the drawer with animation."""
        if self.drawer_open:
            self._close_drawer()
        else:
            self._open_drawer()
    
    def _open_drawer(self):
        """Animate drawer open (overlay, doesn't resize content)."""
        self.drawer_open = True
        self.drawer.height = self.height
        anim = Animation(pos=(0, 0), duration=0.25)
        anim.start(self.drawer)
    
    def _close_drawer(self):
        """Animate drawer closed."""
        self.drawer_open = False
        anim = Animation(pos=(-self.drawer.width, 0), duration=0.25)
        anim.start(self.drawer)
    
    def on_touch_down(self, touch):
        """Track touch for swipe gesture."""
        self._touch_start_x = touch.x
        return super().on_touch_down(touch)
    
    def on_touch_up(self, touch):
        """Detect swipe gesture."""
        if self._touch_start_x is not None:
            dx = touch.x - self._touch_start_x
            
            # Swipe right to open (from left edge)
            if dx > dp(50) and self._touch_start_x < dp(30):
                if not self.drawer_open:
                    self._open_drawer()
            
            # Swipe left to close (when drawer is open)
            elif dx < -dp(50) and self.drawer_open:
                self._close_drawer()
            
            # Tap outside drawer to close
            elif self.drawer_open and touch.x > self.drawer.width:
                self._close_drawer()
        
        self._touch_start_x = None
        return super().on_touch_up(touch)
    
    def on_size(self, instance, value):
        """Update drawer height when container resizes."""
        if hasattr(self, 'drawer'):
            self.drawer.height = self.height


class IconButton(Button):
    """A flat icon-style button using Unicode symbols."""
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.background_normal  = ""
        self.background_down    = ""
        self.background_color   = BTN_COLOR
        self.color              = FG_COLOR
        self.font_size          = sp(20)
        self.size_hint_x        = None
        self.width              = dp(48)
        self.bold               = False
        # Use a font that supports Unicode arrow/symbol glyphs
        # Roboto is standard on Android, DejaVuSans on Linux
        self.font_name = 'Roboto'


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

            elif etype == "literal":
                # Render literal/preformatted text (no markup processing)
                content = el.get("content", "")
                # Escape markup characters for literal display
                safe_text = content.replace("[", "[[").replace("]", "]]")
                lbl = Label(
                    text=safe_text,
                    markup=True,  # Still use markup to escape [[ ]]
                    font_size=sp(12),
                    halign="left",
                    valign="top",
                    size_hint_y=None,
                    color=(0.7, 0.7, 0.7, 1),  # Dimmer color for literal text
                    font_name="monospace",  # Use monospace font if available
                )
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
            self._history      = []
            self._hist_pos     = -1
            self._current_node = DEFAULT_NODE

            # Reticulum client with announce callback
            log("Creating ReticulumClient...")
            self._rns = ReticulumClient(on_announce_callback=self._on_announce_received)

            # Create node drawer
            log("Creating node drawer...")
            self._node_drawer = NodeDrawer(on_node_select=self._navigate_to_node)

            # Main content layout
            log("Creating main content...")
            main_content = BoxLayout(orientation="vertical")

            # Address / nav bar - add menu button
            log("Creating address bar...")
            self._addrbar = AddressBar(on_navigate=self._navigate_url)
            self._addrbar.back_btn.bind(on_press=self._go_back)
            self._addrbar.fwd_btn.bind(on_press=self._go_forward)
            self._addrbar.refresh_btn.bind(on_press=self._refresh)
            
            # Add menu button to open drawer
            menu_btn = IconButton(
                text="☰",
                width=dp(44),
                font_size=sp(24),
            )
            menu_btn.bind(on_press=lambda *_: self._toggle_drawer())
            self._addrbar.add_widget(menu_btn, index=0)

            # Page view
            log("Creating page view...")
            self._pageview = PageView(on_link_tap=self._on_link_tap)

            # Status bar
            log("Creating status bar...")
            self._statusbar = StatusBar(text="  Initialising Reticulum…")

            log("Adding widgets to main content...")
            main_content.add_widget(self._addrbar)
            main_content.add_widget(self._pageview)
            main_content.add_widget(self._statusbar)

            # Wrap in navigation drawer container
            log("Creating navigation drawer container...")
            self._nav_drawer = NavigationDrawer(
                content=main_content,
                drawer=self._node_drawer,
            )

            # Start Reticulum on main thread (required for signals), then load default page
            log("Scheduling Reticulum init...")
            Clock.schedule_once(self._init_rns_main, 0.5)

            log("App build() complete, returning root")
            return self._nav_drawer
        except Exception as e:
            log(f"Build error: {e}")
            log(traceback.format_exc())
            raise

    def _toggle_drawer(self):
        """Toggle the navigation drawer."""
        self._nav_drawer.toggle_drawer()

    def _on_announce_received(self, node_info):
        """Called when a node announce is received."""
        log(f"Announce received: {node_info.get('name', 'Unknown')} ({node_info.get('hash', '')[:8]}...)")
        self._node_drawer.add_node(node_info)
    
    def _load_existing_nodes(self, dt=None):
        """Load existing announced nodes from RNS."""
        try:
            nodes = self._rns.get_announced_nodes()
            for node in nodes:
                self._node_drawer.add_node(node)
        except Exception as e:
            log(f"Error loading existing nodes: {e}")

    def _navigate_to_node(self, node_hash):
        """Navigate to a selected node from the drawer."""
        self._load_page(node_hash, DEFAULT_PAGE, push_history=True)

    # ── Reticulum init ────────────────────────────────────────────────────────

    def _init_rns_main(self, dt=None):
        try:
            log("Starting Reticulum initialization on main thread...")
            self._set_status(f"Connecting to Noderage Hub at {NODERAGE_HOST}:{NODERAGE_PORT}…")
            self._rns.start(NODERAGE_HOST, NODERAGE_PORT)
            log("Reticulum started successfully")
            self._set_status("Connected – settling interface…")

            # Use a thread for the settlement delay and initial load
            threading.Thread(target=self._init_settle_and_load, daemon=True).start()

        except Exception as e:
            log(f"Init error: {e}")
            log(traceback.format_exc())
            self._set_status(f"Init error: {e}")
            self._pageview.show_status(
                f"[color=#ff5555]Failed to start Reticulum:\n{e}[/color]\n\n"
                f"[color=#888888]{traceback.format_exc()}[/color]",
                color=(1,0.33,0.33,1)
            )

    def _init_settle_and_load(self):
        # No sleep — schedule the initial page load on the Kivy clock so the
        # UI thread handles it after the interface has had one event loop cycle.
        Clock.schedule_once(self._do_initial_load, 0.5)

    def _do_initial_load(self, dt=None):
        try:
            log("Loading default page...")
            self._load_page(DEFAULT_NODE, DEFAULT_PAGE, push_history=True)
        except Exception as e:
            log(f"Initial load error: {e}")
            self._set_status(f"Load error: {e}")

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

    def _on_progress(self, msg):
        # msg is now either a diagnostic string or a numeric pct from progress_updated
        if isinstance(msg, int):
            self._set_status(f"Downloading… {msg}%")
        else:
            self._set_status(str(msg))

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
            with self._rns._lock:
                if self._rns._active_link:
                    self._rns._active_link.teardown()
                    self._rns._active_link = None
        except Exception:
            pass


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    RetiBrowserApp().run()
