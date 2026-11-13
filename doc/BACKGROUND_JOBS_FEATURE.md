# Background Jobs

English \| [日本語](BACKGROUND_JOBS_FEATURE.ja.md)

A copy, duplicate, move or delete can run in the **background** while you go on using
XeFM: browse, view files, even start another operation.

## Sending an operation to the background

- **When it asks to start.** The Copy, Duplicate and Move confirmations
  have a **Background** button. The operation starts with no progress dialog.
  Delete has none, because deleting is usually over at once. A long delete
  can still be sent back from its progress dialog.
- **While it runs.** Press the progress dialog's **Run in background**
  button. Its other button, **Cancel**, asks before it stops anything.

## Seeing what is running

The right end of the status bar shows the job:

```
⠋ Copy 42% +1
```

The spinner in front turns while the job runs. `+1` is how many more jobs
wait behind it.

**Click it**, or choose **Tools → Background Jobs…** (`jobs`), to list every
job: what it does, from where to where, and how far it is. The list keeps up
while it is open, and closes by itself once the last job has finished.

```
Copy 12 items  ~/photos → s3://bucket/backup — 42% (1.2G / 2.9G)
Move report.pdf  ~/Downloads → ~/Documents — paused, queued (Enter runs it now)
Copy notes.txt  ~/work → ~/backup — queued (Enter removes it)
```

- **Choose the running job** to bring its progress dialog back. From there
  you can watch it, cancel it, or send it back.
- **Choose a paused job** to run it now, in front, with its progress dialog.
- **Choose a queued job** that has not started to remove it from the queue.

## One at a time

Background jobs run **one after another**, in the order you sent them,
because they usually compete for the same disk or the same server. Only one
of them is ever running.

If you send an operation to the background while another job is running
there, it **pauses and waits its turn**. It pauses once the files it is
working on are done, never in the middle of a file: a transfer to a server
held open that long could time out. When its turn comes, it carries on where
it stopped.

An operation you start in front doesn't join the queue, but it doesn't write
beside the running job either: that job pauses, again once the file it is on
is done, and the operation in front starts as soon as it has. Until then its
progress dialog says `Waiting for Copy to pause…`. When the operation in front
finishes, or you send it to the background, the paused job carries on. The
status bar shows it meanwhile as `Copy 42% paused`.

So only one operation writes at a time. That is what lets each one notice what
another has written into its destination, and ask about it instead of merging
or skipping in silence (see
[File Operations](FILE_OPERATIONS_FEATURE.md#when-something-appears-at-the-destination-later)).

A job that only reads — reading tags, a flat view, an index search, comparing
files, an extension's checksum — neither waits nor makes anything wait: it
runs beside whatever is running.

## When a job needs an answer

If a background job reaches a question, such as a file that already exists at
the destination, it stops and waits. No dialog pops up in the middle of your
work. The status bar shows instead:

```
⚠ Copy
```

It is drawn highlighted, in the bar's colors swapped, and blinks once a second
for the first ten seconds so that you notice it; then it stays highlighted
until the question is answered.

Click it to open the jobs list, and choose the job. Its progress dialog comes back with the
question, and once you answer, it carries on. Send it back with **Run in
background** if you like.

## When a job finishes

It does what a foreground operation does: the panes refresh, and the log says
what was copied, moved or deleted, and what failed.

## Quitting

If background jobs are still running or queued, **Quit** says so and starts on
**Cancel**. Quitting anyway stops them part-way. Files already copied stay
where they are. XeFM waits a few seconds for the file in progress to be
cleaned up before it exits.

## Similar-file scans

[Find Similar Files](FIND_SIMILAR_FILES_FEATURE.md) scans appear in the same
status bar segment and jobs list. They are not background jobs in the sense
above: each runs as a program of its own, keeps running after you quit XeFM,
and doesn't count against the one-at-a-time queue.

## See also

- [File Operations](FILE_OPERATIONS_FEATURE.md): copying, moving, conflicts
  and cancelling
