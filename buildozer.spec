[app]
title = Liquidation Lab
package.name = liquidationlab
package.domain = org.liquidationlab.edu
source.dir = .
source.include_exts = py,kv,png,jpg,json,csv,ttf,md
source.exclude_dirs = tests,__pycache__,.venv,bin
version = 0.3.0
requirements = python3,kivy
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.minapi = 24
android.api = 35
# Internet used for PUBLIC Bybit OHLC fetch only, never for submitting orders.

[buildozer]
log_level = 2
warn_on_root = 1
