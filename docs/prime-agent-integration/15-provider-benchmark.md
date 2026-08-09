# Provider Benchmark — measured, not estimated

Three providers, one workload, one ADOS. Nothing about ADOS changed between
runs: same MCP gateway, same `MissionEvidenceConnector`, same container image,
same workspace preparation, same acceptance rules. The only variable is the
provider block written into the session's `models.json`.

**Workload** (byte-identical across all three): fetch the synthetic incident's
evidence through the governed `FetchIncidentEvidence` capability and print it.

```
Run exactly this python:
    import ados, json
    r = await ados.run_capability('FetchIncidentEvidence', {})
    ev = r['result']['outcome']['output']['evidence']
    print(json.dumps(ev, indent=2))
Then say only: FETCHED
```

Harness: `bench_providers.py`, capturing `message_end.usage` for tokens and
`tool_execution_start.args.code` for the exact Python each model ran.

---

## Results

| Provider / model | Total | Model calls | Tool calls | Time to first response | Median call latency | Input tokens |
|---|---|---|---|---|---|---|
| NVIDIA NIM `openai/gpt-oss-120b` | **2568.0s** | **17** | 17 | — | ~110s | 4132 → 8690 |
| Groq `llama-3.3-70b-versatile` | **1.7s** (rejected) | 1 | 0 | **1.71s** | — | — (413) |
| Ollama `qwen3-4b-16k` (local) | **212.0s** | **2** | **1** | 101.4s | 106.0s | 4201 → 7624 |

---

## What each result means

### NVIDIA NIM — unsuitable for this workload

Latency is dominated by queueing, not computation, and the evidence is that it
does not track prompt size at all:

| input tokens | latency |
|---|---|
| 4,246 | 69.5s |
| 5,828 | 370.2s |
| 5,997 | **482.9s** |
| 8,340 | 254.7s |
| 8,690 | 119.6s |

The *largest* prompt was among the faster calls. Output was 6–204 tokens
throughout, so generation time cannot explain it either. At the median this is
~55 input tokens/second where a working endpoint does thousands.

It also took **17 model calls** to do what the same prompt achieved in 2 on
Qwen — an independent inefficiency, not a latency artifact.

### Groq — fast, but inadmissible at the free tier

```
413 Request too large for model `llama-3.3-70b-versatile` ...
on tokens per minute (TPM): Limit 12000, Requested 20729
```

Per-call speed is excellent: it answered in **1.71 seconds**. The blocker is
purely admission. Two facts worth recording separately, because conflating them
led to a wrong conclusion once already:

* **Per-call latency and TPM admission are different constraints.** Groq wins
  decisively on the first and fails outright on the second.
* **Providers count tokens differently.** NIM reports `input: 4132` for the
  same prompt Groq counts as `20729`. Groq's count is the one that gates
  admission, so NIM's accounting cannot be used to predict Groq's behaviour.
  An earlier revision of this document doubted the Groq result on exactly that
  basis and was wrong; the direct container test settled it.

### Ollama `qwen3:4b` @ 16k — current best candidate

12× faster end-to-end than NIM, and — more importantly — **2 model calls
instead of 17**, with a single tool call that ran the correct code and
succeeded in 0.98s.

Created with:

```
FROM qwen3:4b
PARAMETER num_ctx 16384
```

`num_ctx` matters: Ollama defaults to 4096, which silently truncates a ~4–9k
prompt rather than erroring. The model's native context is 262,144.

Honest caveat: it emitted **5,978 output tokens across 2 calls**. Thinking mode
is doing substantial work and accounts for most of the 212s. It reached the
right answer in one tool call, so this is not obviously a cost worth cutting —
but it is a cost, and it is why a 4B local model is not simply "fast".

---

## The 17-call loop

Under byte-identical conditions — same ADOS, same gateway, same container
image, same workspace, same prompt — Qwen issued **one** tool call. The loop
did not reproduce.

That rules out, by control rather than by argument:

* **the mission prompt** — the same prompt produced one clean call
* **Prime Agent's runtime** — same runtime, same version, no loop
* **ADOS** — unchanged throughout

leaving model behaviour as the explanation. **No ADOS-side loop limit was
added**: a guard against a defect that only one model exhibits would be a
permanent tax on every future model to work around a provider we are not
choosing.

---

## Recommendation

**Local Ollama `qwen3-4b-16k` as the acceptance and development configuration.**
No queue, no TPM ceiling, no per-call cost, and it completed the workload in the
fewest calls of the three.

**This is a test configuration, not an architectural dependency.** Nothing in
`orchestrate/runtime/` names a provider: `provider`, `model`, `provider_key_env`
and a full `models_json` are constructor arguments on `PrimeAgentRuntime`,
written into the session's own agent dir at start-up. Swapping providers is a
caller-side change.

The requirement that *is* architectural: the configured model must hold the
harness prompt and sustain a multi-turn tool loop. Choosing one that cannot is a
silent-failure mode — which is why provider errors are mapped into the ADOS
event stream (`auto_retry_start`/`auto_retry_end` → `runtime.provider.retry*`).
Two acceptance runs were spent rediscovering a 429 and a 413 that were sitting
unread in that stream.

---

## Measured facts vs assumptions

**Measured:** every number in the table above; the latency/token
non-correlation; `cacheRead: 0` on all 20 NIM calls; the Groq 413 body; the
673-char evidence payload; kernel tool execution at 10–480 ms; the Qwen
single-tool-call control.

**Assumption, not measured:** that NIM's latency is specifically free-tier
queueing. The *signature* is queueing — latency uncorrelated with work — but we
have no access to NIM's scheduler and did not test a paid tier.

**Assumption, not measured:** that Groq would perform well end-to-end if the
prompt fitted under 12k TPM. It never completed a single call, so its
multi-turn behaviour on this workload is unknown.

**Not tested:** any hosted frontier model, any paid tier, prompt caching on a
provider that supports it, or Qwen with thinking disabled.
