# RetiBrowser - RNS Micron Browser for Android

A Kivy-based Reticulum NomadNet Micron Browser for Android devices.

Connects to RNS Page Nodes via the **Noderage Community Hub** (`rns.noderage.org:4242`).

## Requirements

- Android device
- Python 3.7+ (for building)
- Kivy
- Reticulum Network Stack (`rns`)

## Building for Android

```bash
# Install dependencies
pip install kivy rns buildozer

# Build APK
cd browser/
buildozer android debug

# The APK will be in bin/
```

## Configuration

The app connects to the Noderage Community Hub by default. Edit `main.py` if needed:

```python
# Noderage Community Hub - public Reticulum transport relay
NODERAGE_HOST = "rns.noderage.org"
NODERAGE_PORT = 4242
```

## Usage

1. Ensure your RNS Page Node server is running and connected to Noderage
2. Open the RetiBrowser app on your Android device
3. The app automatically connects to `rns.noderage.org:4242` and sends an announce
4. Wait for the server's announce to propagate (usually a few seconds)
5. Enter the destination hash to browse pages:
   ```
   <f97f412b9ef6d1c2330ca5ee28ee9e31>
   ```

## Navigation

- **Menu button (☰)**: Open node discovery drawer
- **Back/Forward**: Navigate browsing history
- **Refresh**: Reload current page
- **Address bar**: Enter destination hash or full URL
  - `<hash>:/page/index.mu` - Specific page
  - `<hash>` - Loads default index page

## Node Discovery

**Swipe right from the left edge** or tap the **☰ menu button** to open the node discovery drawer.

The drawer shows:
- All nodes that have sent announces on the network
- Node names and destination hashes
- Quick "Navigate" buttons to browse each node

The app automatically:
- Sends an announce when connecting to the hub
- Listens for announces from other nodes
- Maintains a list of discovered nodes

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│  RetiBrowser │────▶│  Noderage Hub    │◀────│  Page Node  │
│  (Android)   │     │  rns.noderage.org│     │  (server)   │
└──────────────┘     └──────────────────┘     └─────────────┘
   TCP client            Public relay          TCP client
```

Both the browser and page node connect outbound to the Noderage hub, avoiding NAT/firewall issues.

## Micron Markup

The browser fully implements Reticulum's Micron markup language with support for:

### Text Formatting
- **Bold**: `` `!text`! ``
- *Italic*: `` `*text`* ``
- <u>Underline</u>: `` `_text`_ ``
- **Combined**: `` `!`*bold italic`*`! ``

### Colors
- Foreground: `` `F00fred text`f `` (3-digit hex: 000-fff)
- Background: `` `B00fbackground`b `` (3-digit hex)
- Grayscale: `` `g80gray text `` (2-digit hex: 00-ff)

### Alignment
- Center: `` `cCentered text ``
- Left: `` `lLeft aligned ``
- Right: `` `rRight aligned ``
- Reset: `` `aReset to left ``

### Links
- Standard: `` `[Link Label`/page/path.mu] ``
- With node: `` `[Remote Page`abc123:/page/index.mu] ``
- Path as label: `` `[/page/path.mu`/page/path.mu] ``

### Headings
- Level 1: `>Heading 1<`
- Level 2: `>>Heading 2<`
- Level 3: `>>>Heading 3<`
- Reset depth: `<` (on its own line)

### Other Elements
- Dividers: `---` or `` `-` ``
- Comments: `# Comment text` (not rendered)
- Cache header: `#!c=3600` (first line, sets cache time)
- Literal mode: `` `=Raw text with `!formatting`!= `` (preserves formatting codes)
- Escape: `` \` `` (literal backtick)
- Reset all: `` `` `` (resets all formatting)

## Troubleshooting

**"Path not found" error:**
- Ensure both your server and phone are connected to the internet
- Check that your server is connected to Noderage (check server logs)
- Wait for the server's announce to propagate (can take up to 30 minutes)
- Verify the destination hash is correct

**"Identity not received" error:**
- The server may not be announcing properly
- Check server logs for "Sent announce" messages
- Wait longer for announces to propagate through the hub

**Connection timeout:**
- Check your internet connection
- Verify Noderage hub is reachable: `telnet rns.noderage.org 4242`

## License

MIT License
