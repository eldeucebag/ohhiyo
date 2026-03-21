#!/usr/bin/env python3
"""
RetiBrowser - A Kivy-based Reticulum NomadNet Micron Browser
Connects to a community hub and renders Micron markup pages.

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
import json

# ─── Kivy config BEFORE import ───────────────────────────────────────────────
os.environ.setdefault("KIVY_NO_ENV_CONFIG", "1")
os.environ["KIVY_TEXT"] = "sdl2"

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
from kivy.graphics import Color, Rectangle
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.animation import Animation
from kivy.utils import platform
from kivy.vector import Vector
from kivy.uix.dropdown import DropDown
from kivy.uix.modalview import ModalView
from kivy.uix.popup import Popup
from kivy.uix.gridlayout import GridLayout

import RNS
import RNS.vendor.umsgpack as umsgpack

# ─── Font Configuration ───────────────────────────────────────────────────────
FONT_PATH = None

def _init_font():
    global FONT_PATH
    for base in [
        os.path.dirname(os.path.abspath(__file__)),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "files"),
    ]:
        fp = os.path.join(base, "ShureTechMonoNerdFontMono-Regular.ttf")
        if os.path.exists(fp):
            FONT_PATH = fp
            log(f"Using bundled font: {FONT_PATH}")
            return
    FONT_PATH = ""
    log("Using system default font")

_init_font()

# ─── Configuration Manager ────────────────────────────────────────────────────

class ConfigManager:
    def __init__(self, config_dir):
        self.config_dir = config_dir
        self.config_file = os.path.join(config_dir, "retibrowser_config.json")
        self.cache_file = os.path.join(config_dir, "node_cache.json")
        self.config = {
            "node_name": "RetiBrowser Client",
            "default_node": "c95cce570afd2fa1545fa86c07256fdc",
            "hubs": [
                {"host": "rns.chicagonomad.net", "port": 4242, "enabled": True}
            ]
        }
        self.load()

    def load(self):
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, "r") as f:
                    loaded = json.load(f)
                    # Migrate old hub if necessary
                    if "hubs" not in loaded and "hub_host" in loaded:
                        loaded["hubs"] = [{"host": loaded["hub_host"], "port": loaded.get("hub_port", 4242), "enabled": True}]
                    self.config.update(loaded)
            except Exception as e:
                log(f"Error loading config: {e}")

    def save(self):
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            log(f"Error saving config: {e}")

    def load_node_cache(self):
        if os.path.exists(self.cache_file):
            try:
                with open(self.cache_file, "r") as f:
                    return json.load(f)
            except Exception as e:
                log(f"Error loading node cache: {e}")
        return {}

    def save_node_cache(self, cache):
        try:
            with open(self.cache_file, "w") as f:
                json.dump(cache, f, indent=4)
        except Exception as e:
            log(f"Error saving node cache: {e}")

    def purge_node_cache(self):
        try:
            if os.path.exists(self.cache_file):
                os.remove(self.cache_file)
            return True
        except Exception as e:
            log(f"Error purging node cache: {e}")
            return False

# ─── Constants ────────────────────────────────────────────────────────────────
DEFAULT_NODE  = "c95cce570afd2fa1545fa86c07256fdc"

DEFAULT_PAGE  = "/page/index.mu"
PAGE_TIMEOUT  = 60
LINK_TIMEOUT  = 45


# ─── Colours ──────────────────────────────────────────────────────────────────
MICRON_COLORS = {
    "f00": (1,0,0,1),       "0f0": (0,1,0,1),       "00f": (0,0,1,1),
    "ff0": (1,1,0,1),       "0ff": (0,1,1,1),       "f0f": (1,0,1,1),
    "fff": (1,1,1,1),       "000": (0,0,0,1),       "888": (.53,.53,.53,1),
    "aaa": (.67,.67,.67,1), "0a0": (0,.63,0,1),     "a00": (.63,0,0,1),
    "00a": (0,0,.63,1),     "fa0": (1,.63,0,1),     "0fa": (0,1,.63,1),
    "f80": (1,.5,0,1),      "5f5": (.33,1,.33,1),   "55f": (.33,.33,1,1),
    "f55": (1,.33,.33,1),   "5ff": (.33,1,1,1),
}
BG_COLOR  = (0.05, 0.05, 0.08, 1)
FG_COLOR  = (0.85, 0.90, 0.85, 1)
NAV_COLOR = (0.10, 0.12, 0.16, 1)
BTN_COLOR = (0.15, 0.20, 0.28, 1)
BTN_PRESS = (0.25, 0.35, 0.50, 1)
LNK_COLOR = (0.40, 0.80, 1.00, 1)


# ─── Micron Parser ────────────────────────────────────────────────────────────

def hex3_to_rgba(h):
    if h in MICRON_COLORS:
        return MICRON_COLORS[h]
    try:
        return (int(h[0]*2,16)/255, int(h[1]*2,16)/255, int(h[2]*2,16)/255, 1)
    except Exception:
        return FG_COLOR

def hex2_to_rgba(h):
    try:
        v = int(h, 16) / 255
        return (v, v, v, 1)
    except Exception:
        return FG_COLOR


def parse_micron(text):
    """
    Parse Micron markup → list of render elements.
    Ported from NomadNet's MicronParser logic for maximum compatibility.
    """
    elements = []
    
    # Initial state
    state = {
        "literal": False,
        "depth": 0,
        "fg_color": FG_COLOR,
        "bg_color": BG_COLOR,
        "formatting": {
            "bold": False,
            "underline": False,
            "italic": False,
        },
        "default_align": "left",
        "align": "left",
        "default_fg": FG_COLOR,
        "default_bg": BG_COLOR,
    }

    def get_kivy_color(color_spec):
        if color_spec == state["default_fg"]: return FG_COLOR
        if color_spec == state["default_bg"]: return BG_COLOR
        if isinstance(color_spec, (list, tuple)): return color_spec
        return hex3_to_rgba(color_spec)

    def make_segment(txt, s):
        return {
            "text": txt,
            "bold": s["formatting"]["bold"],
            "italic": s["formatting"]["italic"],
            "underline": s["formatting"]["underline"],
            "fg": get_kivy_color(s["fg_color"]),
            "bg": get_kivy_color(s["bg_color"]),
        }

    def process_line(line):
        nonlocal state
        if not line.strip() and not state["literal"]:
            return [{"type": "blank"}]

        # Check for literal toggle at start of line
        if line.strip() == "`=":
            state["literal"] = not state["literal"]
            return []

        if state["literal"]:
            # In literal mode, check for escape for literal toggle
            if line.strip() == "\\`=":
                return [{"type": "literal", "content": "`="}]
            return [{"type": "literal", "content": line}]

        # Normal parsing
        stripped = line.strip()
        first_char = stripped[0] if stripped else ""
        
        # Check for comments
        if stripped.startswith("#") and not stripped.startswith("#!"):
            return []

        # Check for section heading reset
        if first_char == "<" and len(stripped) == 1:
            state["depth"] = 0
            return []

        # Check for section headings
        if first_char == ">":
            i = 0
            while i < len(line) and line[i] == ">":
                i += 1
            if i > 0:
                state["depth"] = i
                content = line[i:].strip()
                if content.endswith("<"): content = content[:-1].strip()
                
                # Heading styles from NomadNet
                heading_fg = {1: (1, 0.85, 0.3, 1), 2: (0.6, 1, 0.7, 1), 3: (0.7, 0.9, 1, 1)}.get(i, (1,1,1,1))
                
                # Headings in NomadNet are bold
                old_bold = state["formatting"]["bold"]
                old_fg = state["fg_color"]
                state["formatting"]["bold"] = True
                state["fg_color"] = heading_fg
                
                # Parse inline content of heading
                res = parse_inline(content)
                
                state["formatting"]["bold"] = old_bold
                state["fg_color"] = old_fg
                
                segments = []
                links = []
                for item in res:
                    if item["type"] == "text":
                        segments.extend(item["segments"])
                    elif item["type"] == "link":
                        links.append(item)
                
                out = []
                if segments:
                    out.append({"type": "text", "heading": i, "align": "left", "segments": segments})
                out.extend(links)
                return out

        # Check for horizontal dividers
        if first_char == "-":
            if stripped == "-" or stripped == "---" or stripped == "`-`":
                return [{"type": "divider"}]
            if len(stripped) == 2 and stripped[0] == "-" and stripped[1] not in " \t":
                return [{"type": "divider", "char": stripped[1]}]
        
        if stripped == "`-`":
            return [{"type": "divider"}]

        # Default line parsing
        return parse_inline(line)

    def parse_inline(line):
        nonlocal state
        line_elements = []
        segments = []
        part = ""
        mode = "text"
        escape = False
        skip = 0

        def flush_text():
            nonlocal part
            if part:
                if state["literal"]:
                    # In literal mode, segments are treated as literal elements for consistency with existing tests
                    # but Kivy renderer uses 'literal' type for block literal. 
                    # For INLINE literal, we'll just use a special segment format or text.
                    # Actually, the existing tests expect elements to be split.
                    segments.append(make_segment(part, state))
                else:
                    segments.append(make_segment(part, state))
                part = ""

        def flush_elements():
            flush_text()
            if segments:
                line_elements.append({"type":"text", "heading":0, "align":state["align"], "segments":segments})
                return True
            return False

        for i in range(len(line)):
            if skip > 0:
                skip -= 1
                continue
            
            c = line[i]
            
            if mode == "formatting":
                if c == "_": state["formatting"]["underline"] = not state["formatting"]["underline"]
                elif c == "!": state["formatting"]["bold"] = not state["formatting"]["bold"]
                elif c == "*": state["formatting"]["italic"] = not state["formatting"]["italic"]
                elif c == "F" and i+3 < len(line):
                    state["fg_color"] = line[i+1:i+4]
                    skip = 3
                elif c == "f": state["fg_color"] = state["default_fg"]
                elif c == "B" and i+3 < len(line):
                    state["bg_color"] = line[i+1:i+4]
                    skip = 3
                elif c == "b": state["bg_color"] = state["default_bg"]
                elif c == "g" and i+2 < len(line):
                    state["fg_color"] = hex2_to_rgba(line[i+1:i+3])
                    skip = 2
                elif c == "`":
                    if i+1 < len(line) and line[i+1] == "=":
                        # Inline literal toggle!
                        if flush_elements():
                            # If we were in text, we finished that element
                            pass
                        # Actually, if we're IN literal mode now, we should switch type.
                        # But existing PageView might not handle mixed 'text' and 'literal' in a line well.
                        # Let's see what the tests want.
                        state["literal"] = not state["literal"]
                        if state["literal"]:
                            # We just entered literal mode.
                            pass
                        else:
                            # We just left literal mode.
                            # We should probably create a literal element for what we just finished.
                            pass
                        
                        skip = 1
                    else:
                        state["formatting"]["bold"] = False
                        state["formatting"]["underline"] = False
                        state["formatting"]["italic"] = False
                        state["fg_color"] = state["default_fg"]
                        state["bg_color"] = state["default_bg"]
                        state["align"] = state["default_align"]
                elif c == "c": state["align"] = "center"
                elif c == "l": state["align"] = "left"
                elif c == "r": state["align"] = "right"
                elif c == "a": state["align"] = state["default_align"]
                elif c == "[":
                    endpos = line[i:].find("]")
                    if endpos != -1:
                        link_data = line[i+1:i+endpos]
                        skip = endpos
                        parts = link_data.split("`")
                        # label`url`fields
                        label = parts[0] if len(parts) > 1 else (parts[0] if parts else "")
                        url = parts[1] if len(parts) > 1 else (parts[0] if parts else "")
                        
                        node_addr, page_path = "", url
                        if ":" in url and not url.startswith("/"):
                            node_addr, page_path = url.split(":", 1)
                        
                        if not label: label = page_path
                        
                        if page_path.startswith("lxmf") or node_addr.startswith("lxmf"):
                            flush_text()
                            segments.append({
                                "text": f"✉ {label}", "bold": False, "italic": True,
                                "underline": True, "fg": (0.6,0.8,0.6,1), "bg": get_kivy_color(state["bg_color"]),
                            })
                        else:
                            if flush_elements():
                                line_elements[-1]["segments"] = segments
                                segments = []
                            else:
                                pass
                            
                            # If we have pending text segments, flush them to an element first
                            if segments:
                                line_elements.append({"type":"text", "heading":0, "align":state["align"], "segments":segments})
                                segments = []

                            line_elements.append({
                                "type":"link", "label":label, "path":page_path, "node":node_addr, "fg":LNK_COLOR,
                            })
                elif c == "<":
                    # Input fields
                    endpos = line[i:].find(">")
                    if endpos != -1:
                        field_data = line[i+1:i+endpos]
                        skip = endpos
                        tick = field_data.rfind("`")
                        default = field_data[tick+1:] if tick != -1 else ""
                        if default:
                            flush_text()
                            segments.append({
                                "text": f"[{default}]", "bold": False, "italic": True,
                                "underline": False, "fg": (0.5,0.6,0.7,1), "bg": get_kivy_color(state["bg_color"]),
                            })
                
                mode = "text"
                continue

            if c == "\\":
                if escape:
                    part += c
                    escape = False
                else:
                    escape = True
            elif c == "`" and not state["literal"]:
                if escape:
                    part += c
                    escape = False
                else:
                    # In text mode, ` starts formatting
                    flush_text()
                    mode = "formatting"
            elif c == "`" and state["literal"]:
                if i+1 < len(line) and line[i+1] == "=":
                    # Literal toggle while IN literal mode
                    # Flush literal text to a 'literal' element
                    if part:
                        line_elements.append({"type": "literal", "content": part})
                        part = ""
                    state["literal"] = False
                    skip = 1
                else:
                    part += c
            else:
                part += c
                escape = False
        
        if part:
            if state["literal"]:
                line_elements.append({"type": "literal", "content": part})
            else:
                flush_text()
                if segments:
                    line_elements.append({"type":"text", "heading":0, "align":state["align"], "segments":segments})
        elif segments:
             line_elements.append({"type":"text", "heading":0, "align":state["align"], "segments":segments})
        
        return line_elements

    # Initial stripping of cache headers
    lines = text.split("\n")
    while lines and lines[0].strip().startswith("#!"):
        lines = lines[1:]

    for line in lines:
        line = line.rstrip("\r")
        res = process_line(line)
        if res:
            elements.extend(res)
            
    return elements


# ─── Reticulum Network Layer ──────────────────────────────────────────────────

class AnnounceHandler:
    """Receives RNS announce packets and extracts node info."""

    aspect_filter = None  # Must be None — RNS aspect_filter string matching is unreliable

    def __init__(self, config_manager, on_announce_callback=None):
        self.config_manager = config_manager
        self.on_announce_callback = on_announce_callback
        self._announced_nodes = {}
        # destination_hash (bytes) -> RNS.Identity; keyed by dest hash not identity hash
        self._identities = {}
        self._node_names = {}
        self._load_cache()

    def _load_cache(self):
        cache = self.config_manager.load_node_cache()
        for node_hash, data in cache.items():
            self._announced_nodes[node_hash] = data["info"]
            dest_hash = bytes.fromhex(node_hash)
            self._node_names[dest_hash] = tuple(data["names"])
            
            # Reconstruct identity from public key
            if "pub_key" in data:
                try:
                    pub_key = bytes.fromhex(data["pub_key"])
                    identity = RNS.Identity.from_bytes(pub_key)
                    self._identities[dest_hash] = identity
                except Exception as e:
                    log(f"Error restoring identity for {node_hash}: {e}")

    def _save_cache(self):
        cache = {}
        for node_hash, info in self._announced_nodes.items():
            dest_hash = bytes.fromhex(node_hash)
            names = self._node_names.get(dest_hash, ("nomadnetwork", "node"))
            identity = self._identities.get(dest_hash)
            
            entry = {
                "info": info,
                "names": list(names),
            }
            if identity:
                entry["pub_key"] = RNS.hexrep(identity.get_public_key(), delimit=False)
            
            cache[node_hash] = entry
            
        self.config_manager.save_node_cache(cache)

    def received_announce(self, destination_hash, announced_identity, app_data,
                          announce_packet_hash=None, is_path_response=False):
        if not announced_identity:
            return

        # Identify if this is a nomadnetwork.node announce.
        is_nomadnet = False
        matched_names = ("nomadnetwork", "node")
        try:
            # We check if the destination hash matches the nomadnetwork.node aspect
            # for the identity that announced.
            h_str  = RNS.Destination.hash_from_name_and_identity("nomadnetwork.node", announced_identity)
            h_str2 = RNS.Destination.hash_from_name_and_identity("nomadnet.node", announced_identity)
            
            if destination_hash == h_str:
                is_nomadnet = True
                matched_names = ("nomadnetwork", "node")
            elif destination_hash == h_str2:
                is_nomadnet = True
                matched_names = ("nomadnet", "node")
        except Exception as e:
            RNS.log(f"RetiBrowser: Error identifying NomadNet node: {e}", RNS.LOG_DEBUG)

        # Fallback: some older nodes might announce differently, or RNS versions might vary.
        # If app_data looks like NomadNet data, we can also consider it.
        if not is_nomadnet and app_data:
            try:
                unpacked = umsgpack.unpackb(app_data)
                if isinstance(unpacked, list) and len(unpacked) >= 1:
                    # NomadNet nodes usually have a name as the first element of a list
                    if isinstance(unpacked[0], (str, bytes)) and len(unpacked[0]) > 0:
                        # This is a bit broad, but helps if the hash calculation above fails
                        # for some reason (e.g. name mismatch "nomadnet" vs "nomadnetwork")
                        is_nomadnet = True
                        matched_names = ("nomadnetwork", "node")
            except Exception:
                pass

        if not is_nomadnet:
            return

        try:
            node_hash = RNS.hexrep(destination_hash, delimit=False)

            # Parse app_data — NomadNet nodes use several formats:
            #   dict   : {"name": "...", "type": "...", ...}
            #   list   : [b"NodeName", None|dict]  — most common NomadNet format
            #   bytes  : msgpack-encoded dict or list
            #   scalar : int/None — no useful name info
            info = {}
            unpacked = app_data
            if isinstance(app_data, bytes):
                try:
                    unpacked = umsgpack.unpackb(app_data)
                except Exception:
                    unpacked = {}

            if isinstance(unpacked, dict):
                info = unpacked
            elif isinstance(unpacked, list):
                # [b'NodeName', optional_dict_or_None]
                name_raw = unpacked[0] if unpacked else None
                extra    = unpacked[1] if len(unpacked) > 1 else None
                if isinstance(name_raw, bytes):
                    info["name"] = name_raw.decode("utf-8", errors="replace")
                elif isinstance(name_raw, str):
                    info["name"] = name_raw
                if isinstance(extra, dict):
                    info.update(extra)

            # If info itself is a list (nested unpack), handle similarly
            if isinstance(info, list):
                name_raw = info[0] if info else None
                extra    = info[1] if len(info) > 1 else None
                info = {}
                if isinstance(name_raw, bytes):
                    info["name"] = name_raw.decode("utf-8", errors="replace")
                elif isinstance(name_raw, str):
                    info["name"] = name_raw
                if isinstance(extra, dict):
                    info.update(extra)

            name = (info.get("name") or info.get("nodename") or
                    info.get("node_name") or info.get("title") or
                    info.get("display_name") or info.get("hostname") or
                    f"Node {node_hash[:8]}")

            caps = info.get("capabilities", [])
            # LXMF detection
            is_lxmf = "lxmf" in caps
            if not is_lxmf and announced_identity:
                try:
                    lx_h = RNS.Destination.hash_from_name_and_identity("lxmf.delivery", announced_identity)
                    # If we could check if lx_h is in RNS routing table or something, but 
                    # usually if it's a nomadnet node, it'll have lxmf in caps if it supports it.
                    pass
                except: pass

            node_record = {
                "hash":         node_hash,
                "name":         name,
                "timestamp":    info.get("timestamp", time.time()),
                "capabilities": caps,
                "type":         info.get("type", "unknown"),
                "is_lxmf":      is_lxmf,
            }
            self._announced_nodes[node_hash] = node_record
            if announced_identity:
                self._identities[destination_hash] = announced_identity
                self._node_names[destination_hash] = matched_names
            
            # Persist to cache
            self._save_cache()
            
            log(f"Announce: {name} ({node_hash[:8]}…)")

            if self.on_announce_callback:
                Clock.schedule_once(
                    lambda dt, nr=node_record: self.on_announce_callback(nr), 0)
        except Exception as e:
            RNS.log(f"RetiBrowser: announce handler error: {e}", RNS.LOG_ERROR)

    def get_announced_nodes(self):
        return list(self._announced_nodes.values())

    def get_identity(self, dest_hash_bytes):
        """Return the Identity for a destination hash bytes object."""
        return self._identities.get(dest_hash_bytes)

    def get_names(self, dest_hash_bytes):
        """Return the app/aspect names for a destination hash."""
        return self._node_names.get(dest_hash_bytes)


class ReticulumClient:
    """Manages the RNS instance and page fetching."""

    def __init__(self, config_manager, on_announce_callback=None):
        self.rns              = None
        self.identity         = None
        self._active_link     = None
        self._lock            = threading.Lock()
        self.config_manager   = config_manager
        self.announce_handler = AnnounceHandler(config_manager, on_announce_callback)

    def start(self):
        # Resolve a writable config directory
        try:
            from kivy.app import App as KivyApp
            app = KivyApp.get_running_app()
            config_root = app.user_data_dir if (app and app.user_data_dir) else os.path.expanduser("~")
        except Exception:
            config_root = os.path.expanduser("~")

        config_path = os.path.join(config_root, ".reticulum_retibrowser")
        os.makedirs(config_path, exist_ok=True)

        # Build interfaces section from config_manager
        interfaces_config = ""
        for i, hub in enumerate(self.config_manager.config["hubs"]):
            if hub.get("enabled", True):
                interfaces_config += f"""
  [[Community Hub {i}]]
    type        = TCPClientInterface
    enabled     = yes
    target_host = {hub['host']}
    target_port = {hub['port']}
"""

        # Write RNS config.
        with open(os.path.join(config_path, "config"), "w") as f:
            f.write(f"""[reticulum]
  enable_transport = No
  share_instance   = No
  rpc_listener     = No

[interfaces]
{interfaces_config}
""")

        self.rns = RNS.Reticulum(configdir=config_path, loglevel=RNS.LOG_DEBUG)

        # Persistent identity
        identity_file = os.path.join(config_path, "identity")
        if os.path.exists(identity_file):
            self.identity = RNS.Identity.from_file(identity_file)
            log(f"Loaded identity: {RNS.hexrep(self.identity.hash, delimit=False)[:8]}…")
        else:
            self.identity = RNS.Identity()
            self.identity.to_file(identity_file)
            log(f"Created identity: {RNS.hexrep(self.identity.hash, delimit=False)[:8]}…")

        # Register handler BEFORE any announces could arrive
        RNS.Transport.register_announce_handler(self.announce_handler)
        RNS.log("RetiBrowser: Reticulum started", RNS.LOG_NOTICE)

    def stop(self):
        if self.rns:
            # There's no explicit stop in RNS, but we can clean up our link
            try:
                with self._lock:
                    if self._active_link:
                        self._active_link.teardown()
                        self._active_link = None
            except Exception:
                pass

    def get_announced_nodes(self):
        return self.announce_handler.get_announced_nodes()

    def fetch_page(self, node_hex, page_path, on_done, on_error, on_progress=None):
        threading.Thread(
            target=self._fetch_thread,
            args=(node_hex, page_path, on_done, on_error, on_progress),
            daemon=True,
        ).start()

    def _fetch_thread(self, node_hex, page_path, on_done, on_error, on_progress):
        """
        Pure callback chain — no sleep(), no Event.wait(), no polling.

        _fetch_thread
          → (path in table?) yes → _step_identity
                              no  → register _PathWatcher + timeout
                                      → on announce → _step_identity
          → _step_identity  → recall identity → _step_open_link
          → _step_open_link → RNS.Link() + timeout clock
                                → _on_link_established → _step_send_request
          → _step_send_request → link.request()
                                    → response_received → on_done
                                    → request_failed   → on_error
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
            status(f"dest={node_hex[:8]}… path={page_path}")

            # Log interface state
            interfaces = getattr(RNS.Transport, "interfaces", [])
            status(f"{len(interfaces)} interface(s): " +
                   ", ".join(f"{getattr(i,'name','?')} online={getattr(i,'online','?')}"
                             for i in interfaces))

            def _step_identity(dh):
                # Primary: look up the identity we stored when the announce arrived.
                identity = self.announce_handler.get_identity(dh)
                names    = self.announce_handler.get_names(dh) or ("nomadnetwork", "node")
                
                if not identity:
                    fail(f"[FAIL] Identity not found for {RNS.hexrep(dh,delimit=False)[:8]}…\n"
                         f"  Node may not have announced recently.")
                    return
                status(f"Identity: {RNS.hexrep(identity.hash,delimit=False)[:8]}… Names: {'.'.join(names)}")
                _step_open_link(identity, dh, names)

            def _step_open_link(identity, dh, names):
                destination = RNS.Destination(
                    identity, RNS.Destination.OUT, RNS.Destination.SINGLE,
                    *names
                )
                if destination.hash != dh:
                    status(f"WARNING: Hash mismatch! Expected {RNS.hexrep(dh,0)[:8]} Calculated {RNS.hexrep(destination.hash,0)[:8]}")
                
                status(f"Opening link to {RNS.hexrep(destination.hash,delimit=False)[:8]}…")

                timeout_ev = [None]

                def _on_link_established(link):
                    if timeout_ev[0]:
                        timeout_ev[0].cancel()
                        timeout_ev[0] = None
                    status("Link established!")
                    _step_send_request(link)

                def _on_link_closed(link):
                    # If the timeout clock is still pending when the link closes,
                    # it means the link never established. Let the timeout fire
                    # naturally with its descriptive error rather than failing
                    # immediately — RNS may internally retry the link after a
                    # path rediscovery, and we don't want to abort prematurely.
                    # The timeout clock will call fail() if the link stays down.
                    if timeout_ev[0]:
                        status("Link closed before established — waiting for timeout or retry")

                def _on_link_timeout(dt):
                    timeout_ev[0] = None
                    fail(f"[FAIL] Link timed out after {LINK_TIMEOUT}s\n"
                         f"  Is the page node destination still running?")

                with self._lock:
                    self._active_link = RNS.Link(destination)
                self._active_link.set_link_established_callback(_on_link_established)
                self._active_link.set_link_closed_callback(_on_link_closed)
                timeout_ev[0] = Clock.schedule_once(_on_link_timeout, LINK_TIMEOUT)
                status("Waiting for link…")

            def _step_send_request(link):
                status(f"Sending request: {page_path}")

                def response_received(receipt):
                    status(f"Response: status={receipt.status}")
                    if receipt.status == RNS.RequestReceipt.FAILED:
                        fail(f"[FAIL] Request failed for {page_path}")
                        return
                    if receipt.response is not None:
                        raw = receipt.response
                        page_content = (raw.decode("utf-8", errors="replace")
                                        if isinstance(raw, bytes) else str(raw))
                        status(f"Response {len(page_content)} chars — rendering…")
                        teardown()
                        on_done(page_content)

                def progress_updated(receipt):
                    status(f"Downloading… {int(receipt.progress*100)}%")

                def request_failed(receipt):
                    fail(f"[FAIL] Request failed (status={receipt.status}) for {page_path}")

                # Send the FULL path — server routes on this argument directly.
                # Never truncate to "/page": that breaks every page except index.mu.
                link.request(
                    page_path,
                    data              = None,
                    response_callback = response_received,
                    failed_callback   = request_failed,
                    progress_callback = progress_updated,
                    timeout           = PAGE_TIMEOUT,
                )

            # ── Start the chain ───────────────────────────────────────────────
            # Fast path: if we have the identity from a recent announce,
            # open the link immediately. Do NOT use Identity.recall(dest_hash)
            # here — recall() takes an identity hash but dest_hash is a
            # destination hash. They are different values.
            if self.announce_handler.get_identity(dest_hash) is not None:
                status("Identity already known — opening link directly")
                _step_identity(dest_hash)
                return

            # Slow path: identity not cached. We need to either:
            #   a) get a path-response (updates routing table, no identity)
            #      then wait for an announce that carries the identity, OR
            #   b) get an announce directly (has both path + identity)
            #
            # expire_announced_path removes a stale cached path entry so RNS
            # doesn't try to use a dead next-hop from a previous session.
            if hasattr(RNS.Transport, "expire_announced_path"):
                try:
                    RNS.Transport.expire_announced_path(dest_hash)
                except Exception:
                    pass

            status("Requesting path…")
            RNS.Transport.request_path(dest_hash)

            # Wait using BOTH mechanisms simultaneously:
            # 1. Clock.schedule_interval polls has_path() + Identity.recall()
            #    every 0.25s — catches path-response packets (no announce handler
            #    fires for these) AND the subsequent announce that brings identity.
            # 2. _PathWatcher fires immediately if an announce arrives first.
            # Whichever fires first cancels the other.

            _path_resolved = [False]
            path_poll      = [None]
            path_timeout   = [None]
            watcher        = [None]

            def _resolve_path():
                if _path_resolved[0]:
                    return
                _path_resolved[0] = True
                if path_poll[0]:
                    Clock.unschedule(path_poll[0])
                    path_poll[0] = None
                if path_timeout[0]:
                    path_timeout[0].cancel()
                    path_timeout[0] = None
                if watcher[0]:
                    try:
                        RNS.Transport.deregister_announce_handler(watcher[0])
                    except Exception:
                        pass
                    watcher[0] = None
                _step_identity(dest_hash)

            def _poll_path(dt):
                # Use stored identity dict, not Identity.recall(dest_hash).
                # recall() takes an identity hash; dest_hash is a destination hash.
                if self.announce_handler.get_identity(dest_hash) is not None:
                    status("Identity received via announce — proceeding")
                    _resolve_path()
                    return False
                # Path known but no identity yet — keep waiting for announce

            def _on_path_timeout(dt):
                path_timeout[0] = None
                if _path_resolved[0]:
                    return
                _path_resolved[0] = True
                if path_poll[0]:
                    Clock.unschedule(path_poll[0])
                if watcher[0]:
                    try:
                        RNS.Transport.deregister_announce_handler(watcher[0])
                    except Exception:
                        pass
                
                hubs_str = ", ".join([f"{h['host']}:{h['port']}" for h in self.config_manager.config["hubs"] if h.get("enabled", True)])
                fail(f"[FAIL] Path or Identity not found after {LINK_TIMEOUT}s\n"
                     f"  Node: {node_hex}\n"
                     f"  Hubs: {hubs_str}\n"
                     f"  Wait for a fresh announce from this node.")

            class _PathWatcher:
                aspect_filter = None  # Filter manually in received_announce
                def received_announce(self_w, destination_hash, announced_identity,
                                      app_data, **kw):
                    if destination_hash == dest_hash:
                        status("Path resolved via announce")
                        _resolve_path()

            watcher[0] = _PathWatcher()
            RNS.Transport.register_announce_handler(watcher[0])
            path_poll[0]    = Clock.schedule_interval(_poll_path, 0.25)
            path_timeout[0] = Clock.schedule_once(_on_path_timeout, LINK_TIMEOUT)

        except Exception as e:
            on_error(f"[EXCEPTION] {e}\n{traceback.format_exc()}")


# ─── UI Widgets ───────────────────────────────────────────────────────────────

class IconButton(Button):
    def __init__(self, **kwargs):
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_down", "")
        kwargs.setdefault("background_color", BTN_COLOR)
        kwargs.setdefault("color", FG_COLOR)
        kwargs.setdefault("font_size", sp(28))
        kwargs.setdefault("size_hint_x", None)
        kwargs.setdefault("width", dp(52))
        kwargs.setdefault("bold", False)
        kwargs.setdefault("font_name", FONT_PATH)
        kwargs.setdefault("halign", "center")
        kwargs.setdefault("valign", "middle")
        super().__init__(**kwargs)


class AddressBar(BoxLayout):
    def __init__(self, on_navigate, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=dp(48), spacing=dp(4), padding=[dp(4),dp(4)], **kwargs)
        self.on_navigate = on_navigate
        with self.canvas.before:
            Color(*NAV_COLOR)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)
        self.back_btn    = IconButton(text="←", width=dp(44))
        self.fwd_btn     = IconButton(text="→", width=dp(44))
        self.refresh_btn = IconButton(text="⟳", width=dp(44))
        self.go_btn      = IconButton(text="➜", width=dp(44))
        self.address = TextInput(
            text="", multiline=False, font_size=sp(14),
            background_color=(0.12,0.15,0.20,1),
            foreground_color=FG_COLOR, cursor_color=LNK_COLOR,
            padding=[dp(8), dp(10)],
        )
        for w in (self.back_btn, self.fwd_btn, self.refresh_btn, self.address, self.go_btn):
            self.add_widget(w)
        self.address.bind(on_text_validate=self._go)
        self.go_btn.bind(on_press=self._go)

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _go(self, *_):
        self.on_navigate(self.address.text.strip())

    def set_url(self, url):
        self.address.text = url


class StatusBar(Label):
    def __init__(self, **kwargs):
        super().__init__(size_hint_y=None, height=dp(24), font_size=sp(11),
                         halign="left", color=(0.6,0.6,0.6,1),
                         text_size=(Window.width, None), **kwargs)
        with self.canvas.before:
            Color(0.08, 0.08, 0.10, 1)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size
        self.text_size = (self.width, None)


class LinkButton(Button):
    def __init__(self, label, path, node, on_tap, **kwargs):
        super().__init__(
            text=f"  ▸ {label}",
            background_normal="", background_down="",
            background_color=(0,0,0,0), color=LNK_COLOR,
            halign="left", valign="middle",
            size_hint_y=None, height=dp(34), font_size=sp(14), **kwargs)
        self.path, self.node, self.on_tap = path, node, on_tap
        self.text_size = (None, None)
        self.bind(size=lambda *_: setattr(self, "text_size", (self.width, None)))
        self.bind(on_press=self._pressed)

    def _pressed(self, *_):
        self.background_color = BTN_PRESS
        Clock.schedule_once(lambda *_: setattr(self, "background_color", (0,0,0,0)), 0.15)
        self.on_tap(self.node, self.path)


class NodeDrawer(BoxLayout):
    def __init__(self, on_node_select, **kwargs):
        super().__init__(orientation="vertical", size_hint=(None,None),
                         width=dp(280), height=Window.height, **kwargs)
        self.on_node_select = on_node_select
        self._node_widgets = {} # hash -> card widget

        with self.canvas.before:
            Color(*BG_COLOR)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)
        Window.bind(size=lambda w, s: setattr(self, "height", s[1]))

        # Header
        hdr = BoxLayout(size_hint_y=None, height=dp(56))
        with hdr.canvas.before:
            Color(*NAV_COLOR)
            hdr._bg = Rectangle(pos=hdr.pos, size=hdr.size)
        hdr.bind(pos=lambda i,v: setattr(i._bg,"pos",v),
                 size=lambda i,v: setattr(i._bg,"size",v))
        ttl = Label(text="Discovered Nodes", halign="left", valign="middle",
                    font_size=sp(18), bold=True)
        ttl.bind(size=lambda i,v: setattr(i,"text_size",i.size))
        hdr.add_widget(ttl)
        close = IconButton(text="×", width=dp(44))
        close.bind(on_press=self._close)
        hdr.add_widget(close)
        self.add_widget(hdr)

        # Node list
        self._scroll = ScrollView(do_scroll_x=False)
        self._node_list = BoxLayout(orientation="vertical", size_hint_y=None,
                                    spacing=dp(2), padding=dp(4))
        self._node_list.bind(minimum_height=self._node_list.setter("height"))
        self._scroll.add_widget(self._node_list)
        self.add_widget(self._scroll)

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def _close(self, *_):
        if hasattr(self, "parent") and hasattr(self.parent, "toggle_drawer"):
            self.parent.toggle_drawer()

    def add_node(self, node_info):
        nh = node_info.get("hash", "")
        
        # If already exists, move to top
        if nh in self._node_widgets:
            card = self._node_widgets[nh]
            self._node_list.remove_widget(card)
            # In Kivy BoxLayout, index 0 is the LAST added widget by default
            # (which means bottom). To put on top, we add it as the last index
            # or just call add_widget() without index to put it at the "end".
            # Wait, Kivy default is index=0 is the last in children list, 
            # and BoxLayout renders children[0] at the bottom.
            # So to put at TOP, we want it to be children[-1].
            self._node_list.add_widget(card)
            return

        card = BoxLayout(orientation="horizontal", size_hint_y=None,
                         height=dp(64), padding=dp(8), spacing=dp(8))
        with card.canvas.before:
            Color(0.12, 0.15, 0.20, 1)
            card._bg = Rectangle(pos=card.pos, size=card.size)
        card.bind(pos=lambda i,v: setattr(i._bg,"pos",v),
                  size=lambda i,v: setattr(i._bg,"size",v))

        info = BoxLayout(orientation="vertical")
        name_row = BoxLayout(orientation="horizontal", spacing=dp(4))
        name_lbl = Label(text=node_info.get("name","?"), halign="left", valign="middle",
                         font_size=sp(14), bold=True, color=FG_COLOR, font_name=FONT_PATH,
                         size_hint_x=None)
        name_lbl.bind(texture_size=lambda i,v: setattr(i,"width",v[0]))
        name_row.add_widget(name_lbl)
        
        # Indicators
        caps = node_info.get("capabilities", [])
        if "pages" in caps or "micron" in caps:
            p_ind = Label(text="\uf0ac", font_size=sp(12), color=(0.2, 0.8, 1, 1),
                          size_hint=(None, None), size=(dp(20), dp(20)), font_name=FONT_PATH)
            name_row.add_widget(p_ind)
            
        if node_info.get("is_lxmf") or "lxmf" in caps:
            l_ind = Label(text="\uf0e0", font_size=sp(12), color=(0.2, 1, 0.2, 1),
                          size_hint=(None, None), size=(dp(20), dp(20)), font_name=FONT_PATH)
            name_row.add_widget(l_ind)
            
        info.add_widget(name_row)
        
        hash_lbl = Label(text=f"{nh[:16]}…", halign="left", valign="top",
                         font_size=sp(10), color=(0.6,0.6,0.6,1), font_name=FONT_PATH)
        hash_lbl.bind(size=lambda i,v: setattr(i,"text_size",i.size))
        info.add_widget(hash_lbl)

        nav = Button(text="Go →", size_hint_x=None, width=dp(60),
                     background_normal="", background_down="",
                     background_color=BTN_COLOR, color=LNK_COLOR, font_size=sp(12))
        nav.bind(on_press=lambda i, h=nh: self._navigate(h))
        card.add_widget(info)
        card.add_widget(nav)
        
        self._node_widgets[nh] = card
        self._node_list.add_widget(card)

    def _navigate(self, node_hash):
        if self.on_node_select:
            self.on_node_select(node_hash)
            self._close()

    def clear_nodes(self):
        self._node_list.clear_widgets()
        self._node_widgets.clear()


class NavigationDrawer(FloatLayout):
    def __init__(self, content, drawer, **kwargs):
        super().__init__(**kwargs)
        self.drawer = drawer
        self.drawer_open = False
        self._touch_start_x = None
        self._drawer_open_at_touch_down = False  # state at touch_down, not touch_up
        self.add_widget(content)
        self.add_widget(drawer)
        Clock.schedule_once(lambda dt: setattr(drawer, "pos", (-drawer.width, 0)), 0.1)

    def toggle_drawer(self):
        if self.drawer_open:
            self.drawer_open = False
            Animation(pos=(-self.drawer.width, 0), duration=0.25).start(self.drawer)
        else:
            self.drawer_open = True
            self.drawer.height = self.height
            Animation(pos=(0, 0), duration=0.25).start(self.drawer)

    def on_touch_down(self, touch):
        # Snapshot drawer state at the START of the touch, not the end.
        # toggle_drawer() may be called between touch_down and touch_up (by a
        # button handler), so checking drawer_open in on_touch_up gives the
        # wrong state — the drawer appears open when it was just opened by this
        # very touch, causing an immediate re-close on desktop.
        self._touch_start_x = touch.x
        self._drawer_open_at_touch_down = self.drawer_open
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if self._touch_start_x is not None:
            dx = touch.x - self._touch_start_x
            was_open = self._drawer_open_at_touch_down

            # Swipe gestures — only on Android
            if platform == "android":
                # Swipe right from left edge → open
                if dx > dp(50) and self._touch_start_x < dp(30) and not was_open:
                    if not self.drawer_open:
                        self.toggle_drawer()

                # Swipe left → close
                elif dx < -dp(50) and was_open:
                    if self.drawer_open:
                        self.toggle_drawer()

            # Tap outside drawer → close (on all platforms)
            # only if drawer was ALREADY open when the finger went down.
            if was_open and abs(dx) < dp(10) and touch.x > self.drawer.width:
                if self.drawer_open:
                    self.toggle_drawer()

        self._touch_start_x = None
        self._drawer_open_at_touch_down = False
        return super().on_touch_up(touch)

    def on_size(self, *_):
        if hasattr(self, "drawer"):
            self.drawer.height = self.height


class PageView(ScrollView):
    def __init__(self, on_link_tap, **kwargs):
        super().__init__(do_scroll_x=False, bar_width=dp(4),
                         bar_color=LNK_COLOR, bar_inactive_color=(0.3,0.3,0.3,0.5),
                         **kwargs)
        self.on_link_tap = on_link_tap
        self.container = BoxLayout(orientation="vertical", size_hint_y=None,
                                   spacing=dp(2), padding=[dp(12), dp(8)])
        self.container.bind(minimum_height=self.container.setter("height"))
        self.add_widget(self.container)
        with self.canvas.before:
            Color(*BG_COLOR)
            self._bg = Rectangle(pos=self.pos, size=self.size)
        self.bind(pos=self._upd, size=self._upd)
        
        self.zoom_factor = 1.0
        self._touches = []
        self._last_dist = 0
        self.current_elements = []

    def _upd(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._touches.append(touch)
            if len(self._touches) == 2:
                self._last_dist = Vector(self._touches[0].pos).distance(self._touches[1].pos)
                return True # Consume for pinch
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if len(self._touches) == 2 and touch in self._touches:
            dist = Vector(self._touches[0].pos).distance(self._touches[1].pos)
            if self._last_dist > 0:
                scale = dist / self._last_dist
                new_zoom = self.zoom_factor * scale
                # Clamp zoom between 0.5x and 3.0x
                if 0.5 <= new_zoom <= 3.0:
                    self.zoom_factor = new_zoom
                    self.show_elements(self.current_elements, reset_scroll=False)
            self._last_dist = dist
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        if touch in self._touches:
            self._touches.remove(touch)
        return super().on_touch_up(touch)

    @mainthread
    def show_elements(self, elements, reset_scroll=True):
        self.current_elements = elements
        self.container.clear_widgets()
        if reset_scroll:
            self.scroll_y = 1

        zf = self.zoom_factor

        for el in elements:
            t = el.get("type")

            if t == "blank":
                self.container.add_widget(Widget(size_hint_y=None, height=dp(6)*zf))

            elif t == "divider":
                div_char = el.get("char")
                if div_char:
                    lbl = Label(text=div_char * 40, font_size=sp(12)*zf, halign="left",
                                valign="top", size_hint_y=None, height=dp(18)*zf,
                                color=(0.4, 0.5, 0.6, 1))
                    lbl.bind(width=lambda i,w: setattr(i,"text_size",(w,None)))
                    self.container.add_widget(lbl)
                else:
                    w = Widget(size_hint_y=None, height=dp(1)*zf)
                    with w.canvas.before:
                        Color(0.3, 0.4, 0.5, 1)
                        r = Rectangle(pos=w.pos, size=w.size)
                    w.bind(pos=lambda i,v,_r=r: setattr(_r,"pos",v),
                           size=lambda i,v,_r=r: setattr(_r,"size",v))
                    self.container.add_widget(w)

            elif t == "link":
                btn = LinkButton(label=el["label"], path=el["path"],
                                 node=el.get("node",""), on_tap=self.on_link_tap)
                btn.font_size = sp(14) * zf
                btn.height = dp(34) * zf
                self.container.add_widget(btn)

            elif t == "text":
                heading  = el.get("heading", 0)
                align    = el.get("align", "left")
                segments = el.get("segments", [])

                markup_parts = []
                non_default_bgs = []
                for seg in segments:
                    txt = (seg["text"].replace("&","&amp;")
                                     .replace("[","[[").replace("]","]]"))
                    r,g,b,a = seg["fg"]
                    col = "#{:02x}{:02x}{:02x}".format(int(r*255),int(g*255),int(b*255))
                    p = f"[color={col}]"
                    if seg.get("bold"):      p += "[b]"
                    if seg.get("italic"):    p += "[i]"
                    if seg.get("underline"): p += "[u]"
                    p += txt
                    if seg.get("underline"): p += "[/u]"
                    if seg.get("italic"):    p += "[/i]"
                    if seg.get("bold"):      p += "[/b]"
                    p += "[/color]"
                    markup_parts.append(p)
                    if seg.get("bg") and seg["bg"] != BG_COLOR:
                        non_default_bgs.append(seg["bg"])

                fs_map = {0:sp(14), 1:sp(20), 2:sp(17), 3:sp(15)}
                fs = fs_map.get(heading, sp(14)) * zf
                lbl = Label(text="".join(markup_parts), markup=True,
                            font_size=fs, halign=align, valign="top",
                            size_hint_y=None, color=FG_COLOR)
                lbl.bind(
                    width=lambda i,w: setattr(i,"text_size",(w,None)),
                    texture_size=lambda i,ts: setattr(i,"height",ts[1]+dp(2)))
                lbl.text_size = (self.width - dp(24), None)

                if non_default_bgs:
                    bg = non_default_bgs[0]
                    with lbl.canvas.before:
                        Color(*bg)
                        bgr = Rectangle(pos=lbl.pos, size=lbl.size)
                    lbl.bind(pos=lambda i,v,r=bgr: setattr(r,"pos",v),
                             size=lambda i,v,r=bgr: setattr(r,"size",v))

                self.container.add_widget(lbl)

            elif t == "literal":
                safe = el.get("content","").replace("[","[[").replace("]","]]")
                lbl = Label(text=safe, markup=True, font_size=sp(12)*zf,
                            halign="left", valign="top", size_hint_y=None,
                            color=(0.7,0.7,0.7,1), font_name=FONT_PATH)
                lbl.bind(
                    width=lambda i,w: setattr(i,"text_size",(w,None)),
                    texture_size=lambda i,ts: setattr(i,"height",ts[1]+dp(2)))
                lbl.text_size = (self.width - dp(24), None)
                self.container.add_widget(lbl)

    @mainthread
    def show_status(self, msg, color=FG_COLOR):
        self.container.clear_widgets()
        lbl = Label(text=msg, markup=True, color=color,
                    halign="center", valign="middle", size_hint=(1,1))
        lbl.bind(size=lambda i,_: setattr(i,"text_size",i.size))
        self.container.add_widget(lbl)


class ConfigPopup(ModalView):
    def __init__(self, config_manager, on_save, **kwargs):
        super().__init__(size_hint=(0.9, 0.9), **kwargs)
        self.config_manager = config_manager
        self.on_save = on_save
        
        layout = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(10))
        with layout.canvas.before:
            Color(*BG_COLOR)
            self._bg = Rectangle(pos=layout.pos, size=layout.size)
        layout.bind(pos=self._upd, size=self._upd)
        
        layout.add_widget(Label(text="Configuration", font_size=sp(20), bold=True, size_hint_y=None, height=dp(40)))
        
        # Node Name
        name_layout = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(10))
        name_layout.add_widget(Label(text="Node Name:", size_hint_x=0.3))
        self.name_input = TextInput(text=self.config_manager.config.get("node_name", ""), multiline=False,
                                    background_color=(0.12,0.15,0.20,1), foreground_color=FG_COLOR)
        name_layout.add_widget(self.name_input)
        layout.add_widget(name_layout)
        
        # Default Node
        node_layout = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(10))
        node_layout.add_widget(Label(text="Home Node:", size_hint_x=0.3))
        self.node_input = TextInput(text=self.config_manager.config.get("default_node", ""), multiline=False,
                                    background_color=(0.12,0.15,0.20,1), foreground_color=FG_COLOR)
        node_layout.add_widget(self.node_input)
        layout.add_widget(node_layout)
        
        layout.add_widget(Label(text="Community Hubs", font_size=sp(16), bold=True, size_hint_y=None, height=dp(30)))
        
        # Hubs list
        self.hubs_container = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(5))
        self.hubs_container.bind(minimum_height=self.hubs_container.setter("height"))
        
        scroll = ScrollView()
        scroll.add_widget(self.hubs_container)
        layout.add_widget(scroll)
        
        self.refresh_hubs()
        
        # Buttons
        btn_layout = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(50), spacing=dp(10))
        
        add_btn = Button(text="Add Hub", background_color=BTN_COLOR, background_normal="")
        add_btn.bind(on_release=self.add_hub_dialog)
        
        purge_btn = Button(text="Purge Cache", background_color=(0.6, 0.2, 0.2, 1), background_normal="")
        purge_btn.bind(on_release=self.purge_cache)
        
        save_btn = Button(text="Save & Restart", background_color=(0.2, 0.6, 0.2, 1), background_normal="")
        save_btn.bind(on_release=self.save_config)
        
        close_btn = Button(text="Close", background_color=BTN_COLOR, background_normal="")
        close_btn.bind(on_release=self.dismiss)
        
        btn_layout.add_widget(add_btn)
        btn_layout.add_widget(purge_btn)
        btn_layout.add_widget(save_btn)
        btn_layout.add_widget(close_btn)
        layout.add_widget(btn_layout)
        
        self.add_widget(layout)

    def _upd(self, instance, value):
        self._bg.pos = instance.pos
        self._bg.size = instance.size

    def refresh_hubs(self):
        self.hubs_container.clear_widgets()
        for i, hub in enumerate(self.config_manager.config["hubs"]):
            h_layout = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(5))
            
            host_input = TextInput(text=hub["host"], multiline=False, size_hint_x=0.5,
                                   background_color=(0.12,0.15,0.20,1), foreground_color=FG_COLOR)
            port_input = TextInput(text=str(hub["port"]), multiline=False, size_hint_x=0.2,
                                   background_color=(0.12,0.15,0.20,1), foreground_color=FG_COLOR)
            
            def on_host_change(instance, value, index=i):
                self.config_manager.config["hubs"][index]["host"] = value
            def on_port_change(instance, value, index=i):
                try:
                    self.config_manager.config["hubs"][index]["port"] = int(value)
                except: pass
                
            host_input.bind(text=on_host_change)
            port_input.bind(text=on_port_change)
            
            remove_btn = Button(text="X", size_hint_x=0.1, background_color=(0.6, 0.2, 0.2, 1), background_normal="")
            remove_btn.bind(on_release=lambda btn, index=i: self.remove_hub(index))
            
            h_layout.add_widget(host_input)
            h_layout.add_widget(port_input)
            h_layout.add_widget(remove_btn)
            self.hubs_container.add_widget(h_layout)

    def add_hub_dialog(self, *args):
        self.config_manager.config["hubs"].append({"host": "newhub.org", "port": 4242, "enabled": True})
        self.refresh_hubs()

    def remove_hub(self, index):
        if len(self.config_manager.config["hubs"]) > 1:
            self.config_manager.config["hubs"].pop(index)
            self.refresh_hubs()

    def purge_cache(self, *args):
        if self.config_manager.purge_node_cache():
            app = App.get_running_app()
            if hasattr(app, "_node_drawer"):
                app._node_drawer.clear_nodes()
            self.dismiss()

    def save_config(self, *args):
        self.config_manager.config["node_name"] = self.name_input.text
        self.config_manager.config["default_node"] = self.node_input.text
        self.config_manager.save()
        self.on_save()
        self.dismiss()


# ─── Main App ─────────────────────────────────────────────────────────────────

class RetiBrowserApp(App):
    title = "RetiBrowser – Reticulum Micron Browser"

    def build(self):
        log("build() starting…")
        try:
            Window.clearcolor = BG_COLOR
            self._history, self._hist_pos = [], -1
            
            # Resolve a writable config directory for ConfigManager
            try:
                config_root = self.user_data_dir if (self and self.user_data_dir) else os.path.expanduser("~")
            except Exception:
                config_root = os.path.expanduser("~")
            config_path = os.path.join(config_root, ".reticulum_retibrowser")
            os.makedirs(config_path, exist_ok=True)
            
            self._config_manager = ConfigManager(config_path)
            self._current_node = self._config_manager.config.get("default_node", DEFAULT_NODE)
            self._rns = ReticulumClient(self._config_manager, on_announce_callback=self._on_announce_received)
            self._node_drawer = NodeDrawer(on_node_select=self._navigate_to_node)
            
            # Populate from cache — sort by timestamp so oldest are added first, 
            # and newest end up on top (index=0).
            nodes = self._rns.get_announced_nodes()
            nodes.sort(key=lambda x: x.get("timestamp", 0))
            for node_info in nodes:
                self._node_drawer.add_node(node_info)

            main = BoxLayout(orientation="vertical")
            self._addrbar = AddressBar(on_navigate=self._navigate_url)
            self._addrbar.back_btn.bind(on_press=self._go_back)
            self._addrbar.fwd_btn.bind(on_press=self._go_forward)
            self._addrbar.refresh_btn.bind(on_press=self._refresh)

            # Menu Button with Dropdown
            self._menu_btn = IconButton(text="≡", width=dp(44))
            self._dropdown = DropDown(auto_width=False, width=dp(180))
            
            btn_discovered = Button(text="Discovered Nodes", size_hint_y=None, height=dp(44), 
                                     width=dp(180), size_hint_x=None,
                                     background_color=BTN_COLOR, background_normal="")
            btn_discovered.bind(on_release=lambda btn: self._dropdown.select("discovered"))
            self._dropdown.add_widget(btn_discovered)
            
            btn_config = Button(text="Config", size_hint_y=None, height=dp(44),
                                 width=dp(180), size_hint_x=None,
                                 background_color=BTN_COLOR, background_normal="")
            btn_config.bind(on_release=lambda btn: self._dropdown.select("config"))
            self._dropdown.add_widget(btn_config)
            
            self._menu_btn.bind(on_release=self._dropdown.open)
            self._dropdown.bind(on_select=self._on_menu_select)
            
            self._addrbar.add_widget(self._menu_btn, index=0)

            self._pageview  = PageView(on_link_tap=self._on_link_tap)
            self._statusbar = StatusBar(text="  Initialising Reticulum…")

            main.add_widget(self._addrbar)
            main.add_widget(self._pageview)
            main.add_widget(self._statusbar)

            self._nav_drawer = NavigationDrawer(content=main, drawer=self._node_drawer)
            Clock.schedule_once(self._init_rns_main, 0.5)
            log("build() complete")
            return self._nav_drawer
        except Exception as e:
            log(f"build error: {e}\n{traceback.format_exc()}")
            raise

    def _on_menu_select(self, instance, value):
        if value == "discovered":
            self._nav_drawer.toggle_drawer()
        elif value == "config":
            self._show_config()

    def _show_config(self):
        p = ConfigPopup(self._config_manager, on_save=self._restart_rns)
        p.open()

    def _restart_rns(self):
        log("Restarting Reticulum due to config change...")
        # In a real app, full restart might be complex. Here we'll try to re-init.
        # RNS doesn't like being re-initialized in the same process well, 
        # but we'll try to re-run start() which overwrites the config file.
        # For a true restart, one might need to restart the whole process.
        self._set_status("Config saved. Please restart app for changes to take effect.")
        # Alternatively, we can try to re-start the client, but RNS instances are sticky.
        # self._init_rns_main()

    # ── Reticulum init ────────────────────────────────────────────────────────

    def _init_rns_main(self, dt=None):
        try:
            log("Starting Reticulum…")
            hubs_str = ", ".join([f"{h['host']}:{h['port']}" for h in self._config_manager.config["hubs"] if h.get("enabled", True)])
            self._set_status(f"Connecting to {hubs_str}…")
            self._rns.start()
            log("Reticulum started")
            threading.Thread(target=self._begin_iface_poll, daemon=True).start()
        except Exception as e:
            log(f"Init error: {e}\n{traceback.format_exc()}")
            self._set_status(f"Init error: {e}")
            self._pageview.show_status(
                f"[color=#ff5555]Failed to start Reticulum:\n{e}[/color]",
                color=(1,0.33,0.33,1))

    def _begin_iface_poll(self):
        """Schedule the interface poll from a thread (Clock is thread-safe)."""
        self._iface_wait_start = time.time()
        Clock.schedule_interval(self._wait_for_interface, 0.25)

    def _wait_for_interface(self, dt):
        elapsed = time.time() - self._iface_wait_start
        interfaces = getattr(RNS.Transport, "interfaces", [])

        connected = [
            i for i in interfaces
            if getattr(i, "online", False) and getattr(i, "rxb", 0) > 0
        ]

        if connected:
            names = ", ".join(getattr(i,"name","?") for i in connected)
            log(f"Hub connected after {elapsed:.1f}s: {names}")
            self._set_status("Connected — loading page…")
            Clock.unschedule(self._wait_for_interface)
            self._do_initial_load()
            return False

        if elapsed > 30:
            log("Hub never connected after 30s")
            Clock.unschedule(self._wait_for_interface)
            self._set_status("Connection failed — check network")
            self._pageview.show_status(
                f"[color=#ff5555]Could not connect to configured hubs after 30s[/color]\n\n"
                f"[color=#aaaaaa]The hubs may be down or unreachable.\n"
                f"Check your internet connection.[/color]",
                color=(1,0.33,0.33,1))
            return False

        if int(elapsed) % 2 == 0 and elapsed > 0:
            self._set_status(f"Connecting to hubs… ({int(elapsed)}s)")

    def _do_initial_load(self, dt=None):
        try:
            self._load_page(self._current_node, DEFAULT_PAGE, push_history=True)
        except Exception as e:
            log(f"Initial load error: {e}")
            self._set_status(f"Load error: {e}")

    # ── Announce ──────────────────────────────────────────────────────────────

    def _on_announce_received(self, node_info):
        log(f"Announce: {node_info.get('name','?')} ({node_info.get('hash','')[:8]}…)")
        self._node_drawer.add_node(node_info)

    def _navigate_to_node(self, node_hash):
        self._load_page(node_hash, DEFAULT_PAGE, push_history=True)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _navigate_url(self, url):
        url = url.strip()
        if ":" in url and not url.startswith("/"):
            node, path = url.split(":", 1)
        elif url.startswith("/"):
            node, path = self._current_node, url
        else:
            node, path = url, DEFAULT_PAGE
        self._load_page(node.strip(), path.strip(), push_history=True)

    def _on_link_tap(self, node_hex, page_path):
        self._load_page(node_hex or self._current_node, page_path, push_history=True)

    def _go_back(self, *_):
        if self._hist_pos > 0:
            self._hist_pos -= 1
            n, p = self._history[self._hist_pos]
            self._load_page(n, p, push_history=False)

    def _go_forward(self, *_):
        if self._hist_pos < len(self._history) - 1:
            self._hist_pos += 1
            n, p = self._history[self._hist_pos]
            self._load_page(n, p, push_history=False)

    def _refresh(self, *_):
        if self._history:
            n, p = self._history[self._hist_pos]
            self._load_page(n, p, push_history=False)

    # ── Page loading ──────────────────────────────────────────────────────────

    def _load_page(self, node_hex, page_path, push_history=True):
        node_hex  = node_hex.strip().lower()
        page_path = page_path.strip()

        # Handle relative paths (no leading slash)
        if not page_path.startswith("/"):
            # Resolve relative to current directory if same node
            current_path = ""
            if self._history and self._hist_pos >= 0:
                cur_node, cur_path = self._history[self._hist_pos]
                if cur_node == node_hex:
                    current_path = cur_path
            
            if current_path:
                dir_path = "/".join(current_path.split("/")[:-1])
                if not dir_path.endswith("/"):
                    dir_path += "/"
                page_path = dir_path + page_path
            else:
                # Default to /page/ if no history or different node
                page_path = "/page/" + page_path

        # Normalize path (handle .. and . segments)
        parts = []
        for p in page_path.split("/"):
            if p == "..":
                if parts: parts.pop()
            elif p == "." or not p:
                continue
            else:
                parts.append(p)
        page_path = "/" + "/".join(parts)
        
        self._current_node = node_hex
        Clock.schedule_once(lambda *_: self._addrbar.set_url(f"{node_hex}:{page_path}"), 0)

        if push_history:
            self._history = self._history[:self._hist_pos+1]
            self._history.append((node_hex, page_path))
            self._hist_pos = len(self._history) - 1

        self._update_nav_buttons()
        self._set_status(f"Fetching {page_path} from {node_hex[:8]}…")
        self._pageview.show_status("[color=#aaaaaa]Loading…[/color]")
        self._rns.fetch_page(node_hex, page_path,
                             on_done=self._on_page_done,
                             on_error=self._on_page_error,
                             on_progress=self._on_progress)

    @mainthread
    def _update_nav_buttons(self):
        self._addrbar.back_btn.background_color = \
            BTN_COLOR if self._hist_pos > 0 else (0.08,0.10,0.14,1)
        self._addrbar.fwd_btn.background_color = \
            BTN_COLOR if self._hist_pos < len(self._history)-1 else (0.08,0.10,0.14,1)

    def _on_progress(self, msg):
        self._set_status(f"Downloading… {msg}%" if isinstance(msg, int) else str(msg))

    def _on_page_done(self, content):
        self._set_status("Page loaded")
        self._pageview.show_elements(parse_micron(content))

    def _on_page_error(self, msg):
        self._set_status(f"Error: {msg[:80]}")
        self._pageview.show_status(
            f"[color=#ff5555]{msg}[/color]\n\n"
            "[color=#888888]Check connection and node address.[/color]",
            color=(1,0.33,0.33,1))

    @mainthread
    def _set_status(self, msg):
        self._statusbar.text = f"  {msg}"

    def on_stop(self):
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
