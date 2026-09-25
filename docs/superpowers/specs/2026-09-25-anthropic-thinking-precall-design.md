# Thinking-aware pre-call token count

## Problem

The router's context-window pre-call check (`Router._count_pre_call_check_tokens`) counts every
block of the request prompt as one number for the whole model group, and
`_count_content_list` counts Anthropic `thinking` blocks. On `/v1/messages` traffic aimed at
non-Anthropic backends (e.g. vLLM), the Anthropic->chat bridge moves `thinking` blocks into
`reasoning_content` / `thinking_blocks`, which vLLM does not put in the prompt. The pre-call
estimate is then inflated and can falsely trip `ContextWindowExceededError` or route to the wrong
deployment. Proven by a reproducer: a 760 KB thinking block counted as ~78 real input tokens by
vLLM, yet the router saw 257461 and picked the long-context deployment.

Counting thinking is correct for deployments that receive the payload natively (Anthropic,
Bedrock, Vertex claude, openai_like passthrough with `/v1/messages` in `supported_endpoints`,
databricks claude via `supports_anthropic_thinking_payload`), so "always drop thinking" would
under-count a mixed group.

## Design

### token_counter.py

- `without_anthropic_thinking_blocks(messages) -> tuple[list, bool]`: returns a copy of the
  message list with `thinking` and `redacted_thinking` blocks removed from `content` lists, and
  whether any were removed. Messages without such blocks (and non-dict messages) pass through
  unchanged.
- `_count_content_list` gains a `redacted_thinking` branch counting `str(data)`. Today an
  unhandled `redacted_thinking` block raises `ValueError`, which the router swallows and returns
  deployments unfiltered, so the whole pre-call check silently no-ops on such requests.

### router.py

- `_count_pre_call_check_tokens` returns a frozen `PreCallTokenCounts(total, without_thinking)`
  (defined in token_counter.py, next to `offload_token_count`). When the request carries no
  thinking blocks, one count is taken and both fields are equal, so the hot path pays nothing
  extra for non-thinking traffic.
- `_pre_call_checks` picks, per deployment, `total` when
  `_deployment_receives_anthropic_thinking(model_info)` is True and `without_thinking` otherwise.
  The predicate reads the already-resolved `model_info` of the deployment and returns True when
  any of:
  - `ProviderConfigManager.get_provider_anthropic_messages_config(bare_model, provider)` is not
    None (native Messages provider),
  - `model_info["supported_endpoints"]` contains `"/v1/messages"` (openai_like passthrough, same
    check as the messages handler),
  - `supports_anthropic_thinking_payload(bare_model, provider)` (databricks claude replays
    thinking blocks into the payload).
  Anything unresolvable (missing provider/key, unknown provider enum value) is conservatively
  True, i.e. today's behavior.
- The error string reports the selected count. The sync path, the async off-loop path
  (`_acount_pre_call_check_tokens`) and both sync `_pre_call_checks` callers carry the pair
  unchanged; filtering logic is untouched.

## Tests (tests/test_litellm/test_router.py)

- Regression for the false rejection: an assistant message with a thinking block that exceeds
  `max_input_tokens` only when thinking is counted passes the pre-call check on a `vllm/...`
  deployment.
- The same request on an `anthropic/...` deployment still raises `ContextWindowExceededError`.
- A mixed group keeps the bridge deployment and filters the native one (or vice versa per limit).
- `openai_like`-style deployment with `supported_endpoints: ["/v1/messages"]` counts thinking.
- `redacted_thinking` no longer breaks counting and is included in `total`.
- Without thinking blocks `total == without_thinking`.
- End-to-end `router.aanthropic_messages` against a mock vLLM-style deployment: oversized thinking
  no longer trips the pre-call check.

Existing tests that read the return value of `_count_pre_call_check_tokens` /
`_acount_pre_call_check_tokens` switch to `.total`.

## Out of scope

- Changing what the bridge itself sends.
- `reasoning_content` / top-level `thinking_blocks` message keys, which the token counter already
  skips.
