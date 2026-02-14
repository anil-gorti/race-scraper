#!/usr/bin/env python3
"""
Race Results Scraper Agent for Indian Endurance Sports
======================================================
Given a race name (e.g., "2025 Bengaluru 10K Challenge"), this agent:
1. Searches for the results URL
2. Detects the timing platform
3. Intercepts API calls to extract structured data
4. Outputs a clean CSV

Supported platforms:
- MySamay.in (NEB Sports events)
- SportsTimingSolutions.in (Procam / TCS events)
- TimingIndia.com
- my.raceresult.com

Usage:
    python scraper.py "2025 Bengaluru 10K Challenge"
    python scraper.py --url "https://mysamay.in/race/results/..."
"""

import asyncio
import argparse
import csv
import json
import re
import sys
import os
from datetime import datetime
from urllib.parse import urlparse, urlencode, quote_plus
from pathlib import Path

try:
    from playwright.async_api import async_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Platform Registry
# ---------------------------------------------------------------------------

PLATFORMS = {
    "mysamay": {
        "domains": ["mysamay.in"],
        "name": "MySamay",
        "search_suffix": "site:mysamay.in results",
    },
    "sts": {
        "domains": ["sportstimingsolutions.in"],
        "name": "Sports Timing Solutions",
        "search_suffix": "site:sportstimingsolutions.in results",
    },
    "timingindia": {
        "domains": ["timingindia.com"],
        "name": "Timing India",
        "search_suffix": "site:timingindia.com results",
    },
    "raceresult": {
        "domains": ["my.raceresult.com", "raceresult.com"],
        "name": "Race Result",
        "search_suffix": "site:raceresult.com",
    },
    "runners_quest": {
        "domains": ["runners.quest"],
        "name": "Runners Quest",
        "search_suffix": "site:runners.quest results",
    },
}


def detect_platform(url: str) -> str | None:
    """Identify the timing platform from a URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower().replace("www.", "")
    for key, platform in PLATFORMS.items():
        for d in platform["domains"]:
            if d in domain:
                return key
    return None


# ---------------------------------------------------------------------------
# Phase 1: Discovery - Find results URL via Google search
# ---------------------------------------------------------------------------

async def discover_results_url(race_name: str, browser) -> list[dict]:
    """
    Search Google for race results and return candidate URLs with platform info.
    Returns a list of {url, platform_key, platform_name} dicts.
    """
    page = await browser.new_page()
    candidates = []

    try:
        # Search Google for the race results
        query = f"{race_name} results"
        search_url = f"https://www.google.com/search?q={quote_plus(query)}"

        print(f"  Searching: {query}")
        await page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        await page.wait_for_timeout(2000)

        # Extract all links from search results
        links = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.href).filter(h => h.startsWith('http'))"
        )

        seen = set()
        for link in links:
            platform_key = detect_platform(link)
            if platform_key and link not in seen:
                seen.add(link)
                candidates.append({
                    "url": link,
                    "platform_key": platform_key,
                    "platform_name": PLATFORMS[platform_key]["name"],
                })

        # If no platform-specific results, try platform-specific searches
        if not candidates:
            for key, platform in PLATFORMS.items():
                query2 = f"{race_name} {platform['search_suffix']}"
                search_url2 = f"https://www.google.com/search?q={quote_plus(query2)}"
                await page.goto(search_url2, wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(1500)

                links2 = await page.eval_on_selector_all(
                    "a[href]",
                    "els => els.map(e => e.href).filter(h => h.startsWith('http'))"
                )
                for link in links2:
                    if detect_platform(link) == key and link not in seen:
                        seen.add(link)
                        candidates.append({
                            "url": link,
                            "platform_key": key,
                            "platform_name": platform["name"],
                        })

    except Exception as e:
        print(f"  Warning: Search failed ({e}). You can provide a URL directly with --url.")
    finally:
        await page.close()

    return candidates


# ---------------------------------------------------------------------------
# Phase 2 & 3: API Interception - Load page, capture data API calls
# ---------------------------------------------------------------------------

async def intercept_api_data(url: str, platform_key: str, browser) -> list[dict]:
    """
    Load the results page with Playwright, intercept all JSON API responses,
    and extract results data.
    """
    page = await browser.new_page()
    captured_data = []
    api_responses = []

    async def capture_response(response):
        """Capture JSON responses that look like results data."""
        try:
            content_type = response.headers.get("content-type", "")
            if "json" in content_type or "application/json" in content_type:
                body = await response.text()
                if len(body) > 50:  # Skip tiny responses
                    try:
                        data = json.loads(body)
                        api_responses.append({
                            "url": response.url,
                            "status": response.status,
                            "data": data,
                            "size": len(body),
                        })
                    except json.JSONDecodeError:
                        pass
        except Exception:
            pass

    page.on("response", capture_response)

    try:
        print(f"  Loading: {url}")
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)

        # For paginated results, try scrolling to trigger lazy loading
        for _ in range(3):
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await page.wait_for_timeout(1500)

        # Try clicking "Load More" / "Show All" buttons if present
        for selector in [
            "text=Load More", "text=Show More", "text=View All",
            "text=Next", "button:has-text('More')",
            ".load-more", ".show-more", ".pagination .next"
        ]:
            try:
                button = page.locator(selector).first
                if await button.is_visible(timeout=1000):
                    for _ in range(10):  # Click up to 10 times for pagination
                        try:
                            await button.click()
                            await page.wait_for_timeout(2000)
                            if not await button.is_visible(timeout=1000):
                                break
                        except:
                            break
            except:
                continue

        # Platform-specific extraction strategies
        if platform_key == "sts":
            captured_data = extract_sts_data(api_responses, page)
        elif platform_key == "mysamay":
            captured_data = extract_mysamay_data(api_responses, page)
        else:
            captured_data = extract_generic_data(api_responses, page)

        # If API interception didn't work, fall back to DOM scraping
        if not captured_data:
            print("  API interception found no results. Falling back to DOM scraping...")
            captured_data = await scrape_dom_table(page, platform_key)

    except Exception as e:
        print(f"  Error loading page: {e}")
        print("  Attempting DOM fallback...")
        try:
            captured_data = await scrape_dom_table(page, platform_key)
        except Exception as e2:
            print(f"  DOM fallback also failed: {e2}")
    finally:
        await page.close()

    return captured_data


def extract_sts_data(api_responses: list, page) -> list[dict]:
    """Extract results from SportsTimingSolutions API responses."""
    results = []

    for resp in api_responses:
        data = resp["data"]

        # STS typically returns results in a nested structure
        # Look for arrays of participant objects
        candidates = find_result_arrays(data)
        for arr in candidates:
            for item in arr:
                if isinstance(item, dict) and any(
                    k in item for k in ["bibno", "bib_no", "first_name", "finished_time", "gun_time"]
                ):
                    row = normalize_result_row(item)
                    if row:
                        results.append(row)

    return deduplicate_results(results)


def extract_mysamay_data(api_responses: list, page) -> list[dict]:
    """Extract results from MySamay API responses."""
    results = []

    for resp in api_responses:
        data = resp["data"]
        candidates = find_result_arrays(data)
        for arr in candidates:
            for item in arr:
                if isinstance(item, dict):
                    row = normalize_result_row(item)
                    if row:
                        results.append(row)

    return deduplicate_results(results)


def extract_generic_data(api_responses: list, page) -> list[dict]:
    """Generic extraction for unknown platforms."""
    results = []

    # Sort by response size (largest first, more likely to be results)
    sorted_responses = sorted(api_responses, key=lambda x: x["size"], reverse=True)

    for resp in sorted_responses:
        data = resp["data"]
        candidates = find_result_arrays(data)
        for arr in candidates:
            for item in arr:
                if isinstance(item, dict):
                    row = normalize_result_row(item)
                    if row:
                        results.append(row)

    return deduplicate_results(results)


def find_result_arrays(data, depth=0, max_depth=5) -> list[list]:
    """
    Recursively search a JSON structure for arrays that look like results data.
    Returns list of candidate arrays.
    """
    if depth > max_depth:
        return []

    candidates = []

    if isinstance(data, list) and len(data) > 0:
        # Check if this array contains result-like objects
        if isinstance(data[0], dict):
            score = score_result_array(data)
            if score > 2:
                candidates.append(data)

    if isinstance(data, dict):
        for key, value in data.items():
            # Prioritize keys that sound like results
            if isinstance(value, (list, dict)):
                candidates.extend(find_result_arrays(value, depth + 1, max_depth))

    return candidates


def score_result_array(arr: list) -> int:
    """Score how likely an array is to contain race results (higher = more likely)."""
    if not arr or not isinstance(arr[0], dict):
        return 0

    sample = arr[0]
    keys = set(k.lower() for k in sample.keys())
    score = 0

    # Strong indicators
    strong = ["bibno", "bib_no", "bib", "bib_number", "finished_time", "finish_time",
              "chip_time", "gun_time", "net_time", "pace", "rank", "overall_rank",
              "bracket_rank", "category_rank", "gender_rank"]
    for s in strong:
        if s in keys:
            score += 2

    # Moderate indicators
    moderate = ["first_name", "last_name", "name", "full_name", "runner_name",
                "participant", "age", "gender", "sex", "category", "race_name",
                "race_id", "club", "city", "country", "nationality"]
    for m in moderate:
        if m in keys:
            score += 1

    # Bonus for array length (race results are typically 50+ rows)
    if len(arr) > 20:
        score += 2
    if len(arr) > 100:
        score += 2

    return score


# Field name normalization map
FIELD_MAP = {
    # BIB
    "bibno": "bib", "bib_no": "bib", "bib_number": "bib", "bibnumber": "bib",
    "race_number": "bib", "start_number": "bib",
    # Name
    "first_name": "first_name", "firstname": "first_name",
    "last_name": "last_name", "lastname": "last_name",
    "full_name": "full_name", "fullname": "full_name", "name": "full_name",
    "runner_name": "full_name", "participant_name": "full_name",
    # Time
    "finished_time": "chip_time", "finish_time": "chip_time",
    "chip_time": "chip_time", "net_time": "chip_time", "chiptime": "chip_time",
    "gun_time": "gun_time", "guntime": "gun_time", "gross_time": "gun_time",
    # Pace
    "chip_pace": "pace", "pace": "pace", "avg_pace": "pace",
    "gun_pace": "gun_pace",
    # Rank
    "overall_rank": "overall_rank", "overallrank": "overall_rank",
    "bracket_rank": "category_rank", "category_rank": "category_rank",
    "gender_rank": "gender_rank",
    # Demographics
    "gender": "gender", "sex": "gender",
    "age": "age", "age_group": "age_group", "agegroup": "age_group",
    "category": "category", "race_name": "race_category",
    # Other
    "club": "club", "team": "club", "team_name": "club",
    "city": "city", "country": "country", "nationality": "nationality",
}


def normalize_result_row(item: dict) -> dict | None:
    """Normalize a single result row to standard field names."""
    row = {}

    for orig_key, value in item.items():
        normalized_key = FIELD_MAP.get(orig_key.lower())
        if normalized_key:
            # Convert value to string, handle nested objects
            if isinstance(value, dict):
                continue
            row[normalized_key] = str(value) if value is not None else ""

    # Must have at least a bib or name to be a valid result
    has_identity = any(k in row for k in ["bib", "full_name", "first_name"])
    has_timing = any(k in row for k in ["chip_time", "gun_time"])

    if has_identity:
        # Build full_name from parts if needed
        if "full_name" not in row and "first_name" in row:
            parts = [row.get("first_name", ""), row.get("last_name", "")]
            row["full_name"] = " ".join(p for p in parts if p).strip()
        return row

    return None


def deduplicate_results(results: list[dict]) -> list[dict]:
    """Remove duplicate rows based on bib number."""
    seen = set()
    unique = []
    for row in results:
        key = row.get("bib", "") or row.get("full_name", "")
        if key and key not in seen:
            seen.add(key)
            unique.append(row)
    return unique


# ---------------------------------------------------------------------------
# Fallback: DOM Table Scraping
# ---------------------------------------------------------------------------

async def scrape_dom_table(page, platform_key: str) -> list[dict]:
    """
    Fallback: scrape HTML tables from the rendered DOM.
    Works when API interception fails (e.g., data is server-rendered or in HTML tables).
    """
    results = []

    # Wait for any tables to appear
    try:
        await page.wait_for_selector("table", timeout=10000)
    except:
        print("  No tables found on page.")
        return results

    # Extract all tables
    tables = await page.query_selector_all("table")

    for table in tables:
        rows = await table.query_selector_all("tr")
        if len(rows) < 3:  # Need at least header + 2 data rows
            continue

        # Get headers
        header_row = rows[0]
        headers = []
        for cell in await header_row.query_selector_all("th, td"):
            text = (await cell.inner_text()).strip().lower()
            headers.append(text)

        if not headers:
            continue

        # Check if this looks like a results table
        results_keywords = {"bib", "name", "time", "finish", "rank", "pace", "position"}
        header_text = " ".join(headers)
        if not any(kw in header_text for kw in results_keywords):
            continue

        # Map headers to normalized names
        header_map = {}
        for i, h in enumerate(headers):
            for orig, norm in FIELD_MAP.items():
                if orig in h.replace(" ", "_"):
                    header_map[i] = norm
                    break
            else:
                # Try fuzzy matching
                if "bib" in h:
                    header_map[i] = "bib"
                elif "name" in h:
                    header_map[i] = "full_name"
                elif "finish" in h or "chip" in h or "net" in h:
                    header_map[i] = "chip_time"
                elif "gun" in h or "gross" in h:
                    header_map[i] = "gun_time"
                elif "rank" in h or "pos" in h:
                    if "overall" in h:
                        header_map[i] = "overall_rank"
                    elif "gender" in h or "category" in h:
                        header_map[i] = "category_rank"
                    else:
                        header_map[i] = "overall_rank"
                elif "pace" in h:
                    header_map[i] = "pace"
                elif "age" in h:
                    header_map[i] = "age_group"
                elif "gender" in h or "sex" in h:
                    header_map[i] = "gender"
                elif "category" in h or "race" in h:
                    header_map[i] = "category"
                elif "club" in h or "team" in h:
                    header_map[i] = "club"

        # Extract data rows
        for row in rows[1:]:
            cells = await row.query_selector_all("td")
            if len(cells) == 0:
                continue

            result_row = {}
            for i, cell in enumerate(cells):
                if i in header_map:
                    text = (await cell.inner_text()).strip()
                    result_row[header_map[i]] = text

            if result_row:
                results.append(result_row)

    return results


# ---------------------------------------------------------------------------
# Phase 3b: Platform-specific pagination handlers
# ---------------------------------------------------------------------------

async def handle_sts_pagination(page, url: str, api_responses: list) -> list[dict]:
    """
    SportsTimingSolutions often paginates results.
    Intercept the pagination API calls.
    """
    results = []

    # STS uses race_id and bracket selection. Try to select "All" categories
    try:
        # Look for bracket/category dropdowns
        selectors = await page.query_selector_all("select")
        for sel in selectors:
            options = await sel.query_selector_all("option")
            for opt in options:
                text = await opt.inner_text()
                if "all" in text.lower() or "overall" in text.lower():
                    await sel.select_option(label=text)
                    await page.wait_for_timeout(2000)
                    break
    except:
        pass

    return results


# ---------------------------------------------------------------------------
# Phase 4: CSV Output
# ---------------------------------------------------------------------------

# Preferred column order for output
COLUMN_ORDER = [
    "bib", "full_name", "first_name", "last_name", "gender", "age_group",
    "category", "race_category", "club", "city", "country", "nationality",
    "chip_time", "gun_time", "pace", "gun_pace",
    "overall_rank", "category_rank", "gender_rank",
]


def write_csv(results: list[dict], output_path: str):
    """Write results to CSV with consistent column ordering."""
    if not results:
        print("  No results to write.")
        return

    # Collect all fields present in the data
    all_fields = set()
    for row in results:
        all_fields.update(row.keys())

    # Order columns: known fields first (in preferred order), then extras
    ordered = [c for c in COLUMN_ORDER if c in all_fields]
    extras = sorted(all_fields - set(ordered))
    columns = ordered + extras

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print(f"\n  CSV written: {output_path}")
    print(f"  Rows: {len(results)} | Columns: {len(columns)}")
    print(f"  Fields: {', '.join(columns)}")


# ---------------------------------------------------------------------------
# Main Agent Orchestrator
# ---------------------------------------------------------------------------

async def run_agent(race_name: str = None, url: str = None, output: str = None):
    """Main agent entry point."""

    print("=" * 60)
    print("  Race Results Scraper Agent")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-setuid-sandbox"]
        )

        results_url = url
        platform_key = None

        # Phase 1: Discovery
        if not results_url:
            if not race_name:
                print("ERROR: Provide either --race or --url")
                await browser.close()
                return

            print(f"\n[Phase 1] Discovering results for: {race_name}")
            candidates = await discover_results_url(race_name, browser)

            if not candidates:
                print("  No results pages found. Try providing a direct URL with --url.")
                await browser.close()
                return

            print(f"\n  Found {len(candidates)} candidate(s):")
            for i, c in enumerate(candidates):
                print(f"    [{i+1}] {c['platform_name']}: {c['url'][:80]}...")

            # Use the first candidate (or let user choose interactively)
            results_url = candidates[0]["url"]
            platform_key = candidates[0]["platform_key"]
            print(f"\n  Using: {candidates[0]['platform_name']}")

        else:
            platform_key = detect_platform(results_url)
            if platform_key:
                print(f"\n  Detected platform: {PLATFORMS[platform_key]['name']}")
            else:
                print(f"\n  Unknown platform. Will use generic extraction.")
                platform_key = "generic"

        # Phase 2 & 3: Load page and intercept API data
        print(f"\n[Phase 2] Intercepting API data...")
        results = await intercept_api_data(results_url, platform_key, browser)

        # Phase 4: Output
        if results:
            if not output:
                safe_name = re.sub(r'[^\w\-]', '_', race_name or "race") 
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output = f"{safe_name}_results_{timestamp}.csv"

            print(f"\n[Phase 3] Writing results...")
            write_csv(results, output)
        else:
            print("\n  No results extracted. Possible reasons:")
            print("  - The page may require user interaction (category/race selection)")
            print("  - Results may be behind authentication")
            print("  - The platform may not be supported yet")
            print("\n  Debug: Try running with --debug to see captured API responses")

        await browser.close()

    return results


# ---------------------------------------------------------------------------
# Debug Mode: Dump all captured API responses
# ---------------------------------------------------------------------------

async def debug_page(url: str):
    """Debug mode: show all API calls made by a results page."""
    print(f"\n[DEBUG] Loading: {url}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page()

        all_responses = []

        async def capture(response):
            ct = response.headers.get("content-type", "")
            if "json" in ct:
                try:
                    body = await response.text()
                    data = json.loads(body)
                    all_responses.append({
                        "url": response.url,
                        "status": response.status,
                        "size": len(body),
                        "data_preview": json.dumps(data, indent=2)[:500],
                    })
                except:
                    pass

        page.on("response", capture)
        await page.goto(url, wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(5000)

        print(f"\n  Captured {len(all_responses)} JSON API responses:\n")
        for i, resp in enumerate(all_responses):
            print(f"  [{i+1}] {resp['url']}")
            print(f"      Status: {resp['status']} | Size: {resp['size']} bytes")
            print(f"      Preview: {resp['data_preview'][:200]}...")
            print()

        # Also dump the page title and key DOM info
        title = await page.title()
        print(f"  Page title: {title}")

        await browser.close()


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Scrape race results from Indian timing platforms",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scraper.py "2025 Bengaluru 10K Challenge"
  python scraper.py --url "https://mysamay.in/race/results/2f9d04d2-..."
  python scraper.py "TCS World 10K 2025" --output results.csv
  python scraper.py --url "https://sportstimingsolutions.in/results?q=..." --debug
        """
    )
    parser.add_argument("race", nargs="?", help="Race name to search for")
    parser.add_argument("--url", "-u", help="Direct URL to results page")
    parser.add_argument("--output", "-o", help="Output CSV filename")
    parser.add_argument("--debug", "-d", action="store_true", help="Debug mode: dump API responses")

    args = parser.parse_args()

    if not args.race and not args.url:
        parser.print_help()
        sys.exit(1)

    if args.debug and args.url:
        asyncio.run(debug_page(args.url))
    else:
        asyncio.run(run_agent(race_name=args.race, url=args.url, output=args.output))


if __name__ == "__main__":
    main()
