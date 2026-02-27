# WONE — Race Results CSV Scraper

A Python agent that extracts race results from Indian endurance sports timing platforms into clean CSV files.

## The Problem

Indian race results live across a fragmented ecosystem of timing vendors. Each is a client-side rendered SPA that loads data via internal APIs. You can't just `curl` the page and parse HTML. You need a headless browser to intercept the actual data.

## How It Works

```
Race Name → Google Search → Platform Detection → Headless Browser → API Interception → CSV
```

Three-phase architecture:

| Phase | What Happens | How |
|-------|-------------|-----|
| **Discovery** | Find the results URL | Google search with platform-aware filtering |
| **Interception** | Capture the data API calls | Playwright loads the SPA, intercepts JSON responses |
| **Extraction** | Normalize and export | Field mapping, deduplication, CSV output |

The key insight: instead of scraping HTML (which is templated Vue/React), we intercept the underlying JSON API calls that the frontend makes. This gives us structured data without fragile CSS selector dependencies.

## Supported Platforms

| Platform | Domain | Used By |
|----------|--------|---------|
| **MySamay** | mysamay.in | NEB Sports (Bengaluru 10K Challenge, etc.) |
| **Sports Timing Solutions** | sportstimingsolutions.in | Procam (TCS World 10K, Mumbai Marathon) |
| **Timing India** | timingindia.com | Various regional events |
| **Race Result** | my.raceresult.com | International + some Indian events |

## Setup

```bash
# Clone or download this directory, then:
chmod +x setup.sh
./setup.sh

# Or manually:
pip install -r requirements.txt
playwright install chromium
```

## Usage

### Basic: Search by race name
```bash
python scraper.py "2025 Bengaluru 10K Challenge"
```

### Direct URL (skip search)
```bash
python scraper.py --url "https://mysamay.in/race/results/2f9d04d2-4750-4736-881b-dbc8227ce941"
python scraper.py --url "https://sportstimingsolutions.in/results?q=eyJlX25hbWUiOiJUQ1MgV29ybGQgMTBLIEJlbmdhbHVydSAyMDI1IiwiZV9pZCI6ODU5NTF9"
```

### Custom output path
```bash
python scraper.py "TCS World 10K 2025" --output tcs_10k_results.csv
```

### Debug mode (inspect API calls)
```bash
python scraper.py --url "https://mysamay.in/race/results/..." --debug
```

Debug mode shows all JSON API calls the page makes without extracting data. Use this to understand a new platform's API structure before adding support.

## Output Format

The CSV uses normalized column names regardless of source platform:

| Column | Description |
|--------|-------------|
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

## Adding a New Platform

1. Run `--debug` on a results URL from the new platform
2. Identify the JSON API endpoint(s) that return results data
3. Add the domain to `PLATFORMS` dict in `scraper.py`
4. If the API response structure differs significantly, add a platform-specific extractor function
5. Update `platforms.json` with the discovered endpoint patterns

The generic extractor (`extract_generic_data`) handles most cases automatically by scoring JSON arrays for "results-like" field names.

## Known Limitations

- **Pagination**: Some platforms paginate results (50-100 per page). The agent attempts to trigger pagination by clicking "Load More" buttons and scrolling, but may not capture all pages for very large events (10K+ runners).
- **Authentication**: Some platforms require login to view full results. Not supported.
- **Category selection**: Platforms like STS require selecting a race category before showing results. The agent tries to select "All" but may need manual URL crafting.
- **Rate limiting**: Google search may block automated queries. Use `--url` for direct access.

## Architecture Notes for WONE Integration

This scraper is a standalone tool, but the extraction logic maps directly to WONE's data model:

- `bib` + `race_name` + `date` = unique race participation record
- `full_name` + `club` = identity enrichment for athlete profiles  
- `chip_time` + `pace` + `overall_rank` = performance credentials
- The `platforms.json` config can evolve into a platform registry service

The field normalization layer (`FIELD_MAP` + `normalize_result_row`) ensures consistent data regardless of which timing vendor hosted the race. This is the "identity is portable" principle applied to race data.
