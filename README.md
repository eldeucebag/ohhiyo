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
3. The app automatically connects to `rns.noderage.org:4242`
4. Wait for the server's announce to propagate (usually a few seconds)
5. Enter the destination hash to browse pages:
   ```
   <f97f412b9ef6d1c2330ca5ee28ee9e31>
   ```

## Navigation

- **Back/Forward**: Navigate browsing history
- **Refresh**: Reload current page
- **Address bar**: Enter destination hash or full URL
  - `<hash>:/page/index.mu` - Specific page
  - `<hash>` - Loads default index page

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

The browser renders Micron markup with support for:

- **Bold**: `` `!text`! ``
- *Italic*: `` `*text`* ``
- <u>Underline</u>: `` `_text`_ ``
- Colors: `` `F00fred`f `` (foreground), `` `B00fbackground`b ``
- Links: `` `[Label`/page/path.mu] ``
- Headings: `>H1`, `>>H2`, `>>>H3`

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
