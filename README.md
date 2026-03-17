# RetiBrowser - RNS Micron Browser for Android

A Kivy-based Reticulum NomadNet Micron Browser for Android devices.

Connects to RNS Page Nodes over TCP/IP and renders Micron markup pages.

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

Edit `main.py` to configure your server connection:

```python
# Server configuration - update SERVER_HOST to your server's public IP
SERVER_HOST = "167.100.58.227"  # Your server's public IP address
SERVER_PORT = 4965              # RNS TCP port
```

## Usage

1. Ensure the RNS Page Node server is running
2. Open the RetiBrowser app on your Android device
3. The app will automatically connect to the configured server
4. Enter a destination hash to browse pages:
   ```
   <f97f412b9ef6d1c2330ca5ee28ee9e31>
   ```

## Navigation

- **Back/Forward**: Navigate browsing history
- **Refresh**: Reload current page
- **Address bar**: Enter destination hash or full URL
  - `<hash>:/page/index.mu` - Specific page
  - `<hash>` - Loads default index page

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
- Ensure the server is running (`./start-page-node.sh`)
- Check that port 4965 is open on the server firewall
- Verify SERVER_HOST in main.py matches your server's public IP

**"Identity not received" error:**
- The server may not be announcing properly
- Check server logs for "Sent announce" messages

**Connection timeout:**
- Verify network connectivity between Android device and server
- Check that rnsd is running on the server

## License

MIT License
