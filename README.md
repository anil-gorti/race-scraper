# Race Results Scraper

> A Python agent that discovers race results pages, intercepts SPA API calls via headless browser, and exports structured CSVs — works across any timing platform.

[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://python.org)
[![Playwright](https://img.shields.io/badge/playwright-headless-green)](https://playwright.dev)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## The Problem

Race results live across a fragmented ecosystem of timing vendors. Each one is a client-side rendered SPA that loads data via internal APIs — you can't just `curl` the page and parse HTML. You need a headless browser to intercept the actual data.

This tool solves it with a three-phase agent:

```
Race Name → Google Search → Platform Detection → Headless Browser → API Interception → CSV
```

---

## How It Works

| Phase | What Happens | How |
|---|---|---|
| **Discovery** | Find the results URL | Google search with platform-aware filtering |
| **Interception** | Capture the data API calls | Playwright loads the SPA, intercepts JSON responses |
| **Extraction** | Normalize and export | Field mapping, deduplication, CSV output |

**The key insight:** instead of scraping HTML (templated Vue/React), we intercept the underlying JSON API calls that the frontend makes. This gives us structured data without fragile CSS selector dependencies.

---

## Supported Platforms

| Platform | Domain | Example Events |
|---|---|---|
| **MySamay** | mysamay.in | NEB Sports events (Bengaluru 10K, etc.) |
| **Sports Timing Solutions** | sportstimingsolutions.in | Procam events (TCS World 10K, Mumbai Marathon) |
| **Timing India** | timingindia.com | Various regional events |
| **Race Result** | my.raceresult.com | International + regional events |
| **Runners Quest** | runners.quest | Club and community runs |

> Platforms are defined in `platforms.json` — extending to a new platform takes ~15 minutes.

---

## Setup

```bash
# Clone the repo, then:
chmod +x setup.sh
./setup.sh

# Or manually:
pip install -r requirements.txt
playwright install chromium
```

---

## Usage

### Search by race name
```bash
python scraper.py "2025 City Marathon"
```

### Direct URL (skip search)
```bash
python scraper.py --url "https://mysamay.in/race/results/RACE-ID"
python scraper.py --url "https://sportstimingsolutions.in/results?q=..."
```

### Custom output path
```bash
python scraper.py "City Marathon 2025" --output marathon_results.csv
```

### Debug mode (inspect captured API calls)
```bash
python scraper.py --url "https://timing-platform.com/results/..." --debug
```

Debug mode prints every JSON response the page makes — use this to understand a new platform's API structure before adding support for it.

---

## Output Format

The CSV uses **normalized column names** regardless of source platform:

| Column | Description |
|---|---|
| `bib` | Race bib number |
| `full_name` | Runner's full name |
| `first_name` | First name (if available separately) |
| `last_name` | Last name (if available separately) |
| `gender` | M/F |
| `age_group` | Age category |
| `category` | Race category (e.g., "Open 10K", "Elite") |
| `club` | Running club / team |
| `chip_time` | Net / chip finish time |
| `gun_time` | Gun / gross finish time |
| `pace` | Average pace (min/km) |
| `overall_rank` | Overall position |
| `category_rank` | Category position |
| `gender_rank` | Gender position |

---

## Adding a New Platform

1. Run `--debug` on a results URL from the new platform
2. Identify the JSON API endpoint(s) that return results data
3. Add the domain to `PLATFORMS` dict in `scraper.py`
4. If the API response structure differs, add a platform-specific extractor function
5. Update `platforms.json` with the discovered endpoint patterns

The generic extractor (`extract_generic_data`) handles most cases automatically by scoring JSON arrays for "results-like" field names — you may not need a custom extractor at all.

---

## Architecture

```
scraper.py
├── discover_results_url()   # Phase 1: Google search + platform detection
├── intercept_api_data()     # Phase 2: Playwright headless browser + response capture
│   ├── extract_sts_data()   # Platform-specific extractors
│   ├── extract_mysamay_data()
│   └── extract_generic_data()  # Fallback: scores JSON arrays for result-like fields
├── scrape_dom_table()       # Final fallback: HTML table parsing
└── write_csv()              # Phase 3: Normalize fields + write CSV
```

**Field normalization** (`FIELD_MAP` + `normalize_result_row`) maps each platform's raw API field names to a canonical schema — so downstream consumers always see the same column names regardless of which timing vendor hosted the race.

---

## Known Limitations

- **Pagination**: Some platforms paginate results (50–100 per page). The agent attempts to trigger pagination by clicking "Load More" and scrolling, but may miss pages for very large events (10K+ runners).
- **Authentication**: Some platforms require login to view full results. Not supported.
- **Category selection**: Platforms like STS require selecting a race category before showing results. The agent tries to select "All" but may need manual URL crafting.
- **Rate limiting**: Google search may throttle automated queries. Use `--url` for direct access.

---

## Requirements

- Python 3.9+
- [Playwright](https://playwright.dev/python/) + Chromium
- See `requirements.txt` for full list

---

## License

MIT
