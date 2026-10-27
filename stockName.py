from typing import Dict

TICKER_MAP: Dict[str, str] = {
    "AAPL": "APC.DE",
    "MSFT": "MSF.DE",
    "NVDA": "NVD.DE",
    "TSLA": "TSLA",
    "S&P500": "CSPX.AS",
    "FTSE": "VWCE.DE",
    "VWCE": "VWCE.DE",
    "FTSE ALL-WORLD": "VWCE.DE",
    "RBOT": "2B76.DE",
    "ROBOTICS": "2B76.DE",
    "2B76": "2B76.DE",
    "SMEA": "EUNK.DE",
    "EUNK": "EUNK.DE",
    "EUROPE": "EUNK.DE",
}

DISPLAY_NAMES: Dict[str, str] = {
    "AAPL": "AAPL (APC.DE)",
    "APC.DE": "AAPL (APC.DE)",
    "MSFT": "MSFT (MSF.DE)",
    "MSF.DE": "MSFT (MSF.DE)",
    "NVDA": "NVDA (NVD.DE)",
    "NVD.DE": "NVDA (NVD.DE)",
    "VWCE.DE": "Vanguard FTSE All-World (VWCE.DE)",
    "2B76.DE": "iShares Automation & Robotics (2B76.DE)",
    "EUNK.DE": "iShares Core MSCI Europe (EUNK.DE)",
    "CSPX.AS": "iShares S&P 500 (CSPX.AS)",
    "TSLA": "TSLA",
}


def get_mapped_ticker(user_input: str) -> str:
    clean = user_input.strip().upper()
    return TICKER_MAP.get(clean, clean)


def get_display_name(ticker: str) -> str:
    clean = ticker.strip().upper()
    if clean in DISPLAY_NAMES:
        return DISPLAY_NAMES[clean]

    for orig, mapped in TICKER_MAP.items():
        if mapped == clean:
            return f"{orig} ({clean})"

    return clean