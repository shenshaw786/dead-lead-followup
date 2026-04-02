# Dead Lead Follow-Up Automation Setup Guide

This guide explains how to set up, configure, and run the automated dead lead follow-up system.

## 1. Prerequisites

Before starting, ensure you have the following accounts and access:
*   **GoHighLevel (GHL):** Admin access to your Sub-Account to generate an API key.
*   **Fireflies.ai:** Access to the API key from your integrations page.
*   **Slack:** Permission to create a Slack App in your workspace.
*   **Google Workspace (Gmail):** Access to Google Cloud Console to create OAuth credentials.
*   **OpenAI:** An API key with access to GPT-4o.

## 2. Configuration (`.env` file)

1.  Navigate to the project directory: `/home/ubuntu/lead_followup`
2.  Copy the template file: `cp .env.example .env`
3.  Open `.env` and fill in the required credentials as described below.

### GoHighLevel Settings
*   `GHL_API_KEY`: Your Sub-Account API Key (found in Settings > Integrations > API Keys).
*   `GHL_LOCATION_ID`: Your Sub-Account Location ID (the long alphanumeric string in your GHL URL).
*   `GHL_DEAD_PIPELINE_STAGE_IDS`: Comma-separated list of pipeline stage IDs that define a dead lead (e.g., the ID for "Closed Lost").
*   `GHL_INACTIVITY_DAYS`: Minimum days since last activity to qualify as a dead lead (default: `14`).

### Fireflies.ai Settings
*   `FIREFLIES_API_KEY`: Found at app.fireflies.ai > Integrations > API.

### Slack Settings
1.  Go to [api.slack.com/apps](https://api.slack.com/apps) and create a new app.
2.  Under **OAuth & Permissions**, add the following Bot Token Scopes: `chat:write`, `incoming-webhook`.
3.  Install the app to your workspace and copy the **Bot User OAuth Token** (starts with `xoxb-`) to `SLACK_BOT_TOKEN`.
4.  Under **Basic Information**, copy the **Signing Secret** to `SLACK_SIGNING_SECRET`.
5.  In Slack, right-click the channel you want to use for approvals, select **View channel details**, and copy the Channel ID to `SLACK_CHANNEL_ID`.
6.  *Important:* Invite the bot to your channel by typing `/invite @YourBotName` in the channel.

### Gmail Settings
1.  Go to the [Google Cloud Console](https://console.cloud.google.com).
2.  Create a new project and enable the **Gmail API**.
3.  Go to **APIs & Services > Credentials** and create an **OAuth client ID** (Application type: Desktop app).
4.  Download the JSON file, rename it to `credentials.json`, and place it in the `/home/ubuntu/lead_followup` directory.
5.  Set `GMAIL_SENDER_EMAIL` to your sending email address.

### OpenAI Settings
*   `OPENAI_API_KEY`: Your OpenAI API key.
*   `OPENAI_MODEL`: Set to `gpt-4o` (or your preferred model).

## 3. Testing Connections

Before starting the server, run the connection test script to verify all credentials are correct:

```bash
cd /home/ubuntu/lead_followup
python3 test_connections.py
```

*Note on Gmail:* The first time you run this or start the server, a browser window will open asking you to log in to your Google account and authorize the app to send emails. Once authorized, a `data/gmail_token.json` file will be created for future use.

## 4. Slack Interactivity Setup

To enable the "Approve", "Edit", and "Reject" buttons in Slack:
1.  Your server must be accessible from the internet (e.g., deployed on a VPS or using ngrok locally).
2.  Go to your Slack App settings at [api.slack.com/apps](https://api.slack.com/apps).
3.  Click **Interactivity & Shortcuts** in the left sidebar.
4.  Toggle **Interactivity** to ON.
5.  Set the **Request URL** to: `https://YOUR_DOMAIN_OR_NGROK_URL/slack/interactions` (replace with your actual domain and ensure it points to port 8000).
6.  Save changes.

## 5. Running the Application

To start the automation server:

```bash
cd /home/ubuntu/lead_followup
bash start.sh
```

The server will start on port 8000 (or the port defined in `APP_PORT`).
The scheduler is automatically configured to run the dead lead check every Monday and Thursday at 8:00 AM EST.

### Manual Trigger
You can manually trigger a run for testing by sending a POST request:
```bash
curl -X POST http://localhost:8000/run-now
```

## References

[1] HighLevel API. "Search Opportunity". Available: https://marketplace.gohighlevel.com/docs/ghl/opportunities/search-opportunity/index.html
[2] Fireflies.ai API Documentation. "Transcripts query". Available: https://docs.fireflies.ai/graphql-api/query/transcripts
[3] Slack Developer Docs. "Creating interactive messages". Available: https://docs.slack.dev/messaging/creating-interactive-messages/
[4] Google Workspace Developers. "Create and send email messages". Available: https://developers.google.com/workspace/gmail/api/guides/sending
