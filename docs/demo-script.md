# Three-minute demo

Complete `make up` and [model setup](model-setup.md) before the presentation. Download and warm `qwen3:8b`; open the console with a healthy, freshly reset stack and traffic stopped. Do not include downloads or builds in the three-minute slot. The timing below assumes warm inference takes roughly 20–45 seconds; slower hardware or model retries can extend the demo. Keep the real loading state visible rather than substituting recorded output.

| Time | Action and narration |
| --- | --- |
| 0:00–0:15 | Click **Start traffic**. “These are two real Java services. Orders calls inventory. Every number comes from completed application requests; the agent will receive only read-only telemetry.” |
| 0:15–0:33 | Show request activity and the healthy services. “We first collect a full window. No data would mean unknown, not healthy.” Point out the time window and actual request count. |
| 0:33–0:50 | Click **Trigger fault**. “The operator can introduce a controlled inventory delay. The investigator has no access to that control or its state.” Watch actual errors and timeouts appear. |
| 0:50–1:06 | Compare orders timeouts and latency. “Inventory may eventually succeed while its caller times out. A process health check alone does not explain customer impact.” Allow the fault to fill the observation window. |
| 1:06–1:50 | Click **Investigate** with “Why are orders failing?” “The local model chooses its tools. Counts and percentiles are calculated in code. This timeline shows the calls and returned evidence.” Open a completed tool result while the investigation runs. |
| 1:50–2:10 | Read the actual diagnosis and open a cited trace. “Follow one orders error to its client span and inventory child span. The evidence can support a delay beyond the caller's timeout. It cannot by itself explain why inventory became slow.” Use the displayed values, confidence basis, and uncertainty. |
| 2:10–2:46 | Keep traffic running and click **Reset fault**. “Reset is my action. We compare 30 seconds before with 30 seconds after, allowing requests and exports to settle. Request volumes must be comparable.” Show the recovery countdown. |
| 2:46–3:00 | Read the measured recovery results. “These windows tell us whether failures stopped at a similar workload. Every diagnosis citation opens the evidence that was actually retrieved. This is open source and all inference stays local.” |

Do not read an expected diagnosis as if the model produced it. If the agent reports incomplete evidence, show what it retrieved and what is still missing. If the model is unavailable, state that no live AI investigation ran; application behavior and deterministic smoke checks can still be demonstrated separately.

For a longer engineering discussion, run the same question against a healthy window and compare its assessment. Stop traffic long enough for the observation window to become empty and demonstrate an honest incomplete assessment. These are separate live evaluations, not steps hidden inside the three-minute presentation.

Traffic stops at 360 seconds. If inference takes longer, restart traffic and allow a fresh window before resetting; a recovery comparison with insufficient volume must remain labeled incomplete.

The [incident](screenshots/incident.png), [healthy](screenshots/healthy.png), and [recovery](screenshots/recovery.png) screenshots are actual UI captures with adjacent JSON provenance records. The [verification record](verification.md) separates deterministic tests from live model runs and lists their limitations.
