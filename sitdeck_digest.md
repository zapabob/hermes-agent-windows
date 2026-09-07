# SitDeck OSINT Digest
_URL: https://app.sitdeck.com/#login_

## Global Pulse (public)
SitDeck — Open-Source Intelligence Dashboard
The world's largest open-source intelligence dashboard. Monitor conflicts, earthquakes, markets, and threats in real-time. 55+ widgets, 180+ live data feeds, 100% free.

## Dashboard extract
SIT
UATION
DECK
Loading data feed list
27%

## API captures (sample)
- `https://app.sitdeck.com/api/auth/me`
  ```
  {"user": {"id": "43c1fa36-9a5c-4a81-9c29-7003d71fe676", "email": "r.minegishi1987@gmail.com", "displayName": "zapabob", "emailVerified": true, "twoFactorEnabled": false, "tosAccepted": true, "onboardingCompleted": true, "planId": "free", "pendingPlanId": null, "pendingPlanInterval": null, "isAdmin": false}}
  ```
- `https://app.sitdeck.com/api/billing/config`
  ```
  {"publishableKey": "pk_live_51T3VEPBl0J87ACGjAL8LVa0lOgYgDnhZCixLtMuruaA3HNUUw5GsXqFODXelWEpB3Z5I1m7E4W35ncr3HTW5pv5800nesiQjid", "mode": "live"}
  ```
- `https://app.sitdeck.com/api/notifications/active`
  ```
  {"notification": null}
  ```

_Source: SitDeck browser crawl (user account). Not World Monitor MCP._