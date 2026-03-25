#!/bin/bash
sudo apt-get update
sudo apt-get install -y python3-pip
pip3 install --user yfinance playwright feedparser requests beautifulsoup4
playwright install chromium
playwright install-deps chromium
