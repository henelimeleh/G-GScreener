from __future__ import annotations

# Approximate SIC -> liquid U.S. sector ETF mapping. This is intentionally broad.
# It is a context proxy, not a canonical GICS classification.

def sector_from_sic(sic_code: str | None, description: str = "") -> tuple[str, str]:
    try:
        sic = int(str(sic_code or "0"))
    except ValueError:
        sic = 0
    desc = (description or "").upper()

    if 1300 <= sic <= 1399 or 2900 <= sic <= 2999:
        return "XLE", "Energy"
    if 4900 <= sic <= 4999:
        return "XLU", "Utilities"
    if 6000 <= sic <= 6799:
        if 6798 <= sic <= 6799 or "REAL ESTATE" in desc or "REIT" in desc:
            return "XLRE", "Real Estate"
        return "XLF", "Financials"
    if 8000 <= sic <= 8099 or 2830 <= sic <= 2839 or "PHARM" in desc or "BIOTECH" in desc:
        return "XLV", "Health Care"
    if 4800 <= sic <= 4899 or 7800 <= sic <= 7899:
        return "XLC", "Communication Services"
    if 2000 <= sic <= 2199 or 5400 <= sic <= 5499:
        return "XLP", "Consumer Staples"
    if 5200 <= sic <= 5999 or 7000 <= sic <= 7099:
        return "XLY", "Consumer Discretionary"
    if 1000 <= sic <= 1499 or 2600 <= sic <= 2699 or 2800 <= sic <= 2829 or 2840 <= sic <= 2899 or 3000 <= sic <= 3399:
        return "XLB", "Materials"
    if 3570 <= sic <= 3579 or 3600 <= sic <= 3699 or 7370 <= sic <= 7379 or "SOFTWARE" in desc or "SEMICONDUCT" in desc or "COMPUTER" in desc:
        return "XLK", "Technology"
    if 1500 <= sic <= 1799 or 3400 <= sic <= 3999 or 4000 <= sic <= 4799 or 5000 <= sic <= 5199:
        return "XLI", "Industrials"
    return "SPY", "Broad / Unmapped"
