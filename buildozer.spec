[app]
title = RetiBrowser
package.name = retibrowser
package.domain = org.retibrowser

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,xml,ttf

version = 1.0.0

requirements = python3,kivy==2.2.1,rns,cryptography,urllib3,requests,chardet,idna,certifi,libbz2,liblzma,sqlite3
# Orientation – portrait by default, can rotate to landscape
orientation = portrait
fullscreen = 0

android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, CHANGE_WIFI_STATE, CHANGE_NETWORK_STATE, WAKE_LOCK, FOREGROUND_SERVICE
android.manifest.activity_attributes = android:hardwareAccelerated="false"

# RNS encrypts all traffic at the application layer so cleartext rules
# do not apply. Removed networkSecurityConfig reference — the xml file
# was never included in source.include_exts, causing install failures.
android.manifest.application_attributes = android:usesCleartextTraffic="true"

android.api = 33
android.minapi = 21
android.ndk = 25.2.9519653
android.sdk = 33
android.accept_sdk_license = True

android.archs = arm64-v8a, armeabi-v7a

# Enable SDL2 bootstrap for better compatibility
p4a.bootstrap = sdl2

# App icon (place a 512x512 PNG at this path)
# icon.filename = %(source.dir)s/icon.png

[buildozer]
log_level = 2
warn_on_root = 1
build_dir = .buildozer
clean = 0
