# RetiBrowser - RNS Micron Browser for Android

A Kivy-based Reticulum NomadNet Micron Browser for Android devices.

Connects to RNS Page Nodes via a **Community Hub** (`rns.chicagonomad.net:4242` by default).

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

The app connects to `rns.chicagonomad.net:4242` by default. You can add more hubs or change the default one in the **Config** menu within the app.

You can also set your **Node Name** in the configuration window.

## Usage

1. Open the RetiBrowser app on your Android device
2. The app connects to the configured hubs and listens for announces
3. Wait for the server's announce to propagate (usually a few seconds)
4. Enter the destination hash to browse pages:
   ```
   <f97f412b9ef6d1c2330ca5ee28ee9e31>
   ```

## Navigation

- **Menu button (≡)**: Opens a dropdown menu with:
  - **Discovered Nodes**: Shows the node discovery drawer
  - **Config**: Opens the configuration window
- **Back/Forward**: Navigate browsing history
- **Refresh**: Reload current page
- **Address bar**: Enter destination hash or full URL
  - `<hash>:/page/index.mu` - Specific page
  - `<hash>` - Loads default index page

## Node Discovery

Select **Discovered Nodes** from the menu or **swipe right from the left edge** to open the node discovery drawer.

The drawer shows:
- All nodes that have sent announces on the network
- Node names and destination hashes
- Quick "Go →" buttons to browse each node

## Architecture

```
┌──────────────┐     ┌──────────────────┐     ┌─────────────┐
│  RetiBrowser │────▶│  Community Hub   │◀────│  Page Node  │
│  (Android)   │     │ (TCP Interface)  │     │  (server)   │
└──────────────┘     └──────────────────┘     └─────────────┘
   TCP client            Public relay          TCP client
```

Both the browser and page node connect outbound to the hub, avoiding NAT/firewall issues.

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
- Check that your server is connected to the same hub as your phone
- Wait for the server's announce to propagate (can take up to 30 minutes)
- Verify the destination hash is correct

**"Identity not received" error:**
- The server may not be announcing properly
- Check server logs for "Sent announce" messages
- Wait longer for announces to propagate through the hub

**Connection timeout:**
- Check your internet connection
- Verify the community hub is reachable

## License

MIT License
