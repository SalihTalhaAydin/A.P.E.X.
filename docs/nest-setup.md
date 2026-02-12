# Google Nest Thermostat Setup in Home Assistant

Once the Nest thermostat is added to Home Assistant, Apex can control it via the existing **climate** tool (set temperature, mode, preset, fan). No code changes in Apex are required.

This guide summarizes the steps to add the **Google Nest** integration in HA. Full official instructions and screenshots: [Home Assistant – Google Nest](https://www.home-assistant.io/integrations/nest/).

---

## Prerequisites

- **$5 US one-time fee** (Device Access). Use the same Google account that has access to your Nest devices.
- **Consumer Google account** (e.g. @gmail.com). Google Workspace and Advanced Protection Program are not supported.
- **Latest Home Assistant** (Pub/Sub setup changed Jan 2025).
- Your thermostat must be [supported by the SDM API](https://developers.google.com/nest/device-access/supported-devices) (previous-gen Google Nest thermostats are supported).

---

## 1. Remove old Google/Nest credentials (if any)

In HA: **Settings → Devices & services** → three dots (⋮) → check for existing Google or Nest integrations → **Delete** any you find so the new setup does not conflict.

---

## 2. Google Cloud Project

1. Go to [Google Cloud Console](https://console.developers.google.com/apis/credentials) and **Create project** (note the **Project ID** for later).
2. **APIs & Services → Library**: enable **Smart Device Management API** and **Cloud Pub/Sub API**.

---

## 3. OAuth consent screen

1. **APIs & Services → OAuth consent screen** → **External** → Create.
2. Fill **App name**, **User support email**, **Developer contact email** → Save and Continue.
3. **Scopes** → Save and Continue.
4. **Test users** → add your Google account (e.g. your @gmail.com) → Save and Continue.
5. Back on OAuth consent screen → **Publish App** so status is **In production** (avoids 7‑day logout in Testing).

---

## 4. OAuth credentials

1. **APIs & Services → Credentials** → **Create Credentials** → **OAuth client ID**.
2. Application type: **Web application**. Name it (e.g. "Home Assistant Nest").
3. **Authorized redirect URIs**: add `https://my.home-assistant.io/redirect/oauth`
4. Create and copy the **Client ID** and **Client Secret** (you’ll enter these in HA).

---

## 5. Device Access project ($5)

1. Go to [Device Access Registration](https://developers.google.com/nest/device-access/registration), accept terms, pay the **$5** fee.
2. Open [Device Access Console](https://console.nest.google.com/device-access/) → **Create project** → name it → **Next**.
3. Paste your **OAuth client ID** (from step 4) → **Next**.
4. Leave **Enable Events** unchecked for now → **Create project**. Copy the **Device Access Project ID**.

---

## 6. Pub/Sub topic (for device events)

1. [Cloud Console → Pub/Sub → Topics](https://console.cloud.google.com/cloudpubsub/topic/list) → **Create Topic** (e.g. Topic ID: `home-assistant-nest`). Note the full **Topic name**: `projects/<your-project-id>/topics/home-assistant-nest`.
2. On that topic → **Permissions** → **Add principal**:
   - New principal: `service-<project-number>@gcp-sa-prod.iam.gserviceaccount.com` (see [HA Nest docs](https://www.home-assistant.io/integrations/nest/) for the exact placeholder; or in Device Access Console the UI may show the service account to use).
   - Role: **Pub/Sub Publisher**.
3. In [Device Access Console](https://console.nest.google.com/device-access/) → your project → … next to **Pub/Sub topic** → **Enable events with PubSub topic** → enter the full **Topic name** → **Add & Validate**.

*(If the principal name is unclear, follow the “Enable events and Pub/Sub topic” section on the [official Nest integration page](https://www.home-assistant.io/integrations/nest/) for the current placeholder.)*

---

## 7. Add Nest in Home Assistant

1. **Settings → Devices & services** → **Add Integration** → **Nest**.
2. Enter when prompted:
   - **Cloud Project ID** (from step 2)
   - **Device Access Project ID** (from step 5)
   - **OAuth Client ID** and **OAuth Client Secret** (from step 4)
3. Complete the browser flow: choose your Google account, grant Nest permissions (thermostat access), accept “unverified app” if shown, then **Link account to Home Assistant**.
4. In HA, select or confirm the **Pub/Sub subscription** (HA can create one if needed) and finish the flow.

---

## 8. Naming in HA

Assign the thermostat to an **area** and set a **friendly name** per [device-naming.md](device-naming.md) (e.g. "Hallway Thermostat" or "Living Room Thermostat"). Then Apex and voice commands will match your naming.

---

## Troubleshooting

- **Can’t link / Error 400**: Remove any old Google/Nest integrations, double-check redirect URI `https://my.home-assistant.io/redirect/oauth`, and ensure OAuth consent is **In production** and your account is in Test users (or app is published).
- **No Pub/Sub topics found**: Ensure the topic exists in Cloud Console, the Publisher principal is set on the topic, and the Device Access project has “Enable events” set with that topic name.
- **Devices not found**: Use the same Google account that owns the Nest devices; re-run the integration and grant all requested permissions.

For more, see [Nest integration – Troubleshooting](https://www.home-assistant.io/integrations/nest/#troubleshooting).
