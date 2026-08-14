# Going live — your specific checklist

You already have: a Creator account ✅, a Meta app ✅ ("TechTales Newsletter
Bot", Instagram use case), tester added and accepted ✅.

Your app is on Meta's **direct Instagram Login** flow (not the older Facebook
Login + Page flow) — that's the modern, preferred setup, and it's what the
publishing code already targets (`graph.instagram.com`). It does **not**
need a linked Facebook Page on the API side. Ignore any instructions that
mention `/me/accounts`, `pages_show_list`, or Graph API Explorer's Facebook
Login permission list — those are for the old flow and don't apply here.

Do steps 1–2 yourself (they need your login, so I can't do them from here).
Then come back and paste me the two values in step 3 — I'll wire them into a
test run and hand you back a preview to approve and publish.

---

## 1. Generate the token with the right scopes (5 min)

1. Go to <https://developers.facebook.com/apps> and open **TechTales
   Newsletter Bot**.
2. Left sidebar → **Instagram → API setup with Instagram login**.
3. Find your added tester and click **Generate token** next to it (this is
   a different control from Graph API Explorer — it's built into this page
   specifically for this flow).
4. Check both boxes:
   - `instagram_business_basic`
   - `instagram_business_content_publish`
5. Generate, then approve the login prompt on your Instagram account.

That token is scoped directly to your Instagram account — no Facebook Page
involved anywhere in this flow.

## 2. Get your numeric Instagram User ID + confirm the token works (2 min)

```bash
curl "https://graph.instagram.com/v21.0/me?fields=id,username,account_type&access_token=YOUR_TOKEN"
```

The `id` in the response is your `IG_USER_ID`. Then confirm publish scope is
active:

```bash
curl "https://graph.instagram.com/v21.0/YOUR_ID/content_publishing_limit?access_token=YOUR_TOKEN"
```

A JSON reply with a `quota_usage` number means both values are good.

**If the token from step 1 is short-lived** (check by calling
`https://graph.instagram.com/v21.0/YOUR_ID?fields=id&access_token=...` — an
expired/near-expiry token will start erroring within an hour), exchange it
for a long-lived one (~60 days) using the Instagram — not Facebook —
exchange endpoint:

```bash
curl "https://graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=YOUR_APP_SECRET&access_token=YOUR_TOKEN"
```

`YOUR_APP_SECRET` is on the app's **Settings → Basic** page. The response's
`access_token` is your long-lived `IG_ACCESS_TOKEN`.

## 3. What to send me

Once you've got them, paste these back (as plain text is fine, this is a
short-lived-in-conversation test, not something I'll commit anywhere):

- `IG_ACCESS_TOKEN` — the long-lived token from step 1 (exchanged in step 2 if needed)
- `IG_USER_ID` — the numeric `id` from step 2

You'll also need a public GitHub repo with this project pushed to it, and a
GitHub personal access token with `repo` scope (create one at
<https://github.com/settings/tokens> → **Generate new token (classic)**) —
that's what lets `test_publish.py` upload the JPEGs as a release asset for
Instagram to fetch. You don't need to send me that token; it's only used on
your own machine when you run the script.

## What happens after you send those

`test_publish.py` is already in this repo — it takes your token + ID as
environment variables, uploads the 6 approved JPEGs to a **public GitHub
release** on a repo you push, and calls `publish_carousel()` for real.

```bash
export IG_ACCESS_TOKEN="..."
export IG_USER_ID="..."
export GITHUB_REPOSITORY="yourname/ai-daily"   # must be PUBLIC
export GH_TOKEN="ghp_..."                       # a PAT with 'repo' scope

python test_publish.py editions/2026-08-14.json out/2026-08-14
```

It prints the caption and slide list, asks you to type `PUBLISH` to confirm,
then either publishes for real or tells you exactly what Instagram rejected.
Because my sandbox has no outbound network access, **you run this yourself**
— paste back whatever it prints (post ID, or an error) and we'll debug
together if needed. Nothing posts without you typing `PUBLISH`.

---

### Why I can't just publish it from here

This session's sandbox has zero outbound network access — every live HTTP
call (feeds, images, the Instagram API itself) is blocked at the proxy. That
is why every step above ends with something you run locally rather than me
calling the Instagram API directly. Once this is proven out, the same calls
run unattended inside GitHub Actions (Section 9 of `SETUP.md`), which has
normal internet access — so this is a one-time manual step to prove the
pipeline works, not the long-term workflow.
