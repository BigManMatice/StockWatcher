import asyncio
from unittest.mock import AsyncMock, patch
import bot


async def run_spike_alert_test():
    print("🧪 Starting Spike Alert Verification Test...")

    # 1. Set threshold low to 0.1%
    bot.SPIKE_THRESHOLD_PCT = 0.1
    print(f"• Set alert threshold to: {bot.SPIKE_THRESHOLD_PCT}%")

    # 2. Inject baseline initial price (€100.00)
    bot.last_prices["APC.DE"] = 100.0
    print("• Injected baseline price for APC.DE: €100.00")

    # 3. Create mock channels for log and alert
    mock_log_channel = AsyncMock()
    mock_alert_channel = AsyncMock()

    def get_channel_side_effect(channel_id):
        if channel_id == 12345:
            return mock_log_channel
        if channel_id == 67890:
            return mock_alert_channel
        return None

    # 4. Mock a 5% price jump (€100.00 -> €105.00)
    fake_quote = {
        "ticker": "APC.DE",
        "price": 105.0,
        "prev_close": 100.0,
        "pct_change": 5.0,
    }

    print("• Simulating live quote update: €105.00 (+5.0% movement)...")

    with patch("alerts.get_all_global_watchlists", return_value=["APC.DE"]), \
         patch("data.get_finnhub_quote", return_value=fake_quote), \
         patch.object(bot.bot, "get_channel", side_effect=get_channel_side_effect), \
         patch("bot.LOG_CHANNEL_ID", 12345), \
         patch("bot.ALERT_CHANNEL_ID", 67890):

        # Execute 1 scanner loop iteration
        await bot.minute_market_scanner()

        # 5. Check if alert channel received the message
        if mock_alert_channel.send.called:
            print("✅ SUCCESS: Alert was triggered and dispatched to the alert channel!")
            call_kwargs = mock_alert_channel.send.call_args[1]
            embed = call_kwargs.get("embed")
            if embed:
                print(f"  └─ Embed Title: '{embed.title}'")
                print(f"  └─ Embed Content: '{embed.description.replace('\n', ' ')}'")
        else:
            print("❌ FAILURE: Scanner ran but no alert was sent to the channel.")


if __name__ == "__main__":
    asyncio.run(run_spike_alert_test())