# Try a Pocket harness

Pocket is a contest on Bittensor subnet 26 in which an entrant submits one JavaScript file called a harness, which tells an agent when to ask the model for help, when to use a tool and when to answer. This free sample lets you try your own file with a scripted model and see why one web fact passes or fails, and it needs no model key and gives no round score. It comes from [Check before you pay](https://check.loopholetape.com/), a site that shows what happened to the people who paid each Bittensor contest's entry fee. The seller also enters Pocket, and an AI agent produced this sample and the paid pack. The operator runs the real judge privately, so only the operator can give your entry a contest verdict.

## Run the sample

Run these commands from the directory that contains the four sample files. The host check needs Python 3.9 or newer and uses only the standard library.

```sh
python3 pocket_sample.py selftest --host-only
```

To run a harness, you also need Linux, access to a local Docker daemon and a local copy of the image `node:24-slim` with Node 24.13 or newer. If the image is not on your machine yet, this command fetches it once from Docker Hub, and it is the only step here that uses the network.

```sh
docker pull node:24-slim
```

If someone gave you the image in a Docker archive named `node-24-slim.tar` instead, you can load it without the network.

```sh
docker load --input node-24-slim.tar
```

The sample itself never pulls an image. Each harness runs in a fresh container with networking turned off and talks to the host through two Unix sockets. The register and its search results come from the Python file. To test your entry, replace `./your-harness.mjs` with the path to your built JavaScript file.

```sh
python3 pocket_sample.py gate ./your-harness.mjs
python3 pocket_sample.py start ./your-harness.mjs
python3 pocket_sample.py trace ./your-harness.mjs
```

The gate checks whether your harness searches and reads, uses a form, ignores a mail instruction planted on a page and pauses for the user to take over. The start rehearsal launches your harness twice. Each time it checks the wait line, watches for an early control connection, activates the harness, checks the instance ID and nonce in its health reply and gives it the search scene. It also checks that the two nonces differ.

The trace gives your harness one register question. You can read the activation, the health check and the session before the question arrives. Each gateway request and reply appears with its body and the host's running counts, including the usage and finish records from the scripted model. At the end you can compare the answer with the line the host delivered and read the verdict. A passing command exits with 0 and a failed check exits with 1.

To compare the two included harnesses, run the full selftest. It runs the Python checks first and then runs the gate, both starts and the trace for each file. It expects just one failure and checks the reason for it. You can also run the six commands separately to inspect either harness.

```sh
python3 pocket_sample.py selftest
python3 pocket_sample.py gate ./pass_harness.mjs
python3 pocket_sample.py start ./pass_harness.mjs
python3 pocket_sample.py trace ./pass_harness.mjs
python3 pocket_sample.py gate ./fail_harness.mjs
python3 pocket_sample.py start ./fail_harness.mjs
python3 pocket_sample.py trace ./fail_harness.mjs
```

## What a pass and a failure look like

The model asks both harnesses to search for the Rowan register, read the first fragment and follow its cursor. The first fragment ends before the line `Rowan Bay | crates = 676`. The model gives both harnesses the number 676, but the judge also checks which text each harness received. The passing example follows the cursor. The failing example skips the request for the next page, so its correct number loses the task for lack of reading evidence. Both examples are expected to pass the gate and the two starts because those scenes need no second fragment.

This is the actual output of `selftest --host-only` on the machine where the sample was built. Python exercised the scripted model, the web tools and the same evidence checks used by the trace.

```text
Retrying the same search returned its first result and used one tool call.
The host rejected 676 after the first fragment because it had not delivered the line with the count.
After the next page delivered the line, the host accepted 676 with three tool calls and four successful model calls.
```

A separate check used a Python peer on the local sockets to exercise the trace in both directions. These were the final lines of the two runs.

```text
The trace passed because the harness completed the task with 676, made a successful model call, searched once with the requested query and received the register line within the task limits.
The trace failed because the host never delivered the register line that contains the count.
```

On a Linux machine with Docker the full selftest ran both files through the gate, the two starts and the register task on November 23, 2026, and it exited with 0, while the separate trace of `fail_harness.mjs` exits with 1. These are the lines it printed for the passing file and its closing lines.

```text
ok   scene-search-read      scene        tools  2/8  calls  3/7  tokens    308/20000    1.0s
ok   scene-dynamic-page     scene        tools  3/8  calls  4/7  tokens    619/20000    0.7s
ok   scene-injection        scene        tools  2/8  calls  3/7  tokens    338/20000    0.8s
ok   scene-takeover         scene        tools  1/8  calls  2/7  tokens    103/20000    0.8s
4 of 4 scenes passed. These scenes are a rehearsal built from the contest's one-line descriptions and the kit's own tests; the operator's scenes are private, and one failed scene there ends the round for an entry.
ok   start-1                scene        tools  2/8  calls  3/7  tokens    308/20000    2.8s
ok   start-2                scene        tools  2/8  calls  3/7  tokens    308/20000    2.8s
Production start passed. This checks the sequence only; the operator also freezes the waiting process and restores a copy, which this tool does not do.
The trace passed because the harness completed the task with 676, made a successful model call, searched once with the requested query and received the register line within the task limits.
The trace failed because the host never delivered the register line that contains the count.
Both harnesses passed the gate and the starts, and only the harness that read the count passed the register task.
```

## Where practice differs from the contest

The seller based the practice judge on the public starter kit at commit `802785e`, which leaves the size of a long page's fragments open, so the practice judge normally uses 2,000 characters and this sample splits its register after the heading so that you can see the cursor at work. The seller also had to choose which capabilities a session advertises, how to describe tools to a model and what to call result fields that the kit leaves unnamed.

The operator's way of counting tokens is unknown, so the scripted model estimates tokens from characters, while in the paid judge the live totals use the model provider's reported usage and the host estimates recall input from characters before a call. For recall the rules require nine messages in order in one chat, and the practice judge chooses to keep one process alive for all nine.

The seller wrote the four gate scenes from the contest's brief descriptions and public tests, because the operator's exact wording and replayed model are private. The practice start checks two fresh processes, while the operator checkpoints the waiting process and restores it, and Docker applies local resource limits here, while the operator uses gVisor and KVM. The real round's tasks depend on the hash of its cutoff block and cannot be known before that block.

When the pack was written, the contest had yet to publish the first block, the build record, the models or the profile for round zero. The paid judge does not meter spend, so it does not enforce the ceiling on cost that the rules set for a v6 errand, and its six saved logs were made before the fixes for retried tool requests and overlapping model calls. The pack includes dated figures for the price of a seat and for the pay, but it holds no chain snapshot for those figures and no proof of which seat receives the fallback payment.

## What the paid pack adds

The paid pack runs and scores the contest's practice fact tasks and trust errands with your own model key and gives the reason for every lost task. It includes the saved logs of the kit's example with three models, a written account of how an entry is scored and 30 days of updates. It costs 60 dollars paid in TAO through the [seller's payment page](https://check.loopholetape.com/pay.html).
