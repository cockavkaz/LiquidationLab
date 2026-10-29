[app]
title = Liquidation Lab
package.name = liquidationlab
package.domain = org.liquidationlab.edu
source.dir = .
source.include_exts = py,kv,png,jpg,json,csv,ttf,md
source.exclude_dirs = tests,__pycache__,.venv,bin
version = 0.2.0
requirements = python3,kivy
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.minapi = 24
android.api = 35
# Explicitly accept Android SDK licenses in non-interactive CI.
android.accept_sdk_license = True
# python-for-android's master currently has a broken temporary pip venv.
# The develop branch includes upstream PR #3360 fixing this failure.
# Pin the merged upstream commit for reproducible Android builds.
p4a.branch = develop
p4a.commit = 0382d27de2f7315ed98e74884bafb30365decdee

[buildozer]
log_level = 2
warn_on_root = 1
