# tests/test_stockName.py
import stockName


def test_stock_name_mappings():
    assert stockName.get_mapped_ticker("AAPL") == "APC.DE"
    assert stockName.get_mapped_ticker("MSFT") == "MSF.DE"
    assert stockName.get_mapped_ticker("NVDA") == "NVD.DE"
    assert stockName.get_mapped_ticker("S&P500") == "CSPX.AS"
    assert stockName.get_mapped_ticker("TSLA") == "TSLA"

    assert stockName.get_display_name("AAPL") == "AAPL (APC.DE)"
    assert stockName.get_display_name("APC.DE") == "AAPL (APC.DE)"
    assert stockName.get_display_name("MSFT") == "MSFT (MSF.DE)"
    assert stockName.get_display_name("UNKNOWN") == "UNKNOWN"