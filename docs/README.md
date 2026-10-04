# docs

Written notes: how the system is designed, why decisions were made, and what the datasets are.

`results.md` is the important one: a scoreboard of every requirement measured so far, then
one entry per measurement, written the week it is taken, not reconstructed in January.

`decisions.md` records why things were built the way they were, including every departure
from Phase A's Algorithm 1. `known-issues.md` lists what is found and not yet fixed.
`context/` is how each week's work went.

`architecture/` holds one pipeline diagram per slice: slice 3 (frames from files), slice 4
(the same pipeline fed from a camera through the queue) and slice 5 (the camera wall:
previews, two queues, liveness, a process per camera).
