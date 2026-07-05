// Cloudflare Worker — reverse proxy to Anthropic's API.
//
// Purpose: a mainland-China host (which can't reach api.anthropic.com directly)
// points ANTHROPIC_BASE_URL at this Worker; the Worker forwards to Anthropic
// from Cloudflare's overseas edge. Your API key travels through as-is inside
// the request headers — this Worker does not store or inject it.
//
// Optional hardening: set an ACCESS_TOKEN variable in the Worker settings, then
// send it from the client as header `x-relay-token`. Requests without a matching
// token get 403, so nobody else can use your Worker as an open Anthropic proxy.

const UPSTREAM = "https://api.anthropic.com";

export default {
  async fetch(request, env) {
    // Optional shared-secret gate.
    if (env && env.ACCESS_TOKEN) {
      if (request.headers.get("x-relay-token") !== env.ACCESS_TOKEN) {
        return new Response("forbidden", { status: 403 });
      }
    }

    const url = new URL(request.url);
    const target = UPSTREAM + url.pathname + url.search;

    const headers = new Headers(request.headers);
    headers.delete("host");
    headers.delete("x-relay-token");

    const init = {
      method: request.method,
      headers,
      redirect: "follow",
    };
    if (request.method !== "GET" && request.method !== "HEAD") {
      init.body = request.body;
    }

    const resp = await fetch(target, init);
    // Stream the response straight back (works for both JSON and SSE streaming).
    return new Response(resp.body, {
      status: resp.status,
      statusText: resp.statusText,
      headers: resp.headers,
    });
  },
};
