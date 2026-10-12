# PvPoke cloud prototype (unpublished)

This is a **single-user** prototype using the existing local PvPoke Matrix automation code. It does not replace PvPoke and does not perform GPT IV selection; ChatGPT does that after reading measured results.

## Deployment outline
1. Upload these files to a private GitHub repository, or use a host that supports directory/Dockerfile deployments.
2. Connect that repo to Railway (or an equivalent host) and create a Dockerfile-backed service.
3. In the host's *secret environment variables* create `PVP_API_KEY`: a random string of **32 or more characters**. Do not put it in a source file, plugin ZIP, or ChatGPT message.
4. Allocate about **2 GB RAM or more** for Chromium. A 512 MB free tier is unlikely to be reliable; check billing before deploying.
5. Enable HTTPS on the host, retain exactly one application replica and stable `PORT`. The platform sets `PORT` if needed.
6. Check `https://YOUR-REAL-HOST/health`. This checks only the Python MCP web server, **not** battle results.
7. From a **trusted local client**, test initialize, tools/list, tools/call with Authorization: `Bearer <YOUR_SECRET>` and a real PvPoke small battle before connecting ChatGPT.
8. Once verified, update the **existing** PvPoke IV Selector plugin's `mcp.json` with that real HTTPS `/mcp` URL, transport and API-key auth. Supply secret via the host's connection flow; never in `mcp.json`.

## Test locally (on a Linux PC with Docker)
`docker build -t pvpoke-cloud .`
`docker run --rm -p 127.0.0.1:8787:8787 -e PVP_API_KEY=<YOUR_RANDOM_SECRET> pvpoke-cloud`

Then send `POST /mcp` with the Authorization header. Requests with missing or incorrect keys return 401.

## Limitations and warnings
- Still a proof of concept. ChatGPT remote MCP compatibility has **not** been verified.
- Uses a small MCP subset, with only JSON and local process state, no durable job ID, cancellation, quotas, or multi-user tenancy.
- Do not publish or make requests before configuring a strong secret and TLS. Secrets must stay in the host's environment settings.
- Docker contains Chromium with `--no-sandbox` from the existing code. Only navigate to the predefined PvPoke page. Host should isolate the container and constrain privileges.
- Result state, caches and files are ephemeral unless a persistent volume is mounted; the same instance must handle status/result calls for an active job.
- The underlying web backend fetches live PvPoke data and requires outgoing internet access.
- Check compatibility, source legitimacy, and PvPoke terms of use before deploying automations at scale.
- Before using for rankings, manually verify level/CP and at least one battle rating for every unique shield scenario.
