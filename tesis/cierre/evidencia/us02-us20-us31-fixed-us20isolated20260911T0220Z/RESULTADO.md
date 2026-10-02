# US-02, US-20 and US-31 real-stack acceptance result

- US-02 exercises browser logout, authenticated backend revocation, cookie removal, access/refresh rejection and Back navigation.
- US-20 exercises the real Valkey → consumer → database Alert → SSE → toast chain. Reconnection is tested by stopping only a disposable lab SSE proxy, observing the original SSE request close, proving API health and refresh remain HTTP 200, restarting the proxy, waiting for the second successful SSE response before publishing, and then receiving one newly published event without reloading.
- US-31 exercises the real include-superseded filter and requires `parent_event_id` as visible linked text.
- No route interception, mocked network response, synthetic SSE response, external notification channel, or shared application state is used.
- The retained closure package is text-only: Playwright traces, screenshots and videos are disabled because binary browser artifacts cannot be reliably sanitized. JUnit, JSON, bounded logs and domain-specific JSON observations remain available.
- Tests and image builds run only from the frozen candidate snapshot inventoried by `candidate-files.sha256`; the mutable worktree is not the certified input.
