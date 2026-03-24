[app]
title = ohhiyo
package.name = ohhiyo
package.domain = org.ohhiyo

source.dir = .
source.include_exts = py,png,jpg,kv,atlas,xml,ttf

version = 1.0.0

requirements = python3,kivy==2.2.1,rns>=0.6.0,cryptography==41.0.7,netifaces,pyserial,pyopenssl,setuptools,urllib3>=2.0.0,requests>=2.31.0,chardet>=5.0.0,idna>=3.4,certifi>=2023.0.0,libbz2,liblzma,sqlite3
# Orientation – portrait by default, can rotate to landscape
orientation = all
fullscreen = 0

android.permissions = INTERNET, ACCESS_NETWORK_STATE, ACCESS_WIFI_STATE, CHANGE_WIFI_STATE, CHANGE_NETWORK_STATE, WAKE_LOCK, FOREGROUND_SERVICE
android.manifest.activity_attributes = android:hardwareAccelerated="true"

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
