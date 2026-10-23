# stockName.py

# API Ticker mapping for fetching prices
API_RENAMES = {
    "AAPL": "APC.DE",
    "S&P500": "CSPX.AS",
    "CSPX": "CSPX.AS",
    "SXR8": "SXR8.DE",
}

# Display mapping for Discord !portfolio output
# Maps whatever ticker is in the database to your desired label format
DISPLAY_NAMES = {
    "AAPL": "AAPL (APC.DE)",
    "APC.DE": "AAPL (APC.DE)",
    "APC.LS": "AAPL (APC.DE)",
    "S&P500": "S&P500 (CSPX.AS)",
    "CSPX": "S&P500 (CSPX.AS)",
    "CSPX.AS": "S&P500 (CSPX.AS)",
    "SXR8": "S&P500 (CSPX.AS)",
    "SXR8.DE": "S&P500 (SXR8.DE)",
    "SXR8.LS": "S&P500 (SXR8.DE)",
}


def get_mapped_ticker(ticker: str) -> str:
    """Returns the underlying API lookup symbol."""
    cleaned = ticker.upper().strip()
    return API_RENAMES.get(cleaned, cleaned)


def get_display_name(ticker: str) -> str:
    """Returns the formatted label for Discord display."""
    cleaned = ticker.upper().strip()
    if cleaned in DISPLAY_NAMES:
        return DISPLAY_NAMES[cleaned]

    mapped = get_mapped_ticker(cleaned)
    if mapped != cleaned:
        return f"{cleaned} ({mapped})"

    return cleaned