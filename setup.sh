#!/bin/bash
# Race Results Scraper - Setup Script
# Run this once to install dependencies

echo "Installing Python dependencies..."
pip install -r requirements.txt

echo "Installing Playwright browsers..."
playwright install chromium

echo ""
echo "Setup complete. Usage:"
echo "  python scraper.py \"2025 Bengaluru 10K Challenge\""
echo "  python scraper.py --url \"https://mysamay.in/race/results/...\""
echo "  python scraper.py --url \"https://sportstimingsolutions.in/results?q=...\" --debug"
