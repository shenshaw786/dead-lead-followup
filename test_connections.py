"""
Connection Test Script
Run this script to verify all API credentials are working before starting the automation.

Usage: python3 test_connections.py
"""
import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()


async def test_ghl():
    print("\n🔍 Testing GoHighLevel (GHL) connection...")
    import httpx
    api_key = os.getenv("GHL_API_KEY")
    location_id = os.getenv("GHL_LOCATION_ID")

    if not api_key or not location_id:
        print("  ❌ GHL_API_KEY or GHL_LOCATION_ID not set in .env")
        return False

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://services.leadconnectorhq.com/opportunities/search",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Version": "2021-07-28",
                    "Accept": "application/json",
                },
                params={"location_id": location_id, "limit": 1},
            )
        if resp.status_code == 200:
            data = resp.json()
            total = data.get("meta", {}).get("total", 0)
            print(f"  ✅ GHL connected. Total opportunities in account: {total}")
            return True
        else:
            print(f"  ❌ GHL API error: {resp.status_code} — {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  ❌ GHL connection failed: {e}")
        return False


async def test_fireflies():
    print("\n🔍 Testing Fireflies.ai connection...")
    import httpx
    api_key = os.getenv("FIREFLIES_API_KEY")

    if not api_key:
        print("  ❌ FIREFLIES_API_KEY not set in .env")
        return False

    query = """query { user { user_id email name } }"""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.fireflies.ai/graphql",
                json={"query": query},
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
            )
        if resp.status_code == 200:
            data = resp.json()
            user = data.get("data", {}).get("user", {})
            print(f"  ✅ Fireflies connected. Account: {user.get('email', 'unknown')}")
            return True
        else:
            print(f"  ❌ Fireflies API error: {resp.status_code} — {resp.text[:200]}")
            return False
    except Exception as e:
        print(f"  ❌ Fireflies connection failed: {e}")
        return False


async def test_slack():
    print("\n🔍 Testing Slack connection...")
    from slack_sdk.web.async_client import AsyncWebClient
    from slack_sdk.errors import SlackApiError

    token = os.getenv("SLACK_BOT_TOKEN")
    channel = os.getenv("SLACK_CHANNEL_ID")

    if not token:
        print("  ❌ SLACK_BOT_TOKEN not set in .env")
        return False

    try:
        client = AsyncWebClient(token=token)
        auth = await client.auth_test()
        print(f"  ✅ Slack connected. Bot: {auth['bot_id']}, Team: {auth['team']}")

        if channel:
            # Try to post a test message
            msg = await client.chat_postMessage(
                channel=channel,
                text="🤖 *Lead Follow-Up Bot* — Connection test successful! This bot is now active.",
            )
            print(f"  ✅ Test message posted to channel {channel}")
        return True
    except SlackApiError as e:
        print(f"  ❌ Slack API error: {e.response['error']}")
        return False
    except Exception as e:
        print(f"  ❌ Slack connection failed: {e}")
        return False


async def test_gmail():
    print("\n🔍 Testing Gmail connection...")
    sys.path.insert(0, os.path.dirname(__file__))
    try:
        from app.gmail_client import verify_gmail_connection
        result = await verify_gmail_connection()
        if result:
            print("  ✅ Gmail connected successfully.")
        else:
            print("  ❌ Gmail connection failed. Check credentials.json.")
        return result
    except FileNotFoundError as e:
        print(f"  ❌ {e}")
        return False
    except Exception as e:
        print(f"  ❌ Gmail connection failed: {e}")
        return False


async def test_openai():
    print("\n🔍 Testing OpenAI connection...")
    from openai import AsyncOpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        print("  ❌ OPENAI_API_KEY not set in .env")
        return False

    try:
        client = AsyncOpenAI(api_key=api_key)
        resp = await client.chat.completions.create(
            model=os.getenv("OPENAI_MODEL", "gpt-4o"),
            messages=[{"role": "user", "content": "Say 'OK' in one word."}],
            max_tokens=5,
        )
        reply = resp.choices[0].message.content.strip()
        print(f"  ✅ OpenAI connected. Model response: '{reply}'")
        return True
    except Exception as e:
        print(f"  ❌ OpenAI connection failed: {e}")
        return False


async def main():
    print("=" * 60)
    print("  Dead Lead Follow-Up — Connection Test")
    print("=" * 60)

    results = {
        "GoHighLevel": await test_ghl(),
        "Fireflies.ai": await test_fireflies(),
        "Slack": await test_slack(),
        "Gmail": await test_gmail(),
        "OpenAI": await test_openai(),
    }

    print("\n" + "=" * 60)
    print("  RESULTS SUMMARY")
    print("=" * 60)
    all_passed = True
    for service, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}  {service}")
        if not passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("\n🚀 All connections verified! You're ready to run the automation.")
        print("   Start the server with: bash start.sh")
    else:
        print("\n⚠️  Some connections failed. Please fix the issues above before starting.")
    print()


if __name__ == "__main__":
    asyncio.run(main())
