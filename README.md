# ohhiyo – Reticulum Micron Browser for Android

A modern Kivy-based Reticulum NomadNet Micron Browser for Android devices.

Connects to multiple RNS Community Hubs and Page Nodes simultaneously, with full Micron markup rendering and node discovery.

## Features

- **Multi-Hub Support**: Connects to multiple community hubs by default (SPAGOnet, MichMesh, ChicagoNomad)
- **Node Discovery**: Automatically discovers and caches announced nodes on the network
- **Full Micron Support**: Complete implementation of Reticulum's Micron markup language
- **Pinch-to-Zoom**: Zoom pages from 0.5x to 3.0x with two-finger gestures
- **Swipe Navigation**: Open node drawer with right-swipe from left edge (Android)
- **Modern UI**: Dark theme with Material Design icons and emoji support
- **Offline Caching**: Caches discovered nodes and their identities for faster access

## Requirements

- Android device (API 21+)
- Python 3.7+ (for building)
- Kivy 2.2.1
- Reticulum Network Stack (`rns>=0.6.0`)

## Building for Android

```bash
# Install dependencies
pip install kivy==2.2.1 rns>=0.6.0 buildozer

# Build APK
cd browser/
buildozer android debug

# The APK will be in bin/
```

## Configuration

The app connects to these hubs by default:
- `rns.chicagonomad.net:4242` (ChicagoNomad)
- `rns.pawgslayers.club:4242` (SPAGOnet Backbone)
- `rns.michmesh.net:7822` (MichMesh Backbone)

Open the **Config** menu to:
- Change your **Node Name**
- Set a **Home Node** (default destination)
- Add, edit, or remove community hubs
- Purge the node cache

## Usage

1. Open ohhiyo on your Android device
2. Wait for connection to community hubs (~5-30 seconds)
3. The app will automatically load your configured home node
4. Browse nodes using:
   - **Address bar**: Enter destination hash or full URL
   - **Discovered Nodes**: View all announced nodes with quick "Go" buttons
   - **Navigation links**: Tap links within pages

### Address Bar Formats

```
<f97f412b9ef6d1c2330ca5ee28ee9e31>          # Node hash only (loads /page/index.mu)
<f97f412b9ef6d1c2330ca5ee28ee9e31>:/page/about.mu  # Specific page
/page/about.mu                              # Path on current node
```

## Navigation

| Control | Action |
|---------|--------|
| **≡ Menu** | Opens dropdown: Discovered Nodes, Config |
| **←/→** | Navigate browsing history |
| **↻ Refresh** | Reload current page |
| **Right swipe** (from left edge) | Open node discovery drawer |
| **Left swipe** (when drawer open) | Close drawer |
| **Pinch** | Zoom in/out (0.5x – 3.0x) |
| **Tap outside drawer** | Close drawer |

## Node Discovery

Access via **Menu → Discovered Nodes** or **swipe right from left edge**.

The drawer displays:
- All nodes that have sent announces on the network
- Node names with capability indicators (🌐 pages, ✉ LXMF)
- Destination hashes (truncated)
- Quick "Go →" buttons for instant navigation

Nodes are cached between sessions for faster access.

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│   ohhiyo     │────▶│  Community Hubs  │◀────│  Page Node  │
│  (Android)   │     │ (TCP Interfaces) │     │  (server)   │
└──────────────┘     └──────────────────┘     └─────────────┘
   TCP client            Public relay          TCP client
```

Both ohhiyo and page nodes connect outbound to community hubs, avoiding NAT/firewall issues. Announces propagate through the hub network, enabling peer discovery without direct connections.

## Micron Markup

ohhiyo fully implements Reticulum's Micron markup language:

### Text Formatting
| Style | Syntax |
|-------|--------|
| **Bold** | `` `!text`! `` |
| *Italic* | `` `*text`* `` |
| <u>Underline</u> | `` `_text`_ `` |
| **Bold + Italic** | `` `!`*combined`*`! `` |

### Colors
| Type | Syntax | Example |
|------|--------|---------|
| Foreground | `` `Fxxx...`f `` | `` `Ff00red text`f `` |
| Background | `` `Bxxx...`b `` | `` `B00fblue bg`b `` |
| Grayscale | `` `gXXtext `` | `` `g80gray text `` |

*Use 3-digit hex (000-fff) for colors, 2-digit hex (00-ff) for grayscale.*

### Alignment
| Alignment | Syntax |
|-----------|--------|
| Center | `` `cCentered text `` |
| Left | `` `lLeft aligned `` |
| Right | `` `rRight aligned `` |
| Reset | `` `aReset to default `` |

### Links
```
`[Link Label`/page/path.mu]           # Local page
`[Remote Page`abc123:/page/index.mu]  # Remote node
`[/page/path.mu`/page/path.mu]        # Path as label
```

### Headings
```
>Heading 1<       # Level 1 (largest)
>>Heading 2<      # Level 2
>>>Heading 3<     # Level 3
<                 # Reset heading depth
```

### Other Elements
| Element | Syntax |
|---------|--------|
| Divider | `---` or `` `-` `` |
| Comment | `# Comment text` (not rendered) |
| Cache header | `#!c=3600` (first line only) |
| Literal mode | `` `=Raw `!formatting`= `` |
| Escape backtick | `` \` `` |
| Reset all | `` `` `` |

## Troubleshooting

### "Path not found" or "Identity not received"
- Ensure the page node is running and connected to a hub
- Wait for announces to propagate (up to 30 minutes on sparse networks)
- Check that you're connected to the same hub as the page node
- Verify the destination hash is correct

### "Connection timeout" or hub connection failures
- Check your internet connection
- Verify the community hub is reachable
- Try purging the node cache (Config → Purge Cache)

### App shows "Could not connect to hubs"
- The configured hubs may be temporarily offline
- Check hub status on RNS community channels
- Add alternative hubs in Config

### Nodes not appearing in discovery
- Wait longer for announces to propagate
- The node may not be announcing properly
- Check server logs for "Sent announce" messages

## Project Structure

```
browser/
├── main.py              # Main application (Kivy app, RNS client, UI)
├── MicronParser.py      # Standalone Micron parser (reference)
├── test_micron_parser.py # Unit tests for Micron parser
├── buildozer.spec       # Buildozer configuration for Android
├── requirements.txt     # Python dependencies
├── files/               # Bundled fonts
│   ├── JetBrainsMonoNerdFont.ttf
│   ├── ShureTechMonoNerdFontMono-Regular.ttf
│   ├── MaterialIcons-Regular.ttf
│   └── Twemoji.Mozilla.ttf
└── pages/               # (Optional) Local pages
```

## Default Configuration

The app stores configuration in `~/.reticulum_ohhiyo/`:
- `config` – Reticulum network configuration
- `identity` – Persistent RNS identity
- `ohhiyo_config.json` – App settings (hubs, node name, home node)
- `node_cache.json` – Cached discovered nodes

## License

MIT License

## Acknowledgments

- [Reticulum Network Stack](https://reticulum.network/)
- [NomadNet](https://github.com/markqvist/NomadNet)
- [Kivy](https://kivy.org/)
- Fonts: JetBrains Mono Nerd Font, Shure Tech Mono, Material Icons, Twemoji
