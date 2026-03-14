[app]
title = RetiBrowser
package.name = retibrowser
package.domain = org.retibrowser

source.dir = .
source.include_exts = py,png,jpg,kv,atlas

version = 1.0.0

requirements = python3,kivy==2.3.0,rns,cryptography

# Orientation – portrait by default, can rotate to landscape
orientation = portrait
fullscreen = 0

android.permissions = INTERNET, ACCESS_NETWORK_STATE
android.api = 33
android.minapi = 21
android.ndk = 25.2.9519653
android.sdk = 33

android.archs = arm64-v8a, armeabi-v7a

# App icon (place a 512x512 PNG at this path)
# icon.filename = %(source.dir)s/icon.png

[buildozer]
log_level = 2
warn_on_root = 1
build_dir = .buildozer
clean = 0
