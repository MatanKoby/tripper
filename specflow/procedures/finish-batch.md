<!-- specflow:start - managed by specflow; do not edit inside these markers (your edits block specflow upgrade). Add your own notes outside them. -->
# Procedure: finish a claimed batch

Run this when wrapping up. `AGENTS.md` carries only the pointer to this file.

> **Commit & push follow the configured levers** (`config.commit` / `config.push` in
> `specflow/config.json`; see `AGENTS.md` → *Commit & push authority*). Wherever a step below says
> "commit" or "push": if `commit: user`, don't commit — alert the user and hand them the suggested
> message; if `push: user`, commit but don't push. Default is `agent` / `agent`.

## Wrap-up

1. Make the final work commit and push. **Note its short SHA** — you'll record it in `CLAIMS.md`.

   ```
   git log --oneline -1     # capture the SHA
   ```

2. Edit `CLAIMS.md`. Move the batch's entry from `## In progress` to the **top** of
   `## Completed`, adding:

   ```
   - Finished: YYYY-MM-DD HH:MM
   - Commit: <short SHA>
   ```

   Same UTC convention as `Started:`. Keep any `Handoff note:` / `Reclaim note:` lines — they're
   part of the historical record.

3. Add a "What shipped" summary under the entry — what changed, where, any manual prereqs,
   verification steps, follow-ups deferred. Match the format of existing `## Completed` entries.
   The point: a future agent (or you, after a context reset) can reconstruct the batch's outcome
   from this entry alone.

4. **Move the batch out of `BUILD_QUEUE.md`.** That file lists only *un-done* batches — a
   completed batch must not linger there or the next agent re-reads it as open work. Three edits:
   - Delete the batch's full section from `BUILD_QUEUE.md`.
   - Add a one-paragraph summary to `specflow/history/BUILD_QUEUE_DONE.md` (match the existing compact style —
     what shipped + key commit).
   - Drop the batch from any **pick-order pointer** line at the top of `BUILD_QUEUE.md`.

5. Commit `meta: complete batch-N` — covering `CLAIMS.md` **+ `BUILD_QUEUE.md` +
   `specflow/history/BUILD_QUEUE_DONE.md`** — and push.

## Hand the context back (if your agent supports context compaction)

6. **End every batch by offering a context handoff** (and do it whenever the context window grows
   heavy, not only at batch end). This is not optional bookkeeping. It is the moment the whole
   protocol pays off: you wrote everything durable to the repo (spec, `git log`, `BUILD_QUEUE.md`,
   `CLAIMS.md`) precisely so the transcript can be thrown away, and offering the reset now is how the
   user actually collects that benefit:

   - **Cheaper next batch.** Context carried across several batches bills every later token for no
     added value; a compact or a clear resets that.
   - **More reliable next batch.** Long contexts degrade attention and raise error rates, so the
     reset makes the next build more accurate, not only cheaper.
   - **A decision point.** This is the one moment the user can stop, redirect, or spend down cost
     before more work chains on. Skipping it silently takes that choice away.

   Do not talk yourself out of this as "noise." Repeating the offer at each boundary is the feature,
   not clutter: it is the only place the user gets to act on cost and context. Building several
   batches in a row without offering it once is exactly the failure this step exists to prevent.

   Decide what, if anything, must survive the reset:

   - **Nothing to carry:** everything is already durable in the repo. Don't write a keep-line at all
     (an empty compaction is just a slower restart). Suggest a plain clear/restart plus a one-line
     re-prompt (e.g. "continue the milestone").
   - **Something to carry:** suggest compacting, and keep *only* that, briefly.
     - **Keep** durable takeaways not recoverable elsewhere: a decision just made but not yet written
       down, a forward pointer to the next likely batch and why.
     - **Drop** blow-by-blow execution detail, specific file paths and SHAs (git and `CLAIMS.md` own
       those), resolved debug threads, intermediate states, and anything already in spec, queue,
       claims, or git.

   The test for each keep-line item: could a fresh agent reconstruct it from the repo? If yes, leave
   it out.

   **Close every finish with this line (keep the shape, fill the brackets):**

   > Batch N complete and committed. The repo is the source of truth, so this transcript is
   > disposable. Recommend `/compact` (or `/clear` plus a one-line re-prompt) before the next batch.
   > Keep-line: `<one line of what must survive, or "nothing to carry, it's all in the repo">`.

   A finish that does not end with this line is not done.

## Next

7. Decide: claim the next eligible batch (run `claim-batch.md`) or stop. Either is fine — don't
   auto-chain unless the user asked you to. A user's "continue" authorizes claiming the next batch;
   it does **not** waive the step 6 handoff line above. Chaining and checkpointing aren't in
   conflict: offer the line, then proceed on the user's call.
<!-- specflow:end -->
