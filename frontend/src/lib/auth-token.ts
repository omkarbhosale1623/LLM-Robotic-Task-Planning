// Module-level holder for the current Supabase access token.
//
// The AuthProvider mirrors the session's access token here whenever it changes.
// The typed API client and the WebSocket hook read it to attach
// `Authorization: Bearer <token>` (REST) and `?token=<token>` (WS) without
// needing React context — keeping those modules plain/non-hook.

let _accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  _accessToken = token;
}

export function getAccessToken(): string | null {
  return _accessToken;
}
